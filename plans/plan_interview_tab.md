# 面试抽题 Tab 功能规划

版本：v1.0
日期：2026-03-25
状态：待确认

---

## 一、功能概述

在现有 7 个 Tab 基础上，新增第 8 个 Tab：**面试抽题**（`interview-draw`）。

该 Tab 支持从题库筛选题目建立面试题库池，配置每套题的题型结构，批量生成套题并标记使用状态，以及导出带答案的 Word 文档交给面试官。

---

## 二、功能模块拆解

### 模块 1：题库筛选（建立面试题库池）

**目标**：从 `exam_system.db` 的 `questions` 表中，按条件筛选题目加入"面试题库池"。

**筛选条件（UI 控件）**：
| 筛选字段 | 对应数据库字段 | 控件类型 |
|---------|--------------|---------|
| 科目 | `subject` | 多选下拉（从 `/api/questions/subjects` 动态加载） |
| 题型 | `question_type` | 多选下拉（从 `/api/question-types` 加载） |
| 难度 | `difficulty` | 多选下拉（easy/medium/hard） |
| 知识点 | `knowledge_point` | 文本输入（模糊匹配） |
| 考点/标签 | `tags` | 文本输入（模糊匹配） |
| 语言 | `language` | 单选下拉（全部/zh/en/both） |
| 排除已使用 | `is_used` | 勾选框（默认勾选，排除 is_used=true 的题目） |
| 排除已在池中 | — | 勾选框（默认勾选，排除已加入面试池的题目） |

**操作**：
- 「预览筛选」：显示命中题目数量和列表预览（仅显示题号、题型、科目、知识点，不显示完整题干）
- 「加入面试池」：将筛选结果批量加入面试题库池（写入 `interview_pool` 表）
- 「清空面试池」：清空当前面试池（确认弹窗）
- 面试池当前状态展示：按题型分类显示各类型题目数量

---

### 模块 2：题型设置（套题模板配置）

**目标**：配置每套面试题由哪些题目组成（类似"套餐配置"）。

**UI 设计**：
- 每行代表套题中的一道题（一个"槽位"）
- 每个槽位配置：
  - 题型（必选，从 `question_type` 列表选择）
  - 语言偏好（可选，zh/en/both/任意）
  - 难度偏好（可选，easy/medium/hard/任意）
  - 备注（可选，如"材料分析题"）
- 支持「添加一行」「删除一行」
- 「保存配置」：持久化到 `interview_configs` 表（JSON 形式）

**示例配置**：
```
槽位1: 题型=简答题, 语言=zh, 难度=medium
槽位2: 题型=材料分析, 语言=zh, 难度=hard
槽位3: 题型=简答题, 语言=en, 难度=任意
```

**配置校验**：
- 每个槽位必须选择题型
- 套题至少包含 1 个槽位

---

### 模块 3：随机抽选展示（单次抽题）

**目标**：单次从面试题库池中抽取一套题展示，抽出的题目自动标记为"本轮已抽"，不再复用。

**UI 设计**：
- 「抽取一套题」按钮
- 抽取结果展示区：
  - 按槽位顺序显示，每道题显示：题号（如 Q001）、题型、完整题干（支持 HTML 渲染）
  - 每道题下方折叠显示「查看答案」（答案/参考答案）
- 显示当前面试池剩余可抽数量（每个题型剩余数）

**抽题逻辑（后端）**：
1. 按套题模板，每个槽位在面试池中随机选一道满足条件（题型/语言/难度）的未抽题目
2. 选中后在 `interview_pool` 表将该题标记为 `drawn=true`, `drawn_at=当前时间`
3. 若某槽位无可用题目，返回警告（不执行本次抽取）

**注意**：此处"抽选"仅用于临时展示，不产生永久套题记录；"套题生成"才是批量生成持久化套题（见模块 5）。

---

### 模块 4：套题及答案导出（Word）

**目标**：将已生成的套题（或选定套题）导出为 Word 文档，供面试官核对。

