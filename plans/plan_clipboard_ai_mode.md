# 剪贴板 AI 模式（无 API Key 方案）

> 规划日期：2026-03-25
> 目标：彻底去除服务器端 DeepSeek API 调用，改为"用户自带 AI 网页"的剪贴板中转模式。
> 优先级：替换 rag_routes.py 中知识点提取和出题两条主流程；其余 UI 不改。

---

## 一、核心思路

```
上传文件 → 服务器解析文本 → 生成提示词 → 用户复制到 AI 网页 → 粘贴结果回窗口 → 服务器解析入库
```

完全不需要 API Key，不需要服务器出网，用户用哪家 AI 都行。

---

## 二、两条主流程详细设计

### 2.1 知识图谱提取流程

**步骤 1 — 上传文件**
- 接口不变：`POST /api/rag/ds-upload`
- 服务器只做文本解析，把课件切分成章节（已有代码）
- 不调用 DeepSeek，直接返回章节列表

**步骤 2 — 生成提示词**
- 新接口：`GET /api/rag/ds-docs/<doc_id>/prompt`
- 服务器把所有章节文本拼成一个"知识点提取 Prompt"返回
- Prompt 格式：固定系统说明 + 章节内容 + 输出格式要求（JSON）
- 前端展示提示词文本框（大字，可全选），旁边放三个链接按钮：
  - [打开通义千问](https://tongyi.aliyun.com)
  - [打开豆包](https://www.doubao.com)
  - [打开 DeepSeek](https://chat.deepseek.com)

**步骤 3 — 粘贴 AI 结果**
- 前端：一个大文本框"粘贴 AI 的回答"
- 一键"解析并导入"按钮

**步骤 4 — 服务器解析 JSON 入库**
- 新接口：`POST /api/rag/ds-docs/<doc_id>/import-kps`
- 请求体：`{ "raw": "<用户粘贴的内容>" }`
- 服务器端用正则从 raw 里提取 JSON 块（支持 ```json ... ``` 和裸 JSON 两种格式）
- 解析后批量写入 ds_kps 表（复用现有字段）
- 返回导入数量和失败列表

---

### 2.2 出题流程

**步骤 1 — 选择知识点**
- 前端已有知识点列表，用户勾选
- 点击"生成提示词"按钮，调用：

**步骤 2 — 生成出题提示词**
- 新接口：`POST /api/rag/ds-generate-prompt`
- 请求体：`{ "kp_ids": [...], "question_list": "5道单选3道判断", "custom_prompt": "..." }`
- 服务器把选中的知识点内容拼成 Prompt，返回给前端展示
- 同样配三个 AI 链接按钮

**步骤 3 — 粘贴 AI 结果**
- 前端：粘贴文本框

**步骤 4 — 解析并导入题库**
- 新接口：`POST /api/rag/ds-import-questions`
- 请求体：`{ "raw": "<AI 回答>", "doc_id": "..." }`
- 复用现有 `parse_questions_from_text()` 逻辑（routes.py 里已有 txt 导入解析器）
- 去重检查（复用 _ngram_set / _is_similar）
- 返回导入数量、重复跳过数量、解析失败列表

---

## 三、Prompt 模板设计

### 知识点提取 Prompt（存在 rag_routes.py 常量里）

```
你是一位课程内容分析专家。请从以下课件文本中提取结构化知识点，输出 JSON 格式。

【课件内容】
{chapter_texts}

【输出格式】
请严格按以下 JSON 数组格式输出，不要添加其他解释：
```json
[
  {
    "chapter_name": "章节名称",
    "kp_name": "知识点名称（简短）",
    "kp_content": "知识点详细描述（1-3句话）",
    "teaching_focus": "重点",
    "knowledge_type": "概念性",
    "cognitive_dimension": "理解",
    "relations": [
      {"type": "depends_on", "target": "前置知识点名称"}
    ]
  }
]
```
teaching_focus 可选值：重点、难点、考点、一般
knowledge_type 可选值：概念性、程序性、原理性、事实性
cognitive_dimension 可选值：记忆、理解、应用、分析、评价、创造
relations.type 可选值：is_a、depends_on、contrasts_with、leads_to
```

### 出题 Prompt（存在 rag_routes.py 常量里）

```
你是一位专业的教学出题专家。请根据以下知识点出题，按要求的题型和数量生成题目。

【知识点】
{kp_context}

【出题要求】
{question_list}

【输出格式】
每道题用以下格式，题与题之间用空行分隔：
[单选]
题干：...
A. ...
B. ...
C. ...
D. ...
答案：A
解析：...（可选）

[判断]
题干：...
答案：正确/错误
解析：...（可选）

[简答]
题干：...
参考答案：...
```

---

## 四、前端 UI 变更（index.html）

### 知识点提取区（AI出题 Tab → 知识图谱子Tab）

**现有流程（待替换）：**
- 上传文件 → 点"开始提取"（调 DeepSeek API）→ 轮询进度

**新流程：**
```
[上传文件] → 解析章节（快速，无 AI）→ 显示"提示词已就绪"
↓
[ 生成提示词 ] 按钮 → 弹出 Modal：
  ┌─────────────────────────────────────────┐
  │  📋 知识点提取提示词                      │
  │  ┌─────────────────────────────────────┐ │
  │  │  （提示词全文，可滚动）               │ │
  │  └─────────────────────────────────────┘ │
  │  [📋 一键复制]                            │
  │                                           │
  │  打开 AI：[通义千问] [豆包] [DeepSeek]   │
  │  （点击新标签页打开，提示"把提示词粘贴过去"）│
  │                                           │
  │  将 AI 的回答粘贴到这里：                  │
  │  ┌─────────────────────────────────────┐ │
  │  │                                     │ │
  │  └─────────────────────────────────────┘ │
  │  [✅ 解析并导入知识点]                    │
  └─────────────────────────────────────────┘
```

### 出题区（选中知识点后）

**现有流程（待替换）：**
- 勾选知识点 → 填写出题要求 → 点"开始出题"（调 DeepSeek）→ 等待结果

**新流程：**
```
勾选知识点 + 填写出题要求 → [生成提示词] → 弹出 Modal（同上结构）→ 粘贴 → [导入题库]
```

---

## 五、涉及文件和改动量

| 文件 | 改动类型 | 估计行数 |
|------|---------|---------|
| `app/rag_routes.py` | 新增 3 个接口，删除 ds_generate/ds_extract 的 DeepSeek 调用逻辑 | +120 / -300 |
| `app/templates/index.html` | 替换 AI 出题区的 UI 和 JS | +150 / -80 |
| `app/routes.py` | 几乎不变（复用 import 解析逻辑） | +5 |

---

## 六、新增接口汇总

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/rag/ds-docs/<doc_id>/prompt` | 生成知识点提取 Prompt |
| POST | `/api/rag/ds-docs/<doc_id>/import-kps` | 解析粘贴内容，批量写入 ds_kps |
| POST | `/api/rag/ds-generate-prompt` | 生成出题 Prompt |
| POST | `/api/rag/ds-import-questions` | 解析 AI 出题结果，导入题库 |

保留的接口（仍需要）：
- `POST /api/rag/ds-upload` — 上传+解析章节（不调 AI）
- `GET /api/rag/ds-docs` — 文档列表
- `DELETE /api/rag/ds-docs/<doc_id>` — 删除文档
- `GET /api/rag/ds-docs/<doc_id>/kps` — 知识点列表（出题前勾选用）

**可以删除的接口（不再需要）：**
- `POST /api/rag/ds-extract/<doc_id>` — AI 提取知识点（改为手动粘贴）
- `GET /api/rag/ds-tasks/<task_id>` — 提取任务轮询（任务消失了）
- `POST /api/rag/ds-tasks/<task_id>/pause` — 暂停提取
- `POST /api/rag/ds-generate` — AI 直接出题（改为生成 Prompt）
- `GET /api/rag/ds-generate-tasks/<task_id>` — 出题任务轮询

---

## 七、JSON 解析容错策略（import-kps 接口）

用户粘贴的内容可能包含：
1. 纯 JSON 数组
2. ` ```json ... ``` ` 包裹的 JSON
3. JSON 前后有多余文字

解析顺序：
```python
def _extract_json_from_raw(raw: str) -> list:
    # 1. 尝试提取 ```json...``` 块
    m = re.search(r'```(?:json)?\s*([\s\S]+?)```', raw)
    if m:
        return json.loads(m.group(1))
    # 2. 找第一个 [ 到最后一个 ] 之间的内容
    start = raw.find('[')
    end = raw.rfind(']')
    if start != -1 and end != -1:
        return json.loads(raw[start:end+1])
    # 3. 尝试直接解析整体
    return json.loads(raw)
```

如果解析失败，返回 `{"error": "无法解析 JSON，请检查 AI 回答格式", "raw_preview": raw[:200]}`。

---

## 八、实施顺序建议

1. **后端先行**：实现 4 个新接口（~2-3小时）
   - `ds-docs/<doc_id>/prompt` — 最简单，只拼字符串
   - `ds-docs/<doc_id>/import-kps` — JSON 解析 + 写 DB
   - `ds-generate-prompt` — 拼 KP context 字符串
   - `ds-import-questions` — 复用现有 txt 导入逻辑

2. **前端 Modal**：实现提示词弹窗 UI（~2小时）

3. **清理旧接口**：删除不再需要的 AI 调用代码（~1小时）

4. **测试**：手动跑一遍流程 + 写2-3个新接口测试（~1小时）

---

## 九、与 P4（登录 UI）的关系

此方案与 P4 独立，可并行开发。
P4 完成后，"提示词 Modal"里可以加一行提示：
`"提示：请在 AI 里开一个新对话，不要泄露账号密码等敏感信息。"`

---

## 十、与现有 simple 版的差异

| 维度 | simple 版（当前） | online 版（新方案） |
|------|----------------|-----------------|
| AI 调用 | 服务器直调 DeepSeek API | 用户手动复制粘贴 |
| API Key | 用户在设置里填 | 不需要 |
| 知识点提取速度 | 自动，5-10分钟 | 手动，1-2分钟（AI 网页很快） |
| 出题速度 | 自动，30秒-2分钟 | 手动，约1分钟 |
| 服务器成本 | 需要代理/翻墙或国内 Key | 零 AI 成本 |
| 用户体验 | 全自动 | 多2次复制粘贴，但更灵活 |
