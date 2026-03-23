# 功能规划文档 2：题库增加导入日期时间字段

**版本**：v1.0
**日期**：2026-03-23
**涉及功能**：题库管理 Tab → 新增 `imported_at` 字段 → 导入时记录 → 搜索时按时间筛选 → 批量删除/导出

---

## 1. 需求背景

当前题库（`exam_system.db` 中的 `questions` 表）缺少"导入时间"字段。用户无法区分不同批次导入的题目，导致以下问题：
- 误导入了一批错误题目，无法批量识别和删除
- 想导出某次课程作业对应的那批题目，无法按时间筛选
- 多次导入历史混杂，管理困难

**目标**：
1. 新增 `imported_at` 字段（DateTime），记录每道题的导入时间
2. 题库搜索栏增加"导入时间范围"筛选器（从/到 日期选择器）
3. 批量操作（删除/导出）支持按时间筛选的结果

---

## 2. 数据库层变更

### 2.1 新增字段

**表**：`questions`（SQLAlchemy 管理，文件 `app/db_models.py`）

**新字段**：
```python
imported_at = db.Column(db.DateTime, nullable=True, default=None)
```

说明：
- `nullable=True`：兼容已有历史数据（老数据此字段为 NULL）
- `default=None`：不设置自动默认值，由应用层在导入时手动填入 `datetime.utcnow()`
- 区别于 `created_at`：`created_at` 是通用创建时间（手动录入也会有），`imported_at` 仅在批量导入时设置，手动新增题目此字段为 NULL，便于区分

### 2.2 数据库迁移

**位置**：`app/factory.py` 中的 `_migrate_db()` 函数

在现有 `ALTER TABLE` 语句列表中追加：
```python
migrations = [
    # ... 现有迁移 ...
    "ALTER TABLE questions ADD COLUMN imported_at DATETIME",
]
```

`_migrate_db()` 使用 `try/except OperationalError` 忽略已存在字段的错误，因此此操作是幂等的，不影响已有数据库。

### 2.3 历史数据处理

老数据的 `imported_at` 为 NULL。在 UI 展示时：
- 时间筛选器忽略 `imported_at=NULL` 的记录（或归类为"未知时间"）
- 列表中显示"—"

---

## 3. 后端变更

### 3.1 导入题目时设置 imported_at

**位置**：`app/routes.py` → `POST /api/questions/import` 端点

在批量创建 `QuestionModel` 对象时，统一为本次导入的所有题目设置同一个时间戳：

```python
from datetime import datetime

@bp.route('/api/questions/import', methods=['POST'])
def import_questions():
    # ... 现有解析逻辑 ...

    import_time = datetime.utcnow()  # 本次导入统一时间戳

    created_questions = []
    for q_data in parsed_questions:
        question = QuestionModel(
            # ... 现有字段 ...
            imported_at=import_time,  # 新增
        )
        created_questions.append(question)

    db.session.bulk_save_objects(created_questions)
    db.session.commit()
    # ...
```

**重要**：同一次导入操作（一个文件）的所有题目共用同一个 `import_time`，方便后续按批次筛选。

### 3.2 搜索接口增加时间范围筛选

**位置**：`app/routes.py` → `GET /api/questions`

新增两个可选查询参数：
- `imported_after`：筛选 `imported_at >= 此日期`，格式 `YYYY-MM-DD`
- `imported_before`：筛选 `imported_at <= 此日期`，格式 `YYYY-MM-DD`（包含当天 23:59:59）

后端处理逻辑：
```python
from datetime import datetime, timedelta

# 现有筛选逻辑之后追加：
imported_after = request.args.get('imported_after', '').strip()
imported_before = request.args.get('imported_before', '').strip()

if imported_after:
    try:
        dt = datetime.strptime(imported_after, '%Y-%m-%d')
        query = query.filter(QuestionModel.imported_at >= dt)
    except ValueError:
        pass

if imported_before:
    try:
        dt = datetime.strptime(imported_before, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(QuestionModel.imported_at < dt)
    except ValueError:
        pass

# 也支持只筛选有导入时间记录的题目（排除手动新增题）
imported_only = request.args.get('imported_only', '')
if imported_only == '1':
    query = query.filter(QuestionModel.imported_at.isnot(None))
```

### 3.3 题目列表 API 返回 imported_at

在 `GET /api/questions` 的序列化输出中增加 `imported_at` 字段：

```python
def serialize_question(q):
    return {
        # ... 现有字段 ...
        "imported_at": q.imported_at.strftime('%Y-%m-%d %H:%M') if q.imported_at else None,
    }
```