**导出格式**：
- 文件名：`面试套题_{套题名称}_{日期}.docx`
- 文档结构：
  ```
  第1套（套题编号：SET-001）
  ─────────────────────────
  第1题（简答题）
  题目：[完整题干]

  参考答案：[答案内容]

  第2题（材料分析）
  ...

  ═════════════════════════
  第2套（套题编号：SET-002）
  ...
  ```
- 每套题之间插入分页符
- 答案单独一页（可选：题目在前，答案在后；或题答紧跟）

**导出选项**：
- 选择导出哪些套题（全部 / 仅未使用 / 手动多选）
- 是否含答案（含/不含，生成两份文件）

**复用现有能力**：利用 `app/utils.py` 中已有的 Word 导出工具（`convert_html_to_word_para`、`export_exam_to_word`）。

---

### 模块 5：套题生成及标记

**目标**：批量生成 N 套题，与面试场次挂钩，标记使用状态。

**UI 设计**：

**5a. 生成面板**：
- 输入：
  - 面试场次名称（如"2026春季招聘第一轮"）
  - 面试人数（如 10 人）
  - 备用倍数（如 3 倍，则生成 30 套题，默认 3）
  - 分值（每题分值，导出时显示）
- 「生成套题」按钮
- 生成后展示套题列表（见下）

**5b. 套题列表**：
| 字段 | 说明 |
|-----|-----|
| 套题编号 | SET-001, SET-002... |
| 面试场次 | 所属场次名称 |
| 包含题目 | 题号列表（如 Q12, Q45, Q78） |
| 状态 | 未使用 / 已使用 |
| 使用时间 | 标记为已使用的时间 |
| 操作 | 「标记使用」「查看详情」「释放」 |

**5c. 状态流转**：
```
未使用 → [标记使用] → 已使用（进入已使用池，不再被分配）
已使用 → [释放] → 未使用（回到可用池，可再次分配）
```

**5d. 批量操作**：
- 「批量标记使用」：选中多套后批量标记
- 「导出选中套题」：快速导出选中的套题 Word

---

### 模块 6：警告系统

**触发时机**（后端校验）：

| 情形 | 警告内容 | 操作提示 |
|-----|---------|---------|
| 面试池题目总数不足以生成 N 套 | "面试池中可用题目不足，当前可生成 X 套，需要 N 套" | 「去筛选更多题目」跳转到筛选面板 |
| 某个槽位题型题目不足 | "槽位 [Y]（题型：简答题）仅剩 M 道题，无法生成 N 套" | 「去增加[简答题]题目」+ 「去AI出题并导入」 |
| 题型配置中某题型在面试池中为 0 | "面试池中没有[英文题]，请先加入该题型的题目" | 「去筛选题目」+ 「去AI出题」 |
| 抽选时某槽位无可用题 | "题型[简答题]已全部抽完，请释放已使用的套题或补充题目" | 「去补充题目」 |

**警告 UI**：
- 模态弹窗（非 JS alert），带醒目图标
- 操作按钮直接跳转至对应功能区（切换面板或跳转到题型管理 Tab）

---

## 三、数据库设计

### 新增表（在 `exam_system.db` 中，SQLAlchemy 管理）

#### 3.1 `interview_pool`（面试题库池）
```sql
CREATE TABLE interview_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id VARCHAR(64) NOT NULL,      -- 关联 questions.question_id
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    drawn BOOLEAN DEFAULT FALSE,            -- 是否已被抽取过（不可再抽）
    drawn_at DATETIME,                      -- 抽取时间
    FOREIGN KEY (question_id) REFERENCES questions(question_id) ON DELETE CASCADE,
    UNIQUE (question_id)                    -- 同一题不能重复加入池
);
```

