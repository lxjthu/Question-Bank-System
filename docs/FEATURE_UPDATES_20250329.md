# 试卷生成系统功能更新文档

> 更新日期：2026-03-29  
> 更新内容：文本粘贴导入、面试模板功能、Excel题型自动匹配

---

## 一、文本粘贴导入功能

### 1.1 功能概述

支持用户直接从其他 AI（ChatGPT、Claude、DeepSeek 等）生成的题库文本粘贴到系统中导入，无需先保存为文件。

### 1.2 后端变更

**文件**: `app/routes.py`

#### 新增 API 路由

```python
@bp.route('/api/questions/import-text', methods=['POST'])
@login_required
@guest_readonly
def import_questions_from_text()
```

**功能说明**:
- 接收 JSON 格式的文本内容和科目信息
- 复用 `parse_question_template()` 函数解析题目
- 支持自动去重（精确匹配 + 相似度匹配）
- 自动检测题目语言

**请求参数**:
```json
{
  "text": "[单选][A]\n题目内容...",
  "subject": "测试科目"
}
```

**响应格式**:
```json
{
  "message": "成功导入 X 题，跳过重复 Y 题",
  "imported": 10,
  "count": 10,
  "skipped": 2,
  "failed": 0
}
```

### 1.3 前端变更

**文件**: `app/templates/index.html`

#### 界面元素

在「题库导入与模板下载」标签页新增「粘贴导入」卡片：

```html
<div class="card">
    <h3><i class="fas fa-paste"></i> 粘贴导入（从AI生成的题库）</h3>
    <!-- 科目输入框 -->
    <!-- 文本粘贴框（12行，等宽字体） -->
    <!-- 导入按钮、清空按钮、状态提示 -->
</div>
```

#### JavaScript 函数

| 函数名 | 功能 |
|--------|------|
| `paste-import-btn` 事件监听 | 处理导入请求 |
| `clearPasteImport()` | 清空粘贴框 |
| `showPasteFormatHelp()` | 显示格式帮助 |

### 1.4 支持的题目格式

```
[单选][A]
这道题的题目内容？
[A] 选项A
[B] 选项B
[C] 选项C
[D] 选项D
<参考答案>正确答案是A
<解析>这里是解析

[简答>材料分析]
材料内容...
问题内容？
<参考答案>参考答案...
```

---

## 二、面试抽题 - 多配置管理 & 模板下载

### 2.1 功能概述

面试抽题模块的「题型设置」面板现在支持每个题库池保存**多条**套题配置，并为每个配置提供「导出模板」功能。

### 2.2 数据库设计

**表**: `interview_configs`（已有，无需 DDL 变更）

