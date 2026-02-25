"""所有 DeepSeek API Prompt 模板。"""


def kg_extraction_prompt(
    chapter_number: str,
    chapter_name: str,
    chapter_text: str,
    subject_hint: str = '农业经济学',
) -> str:
    expert_role = f"{subject_hint}专家和教学内容分析专家" if subject_hint else "学科专家和教学内容分析专家"
    return f"""你是一位{expert_role}。请分析以下章节/主题内容，提取核心知识点及其关系，构建结构化知识图谱。

【章节】{chapter_number} {chapter_name}

【章节内容】
{chapter_text}

【输出要求】
请严格输出以下 JSON 格式，不要添加任何额外说明、markdown 代码块标记或注释：

{{
  "key_points": ["必考重点1", "必考重点2"],
  "difficulty_points": ["易混淆难点1", "易混淆难点2"],
  "concepts": [
    {{"name": "概念名称", "description": "一句话定义（20字以内）", "is_key": true, "is_difficult": false}}
  ],
  "relations": [
    {{"from": "概念A", "to": "概念B", "type": "关系类型"}}
  ]
}}

【字段说明】
- key_points：从章节「学习目标」中提取必须掌握的概念，5~8 个
- difficulty_points：学生容易混淆或理解有难度的概念，3~5 个
- concepts：本章所有重要概念，10~20 个；name 需与 relations 中使用的名称完全一致
- relations 中 type 只能是以下 4 种之一（英文，不可更改）：
    * is_a           — 上下位关系，如「家庭承包经营」是一种「农业经营制度」
    * contrasts_with — 对比关系，如「狭义农业」与「广义农业」形成对比
    * depends_on     — 依赖关系，A 成立以 B 为前提
    * leads_to       — 因果关系，A 导致/推动 B，如「人民公社体制」leads_to「农村家庭承包改革」

【重要】
- relations 中出现的概念名称必须在 concepts 列表中存在
- 仅输出 JSON，不要有 ```json 等标记，不要有任何前言或后记"""


def question_generation_prompt(
    chapter_number: str,
    chapter_name: str,
    chapter_text: str,
    kg_data: dict,
    question_config: dict,
) -> str:
    concepts = kg_data.get("concepts", [])
    relations = kg_data.get("relations", [])

    key_points = [c["name"] for c in concepts if c.get("is_key_point")]
    diff_points = [c["name"] for c in concepts if c.get("is_difficult_point")]
    contrast_pairs = [(r["from"], r["to"]) for r in relations if r["type"] == "contrasts_with"]
    leads_to_pairs = [(r["from"], r["to"]) for r in relations if r["type"] == "leads_to"]

    kg_block = f"重点知识点（必须覆盖出题）: {', '.join(key_points) if key_points else '见章节内容'}\n"
    kg_block += f"难点知识点（着重出题）: {', '.join(diff_points) if diff_points else '见章节内容'}"
    if contrast_pairs:
        pairs_str = "; ".join(f"「{a}」vs「{b}」" for a, b in contrast_pairs[:6])
        kg_block += f"\n对比关系（优先出多选/简答比较题）: {pairs_str}"
    if leads_to_pairs:
        pairs_str = "; ".join(f"「{a}」→「{b}」" for a, b in leads_to_pairs[:6])
        kg_block += f"\n因果关系（优先出论述题）: {pairs_str}"

    q_lines = "\n".join(f"- {qtype}：{count}题" for qtype, count in question_config.items())
    total = sum(question_config.values())

    return f"""你是一位专业的教学内容设计专家，擅长根据课程材料出题。

请仔细阅读以下章节内容，结合知识图谱信息，生成指定题量的题库。

【本章知识图谱】
{kg_block}

【章节内容】
{chapter_number} {chapter_name}

{chapter_text}

### 出题要求

**题型与数量（共 {total} 题）：**
{q_lines}

**质量要求：**
1. 题目内容必须忠实于章节内容，不得编造章节中没有的内容
2. 难度分布：简单(easy) 30%、中等(medium) 50%、困难(hard) 20%
   - easy：答案可直接在原文找到，考查定义、概念识记；单选/是非题以此为主
   - medium：需结合实例或应用场景，要求概念迁移；如「举例说明」「比较两种做法」
   - hard：综合多个知识点，跨概念分析；论述/材料分析题以此为主
3. **重点知识点每个至少出 1 题；难点知识点着重出题**
4. 有「对比关系」的概念对，至少出 1 道多选题或简答比较题
5. 有「因果关系」的概念对，论述题优先从此处取材
6. **题目必须独立成立**，不得出现「如上图」「如第X章所述」「根据材料图表」等引用表述
7. 每题须在 <解析> 中标注知识点（可写章节名或具体概念）和难度

**输出格式（必须严格遵守）：**
- 所有括号用半角：[ ] < >，禁用全角【】（）＜＞
- 题型标识：[单选][A]、[多选][ABD]、[是非][正确]或[是非][错误]、[简答]、[简答>论述]、[简答>材料分析]
- 选项行顶格写，前面不能有空格：[A]选项内容
- <解析>…</解析> 和 <参考答案>…</参考答案> 必须成对出现
- 知识点/标签/难度字段必须写在 <解析> 内
- 难度只能写 easy、medium、hard（英文小写）
- 不要添加题号，不要使用 Markdown 格式符号（*、**、# 等）
- 每题之间留一个空行

---
**单选题格式：**
[单选][正确选项字母]
题目内容？
[A]选项A
[B]选项B
[C]选项C
[D]选项D
<解析>
解析说明。
知识点:{chapter_number}
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**多选题格式：**
[多选][正确选项字母组合]
题目内容？
[A]选项A
[B]选项B
[C]选项C
[D]选项D
<解析>
解析说明。
知识点:{chapter_number}
标签:标签1,标签2
难度:medium|hard
</解析>

---
**是非题格式：**
[是非][正确|错误]
陈述句。
<解析>
解析说明。
知识点:{chapter_number}
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**简答题格式：**
[简答]
题目？
<参考答案>
要点1；要点2；要点3
</参考答案>
<解析>
解析说明（可选）。
知识点:{chapter_number}
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**论述题格式：**
[简答>论述]
题目？
<参考答案>
分点论述，逻辑清晰。
</参考答案>
<解析>
知识点:{chapter_number}
标签:标签1,标签2
难度:hard
</解析>

---
**材料分析题格式：**
[简答>材料分析]
【材料】
与本章内容相关的实际案例或政策背景（3~5句话）

【问题】
基于以上材料，请分析……？
<参考答案>
结合材料和理论进行分析。
</参考答案>
<解析>
知识点:{chapter_number}
标签:标签1,标签2
难度:hard
</解析>

---

现在请开始出题，直接输出题目内容，不需要任何前言或结尾说明。"""