#### 3.2 `interview_configs`（套题配置模板）
```sql
CREATE TABLE interview_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(128) DEFAULT 'default',    -- 配置名称
    slots_json TEXT NOT NULL,               -- JSON: [{type, language, difficulty, remark}, ...]
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 3.3 `interview_sessions`（面试场次）
```sql
CREATE TABLE interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name VARCHAR(256) NOT NULL,     -- 场次名称
    interview_count INTEGER NOT NULL,       -- 面试人数
    sets_multiplier INTEGER DEFAULT 3,      -- 套题倍数
    score_per_question TEXT,                -- 每题分值（JSON：{slot_index: score}）
    config_id INTEGER,                      -- 关联 interview_configs.id
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (config_id) REFERENCES interview_configs(id)
);
```

#### 3.4 `interview_sets`（套题记录）
```sql
CREATE TABLE interview_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_code VARCHAR(32) NOT NULL,          -- 套题编号，如 SET-001
    session_id INTEGER NOT NULL,            -- 关联 interview_sessions.id
    question_ids_json TEXT NOT NULL,        -- JSON: ["q1", "q2", "q3"]（按槽位顺序）
    is_used BOOLEAN DEFAULT FALSE,          -- 是否已使用
    used_at DATETIME,                       -- 使用时间
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES interview_sessions(id)
);
```

### 迁移方式
在 `app/factory.py` 的 `_migrate_db()` 函数中，追加 4 条 `CREATE TABLE IF NOT EXISTS` 语句（幂等），无需额外迁移脚本。

---

## 三-补充、Excel 导入导出设计

### A. 面试题库池（interview_pool）导出/导入

**导出（pool → Excel）**：
- 导出当前面试池所有题目到 `.xlsx`
- 每行一道题，列包含：
  | 列名 | 来源字段 |
  |-----|---------|
  | question_id | questions.question_id |
  | question_type | questions.question_type |
  | subject | questions.subject |
  | difficulty | questions.difficulty |
  | language | questions.language |
  | knowledge_point | questions.knowledge_point |
  | tags | questions.tags |
  | content | questions.content（HTML → 纯文本，去除标签） |
  | answer | questions.answer |
  | reference_answer | questions.reference_answer |
  | drawn | interview_pool.drawn |
  | drawn_at | interview_pool.drawn_at |
  | added_at | interview_pool.added_at |
- 文件名：`面试题库池_{日期}.xlsx`

**导入（Excel → pool）**：
- 上传包含 `question_id` 列的 Excel 文件
- 系统根据 `question_id` 检查题目是否存在于本地题库
- 若存在：将其加入面试池（跳过已在池中的）
- 若不存在（跨机器迁移场景）：**同时写入 `questions` 表**，完整导入题目信息后再加入池
- 返回统计：成功导入 X 道，已跳过 Y 道，新建题目 Z 道

### B. 套题记录（interview_sets）导出/导入

**导出（sets → Excel）**：
- 导出选定场次或全部场次的套题记录到 `.xlsx`
- 文件包含两个 Sheet：
  - **Sheet1: 套题列表**
    | 列名 | 说明 |
    |-----|-----|
    | set_code | 套题编号（SET-001） |
    | session_name | 场次名称 |
    | question_ids | 题目编号（逗号分隔，如 Q1,Q2,Q3） |
    | is_used | 是否已使用（是/否） |
    | used_at | 使用时间 |
    | created_at | 创建时间 |
  - **Sheet2: 套题题目详情**（每道题一行，便于查阅）
    | 列名 | 说明 |
    |-----|-----|
    | set_code | 所属套题编号 |
    | slot_index | 槽位序号（1/2/3） |
    | question_id | 题目编号 |
    | question_type | 题型 |
    | content | 题干（纯文本） |
    | answer | 答案 |
- 文件名：`面试套题_{场次名}_{日期}.xlsx`

**导入（Excel → sets）**：
- 上传套题 Excel（格式与导出一致）
- 系统自动创建对应的 `interview_sessions` 和 `interview_sets` 记录
- 若 `question_id` 不存在于本地，自动从 Sheet2 详情中补全导入题目
- 支持跨机器还原完整套题状态（含已使用标记）
- 返回统计：导入场次 X 个，套题 Y 套，新建题目 Z 道

### C. API 补充
在 4.5 导出基础上增加：
| Method | URL | 说明 |
|--------|-----|------|
| GET | `/api/interview/pool/export-xlsx` | 导出面试池 Excel |
| POST | `/api/interview/pool/import-xlsx` | 导入面试池 Excel（含跨机器建题） |
| GET | `/api/interview/sets/export-xlsx` | 导出套题记录 Excel（query: session_id） |
| POST | `/api/interview/sets/import-xlsx` | 导入套题记录 Excel（还原套题） |

---

## 四、后端 API 设计

新建 Blueprint：`app/interview_routes.py`，前缀 `/api/interview`。

### 4.1 题库池管理
| Method | URL | 说明 |
|--------|-----|------|
| GET | `/api/interview/pool` | 获取面试池列表（含题目详情，分页） |
| GET | `/api/interview/pool/stats` | 按题型统计池中可用数量 |
| POST | `/api/interview/pool/add` | 将筛选结果批量加入池（body: 筛选条件 JSON） |
| POST | `/api/interview/pool/remove` | 从池中移除题目（body: `{question_ids: [...]}`) |
| DELETE | `/api/interview/pool` | 清空面试池（全部删除） |

### 4.2 套题配置管理
| Method | URL | 说明 |
|--------|-----|------|
| GET | `/api/interview/config` | 获取当前默认配置 |
| PUT | `/api/interview/config` | 保存套题配置（body: `{slots: [...]}`) |

### 4.3 单次抽选
| Method | URL | 说明 |
|--------|-----|------|
| POST | `/api/interview/draw` | 抽取一套题（不持久化，标记 drawn=true） |
| POST | `/api/interview/draw/check` | 校验当前池是否支持抽取（警告检查） |

### 4.4 套题生成与管理
| Method | URL | 说明 |
|--------|-----|------|
| POST | `/api/interview/sessions` | 创建面试场次并批量生成套题 |
| GET | `/api/interview/sessions` | 获取所有场次列表 |
| GET | `/api/interview/sessions/<id>/sets` | 获取某场次下所有套题 |
| POST | `/api/interview/sets/<id>/use` | 标记套题为已使用 |
| POST | `/api/interview/sets/<id>/release` | 释放套题（改为未使用） |
| POST | `/api/interview/sets/batch-use` | 批量标记已使用 |

### 4.5 导出
| Method | URL | 说明 |
|--------|-----|------|
| POST | `/api/interview/export` | 导出指定套题为 Word（body: `{set_ids, include_answers}`) |

---

## 五、前端设计（index.html）

### 5.1 Tab 入口

在侧边栏（sidebar）现有 7 个 Tab 之后，追加：
```html
<button class="tab-button" onclick="switchTab('interview-draw')">
    <i class="fas fa-user-tie"></i>
    <span>面试抽题</span>