```sql
CREATE TABLE interview_configs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id     INTEGER NOT NULL,
    config_name VARCHAR(128) DEFAULT 'default',
    slots_json  TEXT NOT NULL DEFAULT '[]',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.3 后端 API 变更

**文件**: `app/interview_routes.py`

#### 2.3.1 获取所有配置（已修改）

```python
GET /api/interview/pools/<int:pool_id>/config
```

**变更内容**:
- 从返回单条改为返回列表
- 每条配置附加 `subjects` 字段（科目统计）
- 每条配置附加 `slot_summary` 字段（槽位摘要，如"简答×2, 论述×1"）

**响应示例**:
```json
{
  "configs": [
    {
      "id": 1,
      "pool_id": 3,
      "config_name": "期末面试A",
      "slots_json": "[...]",
      "created_at": "2026-03-28 10:00:00",
      "updated_at": "2026-03-29 14:30:00",
      "subjects": ["农业经济学", "微观经济学"],
      "slot_summary": "简答×2, 论述×1, 材料分析×1"
    }
  ]
}
```

#### 2.3.2 新增/更新配置（已修改）

```python
PUT /api/interview/pools/<int:pool_id>/config
```

**变更内容**:
- 新增 `config_name` 字段支持
- 按 `config_name` 区分配置
- 存在则更新，不存在则新增

**请求体**:
```json
{
  "config_name": "期末面试A",
  "slots": [
    {"question_type": "简答", "language": "任意", "difficulty": "任意", "remark": ""}
  ]
}
```

#### 2.3.3 删除配置（新增）

```python
DELETE /api/interview/pools/<int:pool_id>/config/<int:config_id>
```

#### 2.3.4 导出套题模板（新增）

```python
GET /api/interview/pools/<int:pool_id>/config/<int:config_id>/export-template
```

**参数**: `set_count`（可选，默认 5）

**生成 Excel 结构**:

- **Sheet1「套题列表」**: `set_code` + N 个槽位列（槽位1-简答、槽位2-论述...）
- **Sheet2「题目详情」**: 与 `export_sets_xlsx` 的 Sheet2 列头一致

#### 2.3.5 下载题库池模板（新增）

```python
GET /api/interview/templates/pool-xlsx
```

返回通用空模板（17 列 + 1 行示例数据）。

### 2.4 前端变更

**文件**: `app/templates/index.html`

#### 2.4.1 题型设置面板重构

新增元素：
- `#iv-saved-configs`: 已保存配置列表容器
- `#iv-config-name`: 配置名称输入框

界面结构：
```
┌─────────────────────────────────────────────┐
│ 套题题型配置         [题库池下拉 ▼]          │
│                                              │
│ ── 已保存配置 ─────────────────────────────  │
│ ┌─────────────────────────────────────────┐ │
│ │ 📋 期末面试A       2026-03-29 14:30     │ │
│ │ 槽位：简答×2, 论述×1                    │ │
│ │ 科目：农业经济学, 微观经济学             │ │
│ │ [使用此配置] [导出模板] [删除]          │ │
│ └─────────────────────────────────────────┘ │
│                                              │
│ ── 编辑区 ─────────────────────────────────  │
│ 配置名称：[________]                        │
│ [槽位1: 简答 ▼ | 任意 ▼ | 任意 ▼ | 备注 ×] │
│ [+ 添加槽位]  [💾 保存配置]                │
└─────────────────────────────────────────────┘
```

#### 2.4.2 JavaScript 函数

| 函数名 | 功能 |
|--------|------|
| `ivLoadConfigForPool()` | 加载配置列表（返回 configs 数组） |
| `ivRenderConfigCards(configs)` | 渲染配置卡片列表 |
| `ivUseConfig(configId)` | 加载指定配置到编辑区 |
| `ivDeleteConfig(poolId, configId)` | 删除配置 |
| `ivExportTemplate(poolId, configId)` | 导出套题模板 |
| `ivDownloadPoolTemplate()` | 下载题库池导入模板 |
| `ivGoToConfigForTemplate()` | 跳转到题型设置面板 |

#### 2.4.3 导入导出面板

新增按钮：
- 题库池区域：「下载导入模板」按钮 → `ivDownloadPoolTemplate()`
- 套题记录区域：「下载套题导入模板」按钮 → `ivGoToConfigForTemplate()`

---

## 三、Excel 导入 - 题型自动匹配和创建

### 3.1 功能概述

Excel 导入题库时，支持自动匹配内置题型，如果匹配失败则自动创建新题型，无需手动预先创建题型。

### 3.2 后端变更

**文件**: `app/routes.py`

#### 3.2.1 新增题型匹配规则

```python
_XLSX_TYPE_PATTERNS = {
    "单选": ["单选", "单选题", "单项选择", "单项选择题"],
    "多选": ["多选", "多选题", "多项选择", "多项选择题", "不定项选择"],
    "是非": ["判断", "判断题", "是非", "是非题", "对错题", "正确错误"],
    "简答": ["简答", "简答题", "问答题", "问答", "名词解释", "解释"],
    "简答>计算": ["计算", "计算题"],
    "简答>论述": ["论述", "论述题"],
    "简答>材料分析": ["材料分析", "材料分析题", "案例分析", "案例分析题", "分析题"],
}
```