### 3.4 导出 xlsx 支持时间筛选

`POST /api/questions/check-export` 和 `POST /api/questions/export-xlsx` 都接受 `question_ids` 列表，因此只要前端在时间筛选后得到题目 ID 列表，导出接口无需修改。

---

## 4. 前端变更（app/templates/index.html）

### 4.1 搜索栏新增时间范围筛选器

**位置**：题库管理 Tab（`id="question-bank"`）的搜索区域，现有 `search-subject`/`search-keyword` 等筛选控件之后追加。

**HTML 新增**：
```html
<!-- 在搜索区域末尾追加 -->
<div class="search-row" id="import-time-filter-row">
  <label>导入时间：</label>
  <input type="date" id="search-imported-after" title="导入时间起始日期">
  <span style="margin:0 4px;">至</span>
  <input type="date" id="search-imported-before" title="导入时间截止日期">
  <label style="margin-left:12px;">
    <input type="checkbox" id="search-imported-only"> 仅显示导入题目
  </label>
</div>
```

### 4.2 搜索函数增加参数

在 `loadQuestions()` 或 `searchQuestions()` 函数中，拼接新参数：

```javascript
const importedAfter = document.getElementById('search-imported-after').value;
const importedBefore = document.getElementById('search-imported-before').value;
const importedOnly = document.getElementById('search-imported-only').checked;

const params = new URLSearchParams({
    // ... 现有参数 ...
    ...(importedAfter && { imported_after: importedAfter }),
    ...(importedBefore && { imported_before: importedBefore }),
    ...(importedOnly && { imported_only: '1' }),
});
```

### 4.3 题目列表展示 imported_at

在题目列表渲染函数（`renderQuestionRow()` 或类似函数）中，在题目卡片/行中增加导入时间展示：

```html
<!-- 题目 meta 信息区域 -->
<span class="q-meta-item" title="导入时间">
  ${q.imported_at ? '📥 ' + q.imported_at : ''}
</span>
```

样式：字体小（12px），颜色灰色，仅在有值时显示。

### 4.4 快捷操作：选中当前时间段的全部题目

在搜索结果区域的批量操作 bar 中，增加一个快捷提示：
- 当前筛选条件包含时间范围时，"全选当前结果"按钮旁边显示：`共 N 道（导入于 YYYY-MM-DD ~ YYYY-MM-DD）`

---

## 5. 典型使用场景

### 场景 1：批量删除误导入的题目
1. 打开题库管理 Tab
2. 在"导入时间"筛选中填入 `2026-03-20` 至 `2026-03-20`
3. 全选搜索结果
4. 点击批量删除

### 场景 2：导出某次课程作业对应的题目
1. 在"导入时间"填入对应日期范围
2. 选中所有结果
3. 导出 xlsx

### 场景 3：区分手动录入 vs 批量导入
1. 勾选"仅显示导入题目"
2. 只看到通过文件导入的题目，手动新增的不显示

---

## 6. 实施步骤清单

1. **数据库**：在 `app/db_models.py` 的 `QuestionModel` 类中添加 `imported_at` 字段
2. **迁移**：在 `app/factory.py` 的 `_migrate_db()` 中添加 `ALTER TABLE questions ADD COLUMN imported_at DATETIME`
3. **后端导入**：在 `app/routes.py` 的 `import_questions()` 函数中，创建 QuestionModel 时设置 `imported_at=import_time`
4. **后端查询**：在 `app/routes.py` 的 `get_questions()` 函数中，添加 `imported_after`/`imported_before`/`imported_only` 参数处理
5. **后端序列化**：在题目序列化逻辑中添加 `imported_at` 字段输出
6. **前端 HTML**：在搜索区域添加时间选择器 HTML
7. **前端 JS**：在搜索函数中添加参数传递
8. **前端 JS**：在题目渲染函数中添加导入时间展示
9. **测试**：导入一批题目 → 验证 imported_at 正确记录 → 按时间筛选

---

## 7. 涉及文件

| 文件 | 修改内容 |
|---|---|
| `app/db_models.py` | 新增 `imported_at` 字段 |
| `app/factory.py` | 新增迁移语句 |
| `app/routes.py` | 导入时设置时间；查询时处理时间筛选参数；序列化时输出时间 |
| `app/templates/index.html` | 搜索栏 HTML + 搜索 JS + 渲染 JS |

**预计工作量**：后端约 30 行，前端约 50 行。
