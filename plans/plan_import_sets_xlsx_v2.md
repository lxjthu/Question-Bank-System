# 套题导入重构规划 v2

## 背景与问题

当前 `POST /api/interview/sessions/import-xlsx` 需要传入 `pool_id`，即用户必须**预先选择**一个题库池，套题才能导入。这导致：
1. 跨机器迁移时，目标机器可能没有任何题库池
2. 场次名固定为 `[导入] YYYY-MM-DD HH:MM`，不可自定义
3. 对于"是否加入已有题库池"的决策被强迫提前（而非在看到导入内容后决定）

## 目标

将套题导入改为**以场次为核心**的迁移流程：

1. 用户自定义场次名（支持语义命名，便于识别）
2. 系统自动决定题库池策略（无池→新建，有池→询问）
3. 导入的套题场次出现在「套题管理」面板
4. 对于加入已有题库池的情况，自动比对重复题目并给出清晰反馈

---

## 新 UX 流程

```
用户点击「导入套题记录」
       ↓
弹出对话框：
  [场次名称] ___________  (必填，如：2026春季招聘)
  [选择文件] ___________  (.xlsx)
  [确认导入]
       ↓
后端第一步：解析文件，统计题目数量，查询系统现有池
       ↓
  ┌── 系统无任何题库池 ──────────────────────┐
  │  自动创建新池，名为 "{场次名称}-题库池"   │
  │  将 Excel 中所有题目导入该池（无重复比对） │
  │  创建场次，关联该新池                     │
  └───────────────────────────────────────────┘
  ┌── 系统已有题库池 ─────────────────────────┐
  │  返回池列表给前端                          │
  │  前端弹出选择对话框：                      │
  │    · 新建独立题库池（名为 "{场次名称}-题库池"）│
  │    · 加入已有题库池 [下拉选择]             │
  │  用户确认后继续                            │
  └───────────────────────────────────────────┘
       ↓
后端第二步：执行导入
  - 新建题库池模式：全量创建题目+加入池
  - 加入已有池模式：
      · Excel中每道题与已有池比对（按题干文本相似或 question_id）
      · 已存在：跳过加入池，标记 status="已有题目"
      · 不存在：创建题目（若本地没有）+加入池，标记 status="新增"
       ↓
创建 interview_sessions 记录（使用自定义场次名）
创建 interview_sets 记录（还原套题结构，question_id 映射到本地ID）
       ↓
前端展示导入摘要：
  ✓ 场次已创建：{场次名称}
  ✓ 共导入套题 N 套
  ✓ 题目：新增 X 道 / 已有 Y 道（跳过）
  [前往套题管理]  → 自动切换到 iv-session 面板
```

---

## API 设计

### 现有接口重构

**`POST /api/interview/sessions/import-xlsx`**（保留路由，改变行为）

**Request（multipart/form-data）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | ✓ | .xlsx 文件 |
| `session_name` | string | ✓ | 自定义场次名 |
| `pool_mode` | string | ✓ | `"new"` 或 `"existing"` |
| `pool_id` | int | 仅 `pool_mode=existing` | 目标已有池ID |

**新增辅助接口（用于前端决策步骤）：**

**`POST /api/interview/sessions/import-xlsx/prepare`**

只解析文件，返回：
```json
{
  "ok": true,
  "question_count": 32,
  "set_count": 8,
  "existing_pools": [
    {"id": 1, "pool_name": "春招题库", "question_count": 45},
    {"id": 2, "pool_name": "秋招题库", "question_count": 60}
  ]
}
```

前端根据 `existing_pools.length`:
- `0`：直接进入第二步（无需选池）
- `≥1`：显示池选择对话框

---

## 比对逻辑（加入已有池时）

优先级从高到低：

1. **精确匹配 question_id**：Excel的 `question_id` 列与本地 `questions.id` 相同 → 直接复用
2. **如 question_id 不存在本地**：从 Excel 行创建新题目 → 加入池

> 注：不做题干文本模糊比对（避免误判，且跨机器 question_id 通常稳定）

### 重复判定（题目已在池中）

检查 `interview_pool_questions` 表：
- `pool_id = 目标池` AND `question_id = 本地题目ID` → 已存在，跳过加入，状态=`"已有题目"`

---

## 文件改动范围

### 1. `app/interview_routes.py`

- **新增函数** `prepare_import_sets_xlsx()`（`POST /prepare` 路由）
- **重构** `import_sets_xlsx()`：
  - 去掉原 `pool_id` 表单参数
  - 新增 `session_name`、`pool_mode`、`pool_id`（可选）参数
  - `pool_mode=new`：调用 `_create_pool_for_import(session_name)` 新建池
  - `pool_mode=existing`：直接使用传入 `pool_id`
  - 题目处理改为按 question_id 精确匹配 → 跳过/创建
  - 场次名使用 `session_name` 参数
  - 返回结果增加 `questions_added`/`questions_skipped`/`pool_id`/`pool_name`

### 2. `app/templates/index.html`

- **重构** `ivImportSetsXlsx()` 函数：分两步（prepare → 选池 → 正式导入）
- **新增** 池选择对话框 HTML（modal）
- **导入完成后** 自动调用 `ivSwitchPanel('iv-session')` + `ivLoadSessions()`

---

## 数据库变更

**无需变更表结构**。

仅逻辑变化：
- 新建题库池时自动命名为 `{session_name}-题库池`
- 场次的 `session_name` 改为使用用户输入值（原来固定为`[导入]...`）

---

## 实施步骤

1. **后端 - prepare 接口**
   - 新增 `POST /api/interview/sessions/import-xlsx/prepare`
   - 解析Excel文件，统计题目数、套题数
   - 查询 `interview_pools` 返回池列表

2. **后端 - 重构 import 接口**
   - 修改 `import_sets_xlsx()`
   - 支持 `pool_mode=new` 时自动建池
   - 支持 `pool_mode=existing` 时精确比对重复
   - 场次名改为 `session_name` 参数

3. **前端 - 重构导入UI**
   - 第一步：场次名+文件选择 → 调用 prepare
   - 第二步（有已有池时）：显示选择对话框
   - 第三步：调用正式导入接口，显示摘要

4. **前端 - 导入完成后跳转**
   - 自动切换到套题管理面板
   - 高亮新建的场次

---

## 不在本次范围内

- 修改题库池题目导入（`import_pool_xlsx`）逻辑，该接口保持不变
- 套题导出逻辑不变
- 迁移历史已导入的套题记录

---

## 完成标志

- [x] prepare 接口可正确返回池列表
- [x] 无已有池时全自动导入，无需手动选择
- [x] 有已有池时弹出选择对话框
- [x] 场次名使用用户输入值
- [x] 导入完成后自动跳转到套题管理
- [x] 摘要中显示新增/跳过的题目数量