#### 3.2.2 新增 `_match_question_type()` 函数

**功能**: 智能匹配题型

**匹配策略**（按优先级）：
1. **精确匹配**: 直接匹配已知题型
2. **反向映射**: `_XLSX_TYPE_REVERSE` 映射表
3. **模糊匹配**: 基于 `_XLSX_TYPE_PATTERNS` 的关键词匹配
4. **层级匹配**: 查找包含标准题型的层级题型
5. **包含匹配**: 双向子串匹配
6. **创建新类型**: 未匹配到时返回需要创建的标志

**返回值**: `(matched_type, is_builtin, needs_create)`

#### 3.2.3 新增 `_ensure_question_type()` 函数

**功能**: 确保题型存在，不存在则创建

**创建逻辑**:
- 检查是否已存在同名自定义题型（避免重复）
- 根据题型名称智能判断 `has_options`（包含"选"字的题型默认有选项）
- 新题型归属于当前用户

#### 3.2.4 修改 `_parse_xlsx_questions()` 函数

**变更**:
- 新增 `user` 参数
- 调用 `_match_question_type()` 进行题型匹配
- 如需创建新题型，调用 `_ensure_question_type()`
- 返回新增 `created_types` 列表

**新签名**:
```python
def _parse_xlsx_questions(file_path, user=None):
    # 返回: (questions_list, errors_list, created_types_list)
```

#### 3.2.5 修改导入路由

**普通题库导入** (`/api/questions/import`):
- 调用 `_parse_xlsx_questions(file_path, _import_user)`
- 返回信息包含 `created_types` 字段

**面试题库导入** (`/api/interview/pools/<id>/questions/import-xlsx`):
- 导入 `routes.py` 中的匹配函数
- 相同的新题型自动创建逻辑

**文件**: `app/interview_routes.py`

```python
from app.routes import _match_question_type, _ensure_question_type
```

### 3.3 导入结果示例

```json
{
  "message": "成功导入 61 题，跳过重复 31 题（含相似题），自动创建 1 个新题型：英语听说题",
  "imported": 61,
  "skipped": 31,
  "created_types": ["英语听说题"],
  "parse_errors": []
}
```

---

## 四、测试用例

### 4.1 文本粘贴导入

1. 切换到「题库导入与模板下载」标签页
2. 在「粘贴导入」区域输入科目并粘贴题库文本
3. 点击「导入题库」按钮
4. 验证题目成功导入到「题库管理」

### 4.2 面试多配置管理

1. 进入「面试抽题」→「题型设置」面板
2. 选择题库池，添加多个槽位，输入配置名称
3. 点击「保存配置」，验证配置卡片出现在上方
4. 测试「使用此配置」「导出模板」「删除」按钮

### 4.3 题型自动创建

1. 准备包含新题型（如「英语听说题」）的 Excel
2. 通过「题库导入」导入该文件
3. 验证：
   - 题目成功导入
   - 返回信息包含新创建的题型
   - 在「题库管理」中可看到新题型

---

## 五、部署说明

### 5.1 依赖检查

确保已安装 `openpyxl`：
```bash
pip install openpyxl
```

### 5.2 数据库迁移

无需数据库结构变更，新功能使用已有表结构：
- `interview_configs` 表已存在 `config_name` 字段
- `question_types` 表支持动态创建

### 5.3 重启服务

```bash
# 开发环境
python server.py

# 生产环境
systemctl restart exam-system-online
```

---

## 六、Git 提交信息

```
feat: 添加文本粘贴导入、面试多配置管理、题型自动创建功能

- 新增文本粘贴导入 API 和前端界面
- 面试模块支持多配置管理和模板导出
- Excel 导入支持题型自动匹配和创建
- 优化题型识别逻辑，支持常见变体
```
