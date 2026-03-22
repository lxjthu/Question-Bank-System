# AI批量标注 v2 规划

> 分支: ds-text-only
> 日期: 2026-03-22
> 涉及文件: `app/rag_routes.py`, `app/templates/index.html`

---

## 问题 1：KeyError 'name'（立即修复）

### 根因

`_classify_batch()` (rag_routes.py ~1803) 访问 `kp['name']` 和 `kp.get('content')`，但 SQL 查询返回的字段名是 `kp_name` 和 `kp_content`：

```python
# 错误（当前）
content_preview = (kp.get('content') or '')[:200]   # → None
lines.append(f"… 名称：{kp['name']}\n…")             # → KeyError: 'name'

# 正确（修复后）
content_preview = (kp.get('kp_content') or '')[:200]
lines.append(f"… 名称：{kp['kp_name']}\n…")
```

同时更新函数 docstring。

**影响范围**：仅 `_classify_batch()` 内部，两处替换。

---

## 问题 2：提示词可见/可编辑 + 重难点列表文件导入（新功能）

### 2.1 用户需求

1. 标注面板展示当前使用的 AI 提示词（系统提示 + 用户提示）
2. 用户可直接编辑提示词（本次会话生效）
3. 用户可上传"重难点列表"文件（`.txt` / `.md`），系统自动将文件内容写入提示词的占位区，用于辅助 AI 判断 `teaching_focus`（重点/难点/考点）
4. 可一键恢复默认提示词

### 2.2 整体流程

```
用户编辑提示词 / 上传重难点文件
       ↓
前端 _startBatchClassify() 读取当前文本框内容
       ↓
POST /api/rag/ds-batch-classify
  body: { kp_ids/doc_id, overwrite,
          system_prompt (可选),
          user_prompt   (可选),
          classify_focus (bool, 可选, 默认 false) }
       ↓
后端 _classify_batch(client, batch, system_prompt, user_prompt, classify_focus)
  - 若 classify_focus=true：输出 JSON 增加 teaching_focus 字段
  - 写回数据库时也更新 teaching_focus
```

### 2.3 后端修改（rag_routes.py）

#### A. 新增"含教学重难点"的提示词模板变量

```python
# 追加在 _CLASSIFY_PROMPT 末尾（或单独变量）
_CLASSIFY_PROMPT_FOCUS_SECTION = """
## 教学重难点参考列表
以下是教师标注的重点/难点/考点，可用于辅助判断 teaching_focus 字段：
{focus_list}

teaching_focus 选项（可多选，用逗号分隔，也可为空）：
- 重点：本课程重点掌握的核心概念或方法
- 难点：学生普遍感到理解困难的内容
- 考点：历年考试频繁出现的内容

"""

# 修改输出要求部分（增加 teaching_focus 字段）
_CLASSIFY_PROMPT_OUTPUT_WITH_FOCUS = """## 输出要求
直接输出纯 JSON 数组，不要加代码块标记，格式如下：
[
  {{"seq": 1, "knowledge_type": "概念性", "cognitive_dimension": "理解", "teaching_focus": "重点,考点"}},
  ...
]
"""
```

#### B. `_classify_batch()` 签名变更

```python
def _classify_batch(
    client,
    kps_batch: list,
    system_prompt: str = None,   # None → 使用 _CLASSIFY_SYSTEM
    user_prompt: str = None,     # None → 使用 _CLASSIFY_PROMPT（含 {kp_list} 占位符）
    classify_focus: bool = False,
) -> list:
```

- `system_prompt` / `user_prompt` 为 `None` 时使用默认常量
- `user_prompt` 必须含 `{kp_list}` 占位符，若不含则 fallback 到末尾追加
- `classify_focus=True` 时，如果 `user_prompt` 是默认提示词则自动追加 focus 输出格式说明

#### C. `ds_batch_classify()` 端点新增参数

```python
data = request.json or {}
system_prompt   = data.get('system_prompt') or None
user_prompt     = data.get('user_prompt') or None
classify_focus  = bool(data.get('classify_focus', False))
```

将以上三个参数传给 `_classify_batch()`。

#### D. 写回数据库时增加 `teaching_focus`

```python
# 当 classify_focus=True 时
tf = res.get('teaching_focus', '')
conn.execute(
    "UPDATE ds_kps SET knowledge_type=?, cognitive_dimension=?, teaching_focus=? WHERE id=?",
    (kt, cd, tf, kp['id']),
)
```

`overwrite` 逻辑：当 `classify_focus=True` 且 `overwrite=False` 时，跳过条件改为"已有 kt+cd+tf 则跳过"。

### 2.4 前端修改（index.html）

#### A. 面板结构（在"AI批量标注"区域内，置于"开始标注"按钮之前）

```
[▼ 查看/编辑提示词]   ← 折叠按钮，默认收起

  折叠区展开后：
  ┌ 系统提示词 ─────────────────────────── [恢复默认] ┐
  │ <textarea id="ds-classify-sys-prompt">           │
  └──────────────────────────────────────────────────┘

  ┌ 用户提示词（含 {kp_list} 占位符）────────────────── ┐
  │ <textarea id="ds-classify-user-prompt">           │
  └──────────────────────────────────────────────────┘

  [📄 导入重难点列表]  <input type="file" accept=".txt,.md" hidden>
  提示：上传后自动写入提示词中的重难点区域，并开启 teaching_focus 标注

  [☑] 同时标注教学重难点（teaching_focus）   ← 仅当上传了文件或勾选时生效
```

#### B. 文件导入逻辑（JS）

```javascript
// 读取文件内容 → 插入 user_prompt 中 {focus_list} 占位符
// 若提示词中无该占位符 → 在 {kp_list} 段之前插入整个重难点 section
// 同时自动勾选"同时标注 teaching_focus"复选框
// 同时修改输出要求部分追加 teaching_focus 字段
```

具体实现：
1. 读取文件后在提示词末尾（"## 待分类知识点"之前）插入 `## 教学重难点参考列表\n{file_content}`
2. 更新"## 输出要求"部分，JSON 样例加上 `"teaching_focus": "重点"` 字段
3. 自动勾选 `#ds-classify-focus-cb`

#### C. `_startBatchClassify()` 修改

```javascript
const body = { overwrite };
// 读取编辑后的提示词（为空则不传，后端使用默认）
const sysP  = document.getElementById('ds-classify-sys-prompt')?.value.trim();
const userP = document.getElementById('ds-classify-user-prompt')?.value.trim();
const doFocus = document.getElementById('ds-classify-focus-cb')?.checked;

if (sysP)  body.system_prompt  = sysP;
if (userP) body.user_prompt    = userP;
if (doFocus) body.classify_focus = true;
```

---

## 实施顺序

1. **立即修复 Bug 1**（2处字段名替换，不影响功能结构）
2. **后端：新增提示词参数 + teaching_focus 写回**（修改 `_classify_batch` + `ds_batch_classify`）
3. **前端：折叠面板 + 提示词 textarea + 文件导入 + classify_focus 勾选**
4. 更新 CHANGELOG / 版本

---

## 涉及文件

| 文件 | 修改内容 |
|------|---------|
| `app/rag_routes.py` | Bug 修复(2行) + `_classify_batch` 签名 + `ds_batch_classify` 参数 + teaching_focus 写回 |
| `app/templates/index.html` | AI标注面板新增折叠提示词编辑区 + 文件上传 + classify_focus 勾选框 |