</button>
```

### 5.2 Tab 内布局

Tab 内采用**左侧竖向子导航 + 右侧内容区**结构，5 个子面板：

```
[题库筛选] [题型设置] [随机抽题] [套题管理] [导出]
```

（或水平 Tab 条，根据屏幕空间决定）

### 5.3 关键 JS 函数

| 函数名 | 说明 |
|--------|-----|
| `switchInterviewPanel(panel)` | 切换子面板 |
| `loadInterviewPoolStats()` | 加载面试池统计 |
| `previewInterviewFilter()` | 预览筛选结果 |
| `addToInterviewPool()` | 加入面试池 |
| `clearInterviewPool()` | 清空面试池 |
| `loadInterviewConfig()` | 加载套题配置 |
| `saveInterviewConfig()` | 保存套题配置 |
| `addConfigSlot()` | 添加槽位行 |
| `removeConfigSlot(index)` | 删除槽位行 |
| `drawInterviewSet()` | 随机抽题 |
| `checkInterviewPool()` | 警告校验 |
| `generateInterviewSets()` | 批量生成套题 |
| `markSetUsed(setId)` | 标记已使用 |
| `releaseSet(setId)` | 释放套题 |
| `exportInterviewSets()` | 导出 Word |
| `showInterviewWarning(msg, actions)` | 显示警告弹窗 |

---

## 六、实施顺序

### Phase 1：数据库 + 基础 API（1-2天）
1. `app/interview_routes.py` — 新 Blueprint，注册到 `factory.py`
2. `app/factory.py` — `_migrate_db()` 追加 4 张表的建表语句
3. 实现：题库池 CRUD API + 统计 API
4. 实现：套题配置 GET/PUT API

### Phase 2：套题生成逻辑（1天）
5. 实现：`POST /api/interview/sessions`（创建场次 + 批量分配套题）
   - 核心：随机分配算法，确保同一题不出现在两套题中
   - 校验：题目数量是否充足，缺失题型警告
6. 实现：套题状态管理（标记使用/释放）

### Phase 3：随机抽选 + 导出（1-2天）
7. 实现：`POST /api/interview/draw`（单次随机抽题）
8. 实现：`POST /api/interview/export`（复用 utils.py Word 导出能力）
9. 实现：Excel 导出（面试池 + 套题记录，用 openpyxl）
10. 实现：Excel 导入（解析 Excel，跨机器自动建题后加入池/还原套题）

### Phase 4：前端 Tab（2-3天）
9. 在 `index.html` 追加 Tab 按钮和内容区骨架
10. 题库筛选面板 + 预览功能
11. 题型配置面板（动态行编辑）
12. 随机抽题面板（含答案折叠展示）
13. 套题管理列表（分页 + 状态标记）
14. 导出选项 UI

### Phase 5：测试 + 边界处理（1天）
15. 新增 `tests/test_interview.py`：核心 API 单元测试
16. 警告系统 E2E 验证

---

## 七、关键设计决策与约束

1. **面试池与主库分离**：`interview_pool` 是独立表，不修改 `questions.is_used` 字段——主库的 `is_used` 只被普通试卷生成使用，面试池用自己的 `drawn` 标记，两套逻辑互不干扰。

2. **套题生成算法**：采用"全局无重复"策略——生成 N 套题时，为所有套题槽位同时分配，确保同一道题只出现在一套题里。采用 Fisher-Yates 洗牌后分批分配，不是每套独立随机（避免后几套无题可选）。

3. **单次抽选 vs 批量生成**：
   - **单次抽选**（模块 3）= 临时展示，标记 `drawn=true`，不产生 `interview_sets` 记录
   - **批量生成**（模块 5）= 持久化，写入 `interview_sets`，供导出和状态管理使用
   - 两套逻辑共用同一个"可用题"判断（池中 `drawn=false`）

4. **Word 导出复用**：复用 `utils.py` 中现有的 HTML→Word 段落转换函数，减少重复实现。

5. **不新增数据库文件**：新表全部追加到现有 `exam_system.db`，通过 `_migrate_db()` 幂等建表，不引入新的 DB 文件。

---

## 八、文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app/interview_routes.py` | **新建** | 面试抽题 Blueprint（~800-1000行，含 Excel 导入导出） |
| `app/factory.py` | 修改 | `_migrate_db()` 追加 4 张表；注册 `interview_bp` |
| `app/templates/index.html` | 修改 | 追加 Tab 按钮 + 面试抽题内容区（+约 500-700 行 HTML/JS） |
| `app/utils.py` | 可能小改 | 若 Word 导出需适配新格式，追加辅助函数 |
| `tests/test_interview.py` | **新建** | 面试抽题功能测试 |

---

## 九、待确认事项

在实施前，请确认以下问题：

1. **单次抽选 vs 仅批量生成**：是否需要"随机抽选展示"（模块 3）这个即时展示功能？还是所有抽题都通过"批量生成套题"来进行？
2. **面试池持久化范围**：面试池是全局唯一的，还是可以有多个命名池（如"春招池"、"秋招池"）？
3. **导出格式**：Word 中题目是否需要保留富文本格式（表格、图片）？还是纯文本即可？
4. **已使用题目的再利用**：用「释放」操作后，该套题的题目在 `interview_pool` 中的 `drawn` 状态是否也同步重置？
5. **测试覆盖要求**：是否需要新增测试，还是仅手动测试即可？
