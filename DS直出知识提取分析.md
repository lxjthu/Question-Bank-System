# DeepSeek 直出模式 — 文档知识提取技术分析

> 文档路径：`app/rag_routes.py`
> 更新日期：2026-02-26

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [第一阶段：文档 → 章节分片](#2-第一阶段文档--章节分片)
3. [第二阶段：章节 → 知识图谱（DeepSeek 提取）](#3-第二阶段章节--知识图谱deepseek-提取)
4. [第三阶段：知识图谱 → 出题（DeepSeek 生成）](#4-第三阶段知识图谱--出题deepseek-生成)
5. [数据库结构](#5-数据库结构)
6. [错误处理与容错机制](#6-错误处理与容错机制)
7. [参数速查表](#7-参数速查表)

---

## 1. 整体架构概览

DS 直出模式（DeepSeek Straight-through Mode）是一套**不依赖向量库**的两阶段知识图谱出题系统，完整流程如下：

```
上传文档
    │
    ▼
【分片层】文档 → 章节列表
  · .md / .txt  →  正则按标题切分
  · .docx       →  Word Heading 样式 → Markdown → 正则切分
  · .pdf / .pptx →  PaddleOCR 异步 → result.md → 正则切分
    │
    ▼（存入 ds_chapters）
【提取层】章节 → 知识点（逐章调用 DeepSeek）
  · 超 8000 字截断
  · system: 教材分析专家
  · temperature=0.3，强制 JSON 输出
  · 提取 3~8 个知识点，含关系图谱
    │
    ▼（存入 ds_kps）
【生成层】知识点 → 题目（一次 DeepSeek 调用）
  · 按章节组装上下文，累计 7000 字封顶
  · temperature=0.7，max_tokens=8000
  · 支持中文 / 双语 / 英文三种提示词模板
    │
    ▼
题目文本（导入题库）
```

**独立数据库：** `ds_knowledge.db`（与 RAG 的 `kg.db` 完全隔离）

---

## 2. 第一阶段：文档 → 章节分片

### 2.1 各格式解析路径

**代码位置：** `app/rag_routes.py:814-838`（`_parse_file_to_chapters`）

| 文件格式 | 解析方式 | 是否异步 |
|---------|---------|---------|
| `.md` `.txt` | 直接读取文本 → `_parse_md_to_chapters()` | 同步 |
| `.docx` | python-docx 提取段落 → 按 Word Heading 样式转 `#`/`##` → `_parse_md_to_chapters()` | 同步 |
| `.pdf` | PaddleOCR API → `result.md` → `_parse_md_to_chapters()` | **异步**（后台线程） |
| `.pptx` `.ppt` | PaddleOCR API → `result.md` → `_parse_md_to_chapters()` | **异步**（后台线程） |

**`.docx` 样式映射规则：**

```python
# app/rag_routes.py:829-834
if 'Heading 1' in style or 'heading 1' in style.lower():
    md_lines.append(f'# {t}')          # → 一级标题
elif 'Heading 2' in style or 'heading 2' in style.lower():
    md_lines.append(f'## {t}')         # → 二级标题
else:
    md_lines.append(t)                  # → 正文行
```

---

### 2.2 章节分割正则

**代码位置：** `app/rag_routes.py:784-811`（`_parse_md_to_chapters`）

**核心正则：**
```python
re.match(r'^#{1,2}\s+(.+)', line)
```

- 匹配以 `#` 或 `##` 开头（一级或二级标题）
- 后跟至少一个空格，再接任意字符作为标题名
- **不匹配** `###` 及更深层标题（三级及以下视为正文）

**完整函数逻辑：**

```python
def _parse_md_to_chapters(text: str) -> list:
    chapters: list = []
    current_title = '（前言/概述）'   # 首个标题前的内容归入此章
    current_num = 0
    current_lines: list = []

    for line in text.splitlines():
        m = re.match(r'^#{1,2}\s+(.+)', line)
        if m:
            # 遇到新标题 → 保存前一章节
            if current_lines:
                chapters.append({
                    'num': current_num,
                    'name': current_title,
                    'text': '\n'.join(current_lines).strip(),
                })
            current_num += 1
            current_title = m.group(1).strip()   # 标题文本（去空格）
            current_lines = []
        else:
            current_lines.append(line)            # 正文行累积

    # 处理最后一章
    if current_lines:
        chapters.append({
            'num': current_num,
            'name': current_title,
            'text': '\n'.join(current_lines).strip(),
        })

    # 过滤掉纯空章节
    return [c for c in chapters if c['text'].strip()]
```

**分片规则总结：**

| 规则 | 说明 |
|-----|-----|
| 触发器 | `^#\s+` 或 `^##\s+` 行 |
| 章节编号 | 从 0 开始，每遇一个标题 +1 |
| 前置内容 | 首个标题前的内容归入 `（前言/概述）`，编号为 0 |
| 空章节 | 有标题但无正文的章节会被过滤 |
| 数据结构 | `{'num': int, 'name': str, 'text': str}` |

---

### 2.3 章节文本截断

**代码位置：** `app/rag_routes.py:1024-1026`

```python
ch_text = ch['raw_text']
if len(ch_text) > 8000:
    ch_text = ch_text[:8000] + '\n\n[（内容过长，已截断）]'
```

- **上限：** 8000 字符（约 2000~4000 tokens，视中英文比例）
- **截断策略：** 硬截断（非按句子/段落对齐），在末尾追加标注
- **截断标注：** `[（内容过长，已截断）]`，让模型感知内容不完整

---

### 2.4 章节入库

截断后的章节写入 `ds_chapters` 表（`app/rag_routes.py:868-878`）：

```python
conn.execute(
    "INSERT INTO ds_chapters "
    "(doc_id, chapter_num, chapter_name, raw_text) VALUES (?,?,?,?)",
    (doc_id, ch['num'], ch['name'], ch['text']),   # raw_text 存原始文本（未截断）
)
```

> **注意：** `ds_chapters` 存储的是**原始未截断**文本；截断仅在调用 DeepSeek 时临时处理。

---

## 3. 第二阶段：章节 → 知识图谱（DeepSeek 提取）

### 3.1 API 调用参数

**代码位置：** `app/rag_routes.py:1034-1042`

```python
resp = client.chat.completions.create(
    model='deepseek-chat',
    messages=[
        {'role': 'system', 'content': _DS_EXTRACT_SYSTEM},
        {'role': 'user',   'content': prompt},
    ],
    max_tokens=3000,
    temperature=0.3,
)
```

| 参数 | 值 | 设计意图 |
|-----|---|---------|
| `model` | `deepseek-chat` | DeepSeek 官方对话模型 |
| `temperature` | `0.3` | 极低温度，确保 JSON 格式稳定、知识点表述一致 |
| `max_tokens` | `3000` | 单章响应上限（3~8 个知识点，每个 200~500 字，足够） |
| `base_url` | `https://api.deepseek.com` | OpenAI 兼容接口 |

---

### 3.2 系统提示词（System Prompt）

**代码位置：** `app/rag_routes.py:841`

```
你是一位专业的教材分析专家，擅长从教材中提取结构化知识图谱。
```

**设计要点：** 简短、角色明确，将模型定位为"教材分析专家"而非通用助手，引导其关注结构化提取而非创意生成。

---

### 3.3 用户提示词（User Prompt）

**代码位置：** `app/rag_routes.py:843-874`（`_DS_EXTRACT_PROMPT`）

**完整模板：**

```
请分析以下教材章节内容，提取该章节的核心知识点及其关系，构建知识图谱。

【学科/科目】：{subject}
【章节名称】：{chapter_name}

【章节原文】：
{chapter_text}

---
**任务要求：**
1. 提取 3-8 个核心知识点
2. 每个知识点的 content 字段应尽量引用原文关键表述，包含：定义/概念、特征/特点、分类/类型、示例/案例等
3. 仅标注同一章节内知识点之间的关系
4. 直接输出纯 JSON，不要添加代码块标记（```）或任何其他文字

**输出格式（严格遵守，直接输出 JSON）：**
{
  "chapter": "章节名称",
  "knowledge_points": [
    {
      "name": "知识点名称（5-20 字）",
      "content": "详细说明（引用原文，200-500 字，包含定义、特征、分类、示例）",
      "relations": [
        {"type": "从属", "target": "上位知识点名称"},
        {"type": "比较", "target": "对比知识点名称"},
        {"type": "并列", "target": "同级知识点名称"}
      ]
    }
  ]
}

关系类型（可组合使用，无关系则填 []）：从属、比较、并列、交叉、前提
```

> **注意：** 模板中的 `{{` / `}}` 是 Python `str.format()` 的转义花括号，实际发送给 DeepSeek 的内容为 `{` / `}`。

**三个占位符：**

| 占位符 | 填充内容 | 来源 |
|-------|---------|-----|
| `{subject}` | 用户在上传界面填写的学科名称 | 前端表单 |
| `{chapter_name}` | 从文档解析出的章节标题 | `ds_chapters.chapter_name` |
| `{chapter_text}` | 章节原文（已做 8000 字截断） | `ds_chapters.raw_text` |

---

### 3.4 提示词设计分析

#### 任务约束层

| 约束 | 作用 |
|-----|------|
| `提取 3-8 个核心知识点` | 防止过少（没意义）或过多（超 token） |
| `引用原文关键表述` | 减少幻觉，提高知识点的原文依据性 |
| `仅标注同一章节内的关系` | 防止跨章引用不存在的知识点 |
| `直接输出纯 JSON` | 明确禁止 Markdown 包裹（```json ... ```），简化后处理 |

#### 输出格式层

```json
{
  "chapter": "章节名称（对照 chapter_name）",
  "knowledge_points": [
    {
      "name": "5-20 字简洁名称",
      "content": "200-500 字详细内容，尽量引用原文",
      "relations": [
        {"type": "关系类型", "target": "同章其他知识点名称"}
      ]
    }
  ]
}
```

**五种关系类型及含义：**

| 类型 | 语义 | 示例 |
|-----|-----|-----|
| `从属` | A 是 B 的下位概念 | 农作物 从属→ 植物 |
| `比较` | A 与 B 相对、对比 | 定性分析 比较→ 定量分析 |
| `并列` | A 与 B 同级平行 | 生产成本 并列→ 销售成本 |
| `交叉` | A 与 B 相互作用 | 土地质量 交叉→ 作物产量 |
| `前提` | A 的实现依赖 B | 播种 前提→ 土壤准备 |

---

### 3.5 输出后处理

**代码位置：** `app/rag_routes.py:1043-1068`

```python
raw = resp.choices[0].message.content.strip()

# 步骤 1：清除 Markdown 代码块标记（防御性处理）
if raw.startswith('```'):
    raw = '\n'.join(raw.split('\n')[1:])   # 去掉第一行（```json 或 ```）
if raw.endswith('```'):
    raw = '\n'.join(raw.split('\n')[:-1])  # 去掉最后一行（```）
raw = raw.strip()

# 步骤 2：JSON 解析
parsed = _json.loads(raw)
kps = parsed.get('knowledge_points', [])

# 步骤 3：逐条入库
with _ds_db_conn() as conn:
    for kp in kps:
        conn.execute(
            "INSERT INTO ds_kps "
            "(doc_id, chapter_name, chapter_num, kp_name, kp_content, relations_json) "
            "VALUES (?,?,?,?,?,?)",
            (
                doc_id,
                ch['chapter_name'],
                ch['chapter_num'],
                kp.get('name', ''),
                kp.get('content', ''),
                _json.dumps(kp.get('relations', []), ensure_ascii=False),
            ),
        )
    conn.commit()
```

**处理链：**
```
DeepSeek 原始输出
    → 去 ``` 包裹（防御性）
    → json.loads()
    → 遍历 knowledge_points[]
    → 每条 INSERT INTO ds_kps
```

---

### 3.6 逐章顺序调用

**代码位置：** `app/rag_routes.py:1018-1073`

```python
for i, ch in enumerate(chapters):
    # 更新任务进度
    _ds_tasks[task_id].update({
        'message': f'正在提取第 {i + 1}/{total} 章：{ch["chapter_name"]}',
        'progress': i,
        'total': total,
    })

    # 截断 + 格式化提示词
    ch_text = ch['raw_text']
    if len(ch_text) > 8000:
        ch_text = ch_text[:8000] + '\n\n[（内容过长，已截断）]'

    prompt = _DS_EXTRACT_PROMPT.format(
        subject=subject or '（未指定）',
        chapter_name=ch['chapter_name'],
        chapter_text=ch_text,
    )

    try:
        # 调用 DeepSeek，解析，入库
        ...
    except Exception as ch_err:
        # 单章失败不中断，跳过继续
        _ds_tasks[task_id]['message'] = (
            f'第 {i + 1} 章提取出错（{ch_err}），跳过，继续下一章...'
        )
```

**关键设计：**
- 章节之间**串行调用**（非并发），避免 API 频率限制
- 每章调用前更新前端可见的任务进度（`progress` / `total`）
- 单章失败**不中断整体**，记录跳过日志后继续下一章

---

## 4. 第三阶段：知识图谱 → 出题（DeepSeek 生成）

### 4.1 知识图谱上下文组装

**代码位置：** `app/rag_routes.py:1274-1304`（`ds_generate` 端点内）

**查询语句：**

```sql
SELECT chapter_name, chapter_num, kp_name, kp_content, relations_json
FROM ds_kps
WHERE doc_id = ?
  [AND chapter_name IN (...)]   -- 可选：按章节筛选
  [AND kp_name IN (...)]         -- 可选：按知识点筛选
ORDER BY chapter_num, id
```

前端支持三级联动筛选（文档 → 章节 → 知识点），未选择时拉取该文档的全部知识点。

**上下文组装逻辑：**

```python
context_parts: list = []
current_chapter = None
total_chars = 0

for kp in kps_data:
    # 超 7000 字封顶
    if total_chars > 7000:
        context_parts.append('\n（已达上下文长度上限，后续知识点省略）')
        break

    # 章节分隔标题
    if kp['chapter_name'] != current_chapter:
        current_chapter = kp['chapter_name']
        context_parts.append(f'\n## {current_chapter}\n')

    # 知识点标题 + 内容
    context_parts.append(f'### 知识点：{kp["kp_name"]}')
    context_parts.append(kp['kp_content'])

    # 关联关系（若有）
    rels = _json.loads(kp['relations_json'] or '[]')
    if rels:
        rel_str = '；'.join(
            f"{r.get('type', '')} → {r.get('target', '')}"
            for r in rels if r.get('target')
        )
        if rel_str:
            context_parts.append(f'关联关系：{rel_str}')

    context_parts.append('')           # 空行分隔
    total_chars += len(kp['kp_content'])

context = '\n'.join(context_parts)
```

**组装后的 context 结构示例：**

```
## 第一章 农业经济学概论

### 知识点：农业经济学的研究对象
农业经济学是研究农业生产中经济关系和经济规律的科学……（200-500字）
关联关系：从属 → 经济学；比较 → 农业生产学

### 知识点：农业的基本特征
农业具有土地依附性、季节性、地域性等基本特征……
关联关系：并列 → 工业特征

## 第二章 农产品供求关系

### 知识点：农产品需求弹性
……
```

**裁剪规则：**

| 层级 | 限制 | 说明 |
|-----|-----|-----|
| 单章文本（提取阶段） | 8000 字 | 输入给提取模型的原文上限 |
| 知识点上下文（生成阶段） | 7000 字 | 输入给出题模型的 context 上限 |
| 单知识点内容 | 200-500 字 | 提示词中的要求（非硬性强制） |

---

### 4.2 出题 API 调用参数

**代码位置：** `app/rag_routes.py:1332-1343`

```python
response = client.chat.completions.create(
    model='deepseek-chat',
    messages=[
        {
            'role': 'system',
            'content': '你是一位专业的教学内容设计专家，擅长根据课程知识图谱设计题库。',
        },
        {'role': 'user', 'content': final_prompt},
    ],
    max_tokens=8000,
    temperature=0.7,
)
```

| 参数 | 提取阶段 | 出题阶段 | 差异原因 |
|-----|---------|---------|---------|
| `model` | `deepseek-chat` | `deepseek-chat` | 相同 |
| `temperature` | `0.3` | `0.7` | 出题需要一定多样性 |
| `max_tokens` | `3000` | `8000` | 出题内容更多 |
| System Role | 教材分析专家 | 教学内容设计专家 | 任务不同 |

---

### 4.3 出题提示词（前端模板）

**代码位置：** `app/templates/index.html`

前端维护三套基础提示词模板，DS 模式通过 `_adaptPromptForDs()` 函数对其做文字替换后使用：

**三套模板：**

| 模板常量 | 适用语言 | System 角色 |
|--------|---------|------------|
| `RAG_PROMPT_ZH` | 中文出题 | 专业教学内容设计专家 |
| `RAG_PROMPT_BILINGUAL` | 中英双语出题 | 双语教学内容设计专家 |
| `RAG_PROMPT_EN` | 英文出题 | Professional academic content designer |

**模板中的两个占位符：**

| 占位符 | 内容 | 来源 |
|-------|-----|-----|
| `{context}` | 知识图谱上下文（≤7000 字） | `ds_generate` 端点组装 |
| `{question_list}` | 题型与数量描述 | 前端用户选择（如"单选 10 题，简答 2 题"） |

**DS 模式文字适配（`_adaptPromptForDs` 替换内容）：**

| 原文（RAG 模式） | 替换为（DS 模式） |
|---------------|----------------|
| `你是一位专业的教学内容设计专家，擅长根据课程材料出题。` | `你是一位专业的教学内容设计专家，擅长根据知识图谱设计题库。` |
| `以下是从知识库检索到的参考内容：` | `以下是从文档中提取的知识图谱信息（包含知识点定义、特征、分类、示例及知识点间关联关系）：` |
| `请根据以上参考内容，按照以下要求生成题目。` | `请根据以上知识图谱信息，按照以下要求生成题目。` |

**中文出题模板关键约束（`RAG_PROMPT_ZH` 节选）：**

```
**质量要求：**
1. 内容必须忠实于参考内容中的知识点，不得编造
2. 难度分布约为：简单(easy) 30%、中等(medium) 50%、困难(hard) 20%
   - 简单(easy)：答案可在参考内容原文中直接找到，考查识记理解
   - 中等(medium)：需结合具体实例或场景，不能仅靠背诵，要求迁移应用
   - 困难(hard)：需综合运用多个知识点，要求整体把握和批判性分析
3. 覆盖参考内容的主要知识点和核心概念
4. 每道题必须标注对应知识点（写在解析里）
5. 题目必须独立成立，严禁出现引用文件位置的表述，如"如第X章所述""见图""根据上文"等
```

---

## 5. 数据库结构

**数据库文件：** `ds_knowledge.db`（项目根目录）
**代码位置：** `app/rag_routes.py:735-778`（`_init_ds_db`）

### 5.1 三张表关系

```
ds_docs (1)
    │── (N) ds_chapters  ← 存储章节原始文本
    └── (N) ds_kps       ← 存储知识点与关系
```

### 5.2 ds_docs — 文档元数据

| 字段 | 类型 | 说明 |
|-----|-----|-----|
| `doc_id` | TEXT PK | 文件名主干（截取 40 字符） |
| `filename` | TEXT | 原始文件名 |
| `subject` | TEXT | 学科名称 |
| `status` | TEXT | `uploaded` / `extracting` / `done` / `error` / `timeout` |
| `error_msg` | TEXT | 错误信息（空字符串表示正常） |
| `created_at` | TEXT | ISO 格式时间戳 |

### 5.3 ds_chapters — 章节原文

| 字段 | 类型 | 说明 |
|-----|-----|-----|
| `id` | INTEGER PK | 自增主键 |
| `doc_id` | TEXT | 关联文档 |
| `chapter_num` | INTEGER | 章节序号（0 起） |
| `chapter_name` | TEXT | 章节标题 |
| `raw_text` | TEXT | 完整原文（**未截断**，最长不限） |

### 5.4 ds_kps — 知识点

| 字段 | 类型 | 说明 |
|-----|-----|-----|
| `id` | INTEGER PK | 自增主键 |
| `doc_id` | TEXT | 关联文档 |
| `chapter_name` | TEXT | 所属章节名 |
| `chapter_num` | INTEGER | 所属章节号 |
| `kp_name` | TEXT | 知识点名称（5-20 字） |
| `kp_content` | TEXT | 知识点详细内容（200-500 字） |
| `relations_json` | TEXT | JSON 字符串，格式：`[{"type":"从属","target":"xxx"}]` |

---

## 6. 错误处理与容错机制

### 6.1 单章提取失败 — 跳过继续

**代码位置：** `app/rag_routes.py:1069-1073`

```python
except Exception as ch_err:
    _ds_tasks[task_id]['message'] = (
        f'第 {i + 1} 章提取出错（{ch_err}），跳过，继续下一章...'
    )
    # 不 raise，继续 for 循环下一章
```

覆盖场景：API 调用超时、JSON 解析失败、网络中断等。

### 6.2 OCR 超时 — 断点续传

**代码位置：** `app/rag_routes.py:598-732`（`_do_ocr_then_parse`）、`pptx_ocr/pipeline.py:209-296`

PDF OCR 按每 10 页一块拆分，每块完成后立即持久化：

```
rag_uploads/<stem>_ocr/
    ├── checkpoint.json      ← {"total": 8, "done": [0, 1, 2, 3]}
    ├── _chunks/
    │   ├── chunk_0000.md    ← 第 1-10 页的 OCR markdown
    │   ├── chunk_0001.md    ← 第 11-20 页
    │   └── ...
    └── images/              ← 已下载的图片（实时写入）
```

超时后任务状态变为 `timeout`，前端显示重试按钮。重试时 `resume=True` 跳过已完成块，从断点继续。

**超时判断关键字（`app/rag_routes.py:741-749`）：**

```python
is_timeout = (
    'timed out' in _lower
    or 'timeout' in _lower
    or 'connectionerror' in _lower
    or 'connection' in _lower and 'error' in _lower
    or 'read timeout' in _lower
)
```

### 6.3 JSON 解析失败 — Markdown 代码块防御

**代码位置：** `app/rag_routes.py:1044-1049`

```python
if raw.startswith('```'):
    raw = '\n'.join(raw.split('\n')[1:])   # 去掉首行（```json）
if raw.endswith('```'):
    raw = '\n'.join(raw.split('\n')[:-1])  # 去掉末行（```）
```

防御 DeepSeek 偶发的输出格式不规范（在 JSON 外包裹 Markdown 代码块）。若 JSON 解析仍失败，该章被跳过（见 6.1）。

### 6.4 API Key 未配置 — 提前返回

**代码位置：** `app/rag_routes.py:1000-1012`

```python
if not api_key:
    _ds_tasks[task_id] = {
        'status': 'error',
        'message': '未设置 DEEPSEEK_API_KEY，请在 API 配置中填写',
    }
    return   # 不进入章节循环
```

Key 读取优先级：`.env` 的 `DEEPSEEK_API_KEY` → `.env` 的 `DEEPSEEK_TOKEN` → 环境变量 `DEEPSEEK_API_KEY` → 环境变量 `DEEPSEEK_TOKEN`。

---

## 7. 参数速查表

### 7.1 分片参数

| 参数 | 值 | 位置 |
|-----|---|-----|
| 章节触发正则 | `^#{1,2}\s+(.+)` | `rag_routes.py:792` |
| 识别标题级别 | `#` 和 `##`（一、二级） | `rag_routes.py:792` |
| 前置内容章节名 | `（前言/概述）` | `rag_routes.py:788` |
| 章节编号起始 | `0` | `rag_routes.py:789` |
| 空章节过滤 | `text.strip()` 为空则丢弃 | `rag_routes.py:811` |
| 章节文本截断 | 8000 字符 | `rag_routes.py:1025` |
| 截断标注文字 | `[（内容过长，已截断）]` | `rag_routes.py:1026` |
| PDF OCR 分块 | 每 10 页一块 | `pipeline.py:21` |
| PDF OCR 超时 | 120 秒/块（含 3 次重试） | `pptx_ocr/config.py:10` |

### 7.2 知识提取 API 参数

| 参数 | 值 | 位置 |
|-----|---|-----|
| Model | `deepseek-chat` | `rag_routes.py:1035` |
| Temperature | `0.3` | `rag_routes.py:1041` |
| Max tokens | `3000` | `rag_routes.py:1040` |
| Base URL | `https://api.deepseek.com` | `rag_routes.py:1015` |
| 知识点数量要求 | 3~8 个/章 | 提示词 |
| 知识点名称长度 | 5~20 字 | 提示词 |
| 知识点内容长度 | 200~500 字 | 提示词 |

### 7.3 出题 API 参数

| 参数 | 值 | 位置 |
|-----|---|-----|
| Model | `deepseek-chat` | `rag_routes.py:1333` |
| Temperature | `0.7` | `rag_routes.py:1342` |
| Max tokens | `8000` | `rag_routes.py:1341` |
| 上下文字数上限 | 7000 字符 | `rag_routes.py:1280` |
| 难度分布 | Easy 30% / Medium 50% / Hard 20% | 出题提示词 |

### 7.4 端点速查

| 端点 | 方法 | 功能 |
|-----|-----|-----|
| `/api/rag/ds-upload` | POST | 上传文档，解析章节结构 |
| `/api/rag/ds-extract/<doc_id>` | POST | 触发知识点提取（DeepSeek 逐章） |
| `/api/rag/ds-tasks/<task_id>` | GET | 轮询任务状态 |
| `/api/rag/ds-retry-ocr/<task_id>` | POST | OCR 超时断点续传 |
| `/api/rag/ds-docs` | GET | 列出所有文档 |
| `/api/rag/ds-docs/<doc_id>/kps` | GET | 获取章节和知识点（三级联动） |
| `/api/rag/ds-docs/<doc_id>` | DELETE | 删除文档及所有数据 |
| `/api/rag/ds-generate` | POST | 根据知识点生成题目 |
