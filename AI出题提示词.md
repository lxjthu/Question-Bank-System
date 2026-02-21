# AI 自动出题提示词

> 用途：将此提示词发给 AI（如 ChatGPT、Claude 等），配合上传的 PPT 或 PDF 文件，自动生成符合本系统导入格式的完整题库。
> 生成结果可直接粘贴到 `.txt` 文件后通过系统"题库管理"→"导入题库"功能导入。

---

## 使用步骤

1. 打开 AI 对话窗口（支持文件上传的版本，如DeepSeek，豆包，千问等）
2. 上传 PPT 或 PDF 文件
3. 根据需要选择以下三种模式之一，复制对应的【主提示词】发给 AI
   - **模式一：纯中文出题**（默认，适合普通中文课程）
   - **模式二：中英双语出题**（适合双语课程，每题同时包含中英两种语言）
   - **模式三：纯英文出题**（适合全英文授课课程）
4. 如需调整题量、题型比例，使用【补充指令】按需追加
5. 将 AI 输出的内容保存为 `.txt` 文件（UTF-8 编码）或docx文件
6. 在系统"题库管理"→"导入题库"中上传该文件

---

## 模式一：【纯中文出题主提示词】

```
你是一位专业的教学内容设计专家，擅长根据课程材料出题。

请仔细阅读我上传的文件（PPT/PDF），全面理解其中的知识点、概念、原理和案例，然后按照以下要求生成一套完整题库。

### 出题要求

**题型与数量：**
- 单选题：15题（每题4个选项A/B/C/D，只有1个正确答案）
- 多选题：8题（每题4个选项A/B/C/D，有2～4个正确答案）
- 是非题：10题（判断正误，答案为"正确"或"错误"）
- 简答题：5题（需提供参考答案）
- 论述题：3题（需提供较详细的参考答案）
- 材料分析题：2题（结合实际案例或材料进行分析）

**质量要求：**
1. 题目内容必须忠实于文件中的知识点，不得编造文件中没有的内容
2. 在每种题型中，题目难度分布约为：简单(easy) 30%、中等(medium) 50%、困难(hard) 20%，三个难度的出题标准如下：
   - **简单(easy)**：答案可以直接在上传材料的原文中找到，考查对定义、概念、步骤等基础内容的识记与理解；是非题和单选题以简单题为主
   - **中等(medium)**：需要结合具体实例或现实应用场景作答，不能仅靠背诵原文，要求学生能将概念迁移到新情境中；典型形式如"举例说明……""分析某案例""比较两种做法的异同"，或在选择、判断题中设计与现实结合的选项
   - **困难(hard)**：需要综合运用多个知识点，跨章节融会贯通，要求学生对知识体系有整体把握；典型形式如"比较多种理论/方法的适用条件""论述某问题的完整解决路径""对给定材料进行批判性分析"；论述题和材料分析题以困难题为主
3. 覆盖文件中的主要章节和核心概念
4. 每道题必须标注对应的知识点（知识点从文件中提取，放在解析里）
5. 选择题的干扰项要合理，不能过于明显
6. 简答题和论述题的参考答案要完整、准确；困难题的参考答案需体现跨知识点的整合与推理过程
7. **题目必须独立成立**，严禁在题干中出现任何引用上传文件位置或呈现方式的表述，例如"如第X章所述""见PPT第X张幻灯片""根据上图""如材料图表所示""结合上文"等——考生在考试时只能看到题目本身，无法看到你所参考的PPT或PDF文件

**输出格式（必须严格遵守）：**

---
**单选题格式：**
[单选][正确选项字母]
题目内容？
[A]选项A内容
[B]选项B内容
[C]选项C内容
[D]选项D内容
<解析>
解析说明（为什么选这个答案）
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**多选题格式：**
[多选][正确选项字母组合，如ABD]
题目内容？
[A]选项A内容
[B]选项B内容
[C]选项C内容
[D]选项D内容
<解析>
解析说明
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**是非题格式：**
[是非][正确|错误]
题目陈述句。
<解析>
解析说明
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**简答题格式：**
[简答]
题目内容？
<参考答案>
参考答案内容（要点1；要点2；要点3……）
</参考答案>
<解析>
解析说明（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:easy|medium|hard
</解析>

---
**论述题格式：**
[简答>论述]
题目内容？
<参考答案>
详细的参考答案，分点论述，逻辑清晰。
</参考答案>
<解析>
解析说明（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:hard
</解析>

---
**材料分析题格式：**
[简答>材料分析]
【材料】
材料内容（一段与课程相关的实际案例、数据或文字材料）

【问题】
基于以上材料，请分析……？
<参考答案>
参考答案（结合材料和理论进行分析）
</参考答案>
<解析>
解析说明（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
难度:hard
</解析>

---

### 格式注意事项

1. 题型标识符必须用方括号包围，如 [单选]、[多选]、[是非]、[简答]、[简答>论述]、[简答>材料分析]
2. 选择题答案紧跟题型标识后，用方括号包围，如 [单选][A]、[多选][ABD]
3. 是非题答案只能是 [正确] 或 [错误]，无需列选项
4. 选项格式：[A]内容、[B]内容，字母大写
5. <解析>...</解析> 中的元数据行格式固定，冒号后不加空格，字段名不可更改
6. 难度值只能是：easy、medium、hard 三选一，必须用英文小写
7. 每道题之间可以有空行，便于阅读
8. 不要添加题号（系统会自动编号）
9. 不要在题目外添加任何说明性文字、章节标题或分割线

现在请开始出题，直接输出题目内容，不需要任何前言。
```

---

## 模式二：【双语出题主提示词】

> 双语模式：每道题同时包含**中文题目**和**英文题目**，系统支持三种显示/导出方式（仅中文 / 仅英文 / 中英并列）。

```
你是一位专业的双语教学内容设计专家，擅长设计中英双语课程题库。

请仔细阅读我上传的文件（PPT/PDF），全面理解其中的知识点，然后按照以下要求生成一套完整的中英双语题库。

### 出题要求

**题型与数量：**
- 单选题：15题（每题4个选项，只有1个正确答案）
- 多选题：8题（每题4个选项，有2～4个正确答案）
- 是非题：10题（判断正误）
- 简答题：5题
- 论述题：3题
- 材料分析题：2题

**质量要求：**
1. 题目内容必须忠实于文件中的知识点，不得编造
2. 题目难度分布约为：简单(easy) 30%、中等(medium) 50%、困难(hard) 20%，三个难度的出题标准如下：
   - **简单(easy)**：答案可以直接在上传材料的原文中找到，考查对定义、概念、步骤等基础内容的识记与理解；是非题和单选题以简单题为主
   - **中等(medium)**：需要结合具体实例或现实应用场景作答，不能仅靠背诵原文，要求学生能将概念迁移到新情境中；典型形式如"举例说明……""分析某案例""比较两种做法的异同"
   - **困难(hard)**：需要综合运用多个知识点，跨章节融会贯通，要求学生对知识体系有整体把握；典型形式如"比较多种理论/方法的适用条件""论述某问题的完整解决路径""对给定材料进行批判性分析"；论述题和材料分析题以困难题为主
3. 覆盖文件中的主要章节和核心概念
4. 每道题必须同时提供中文和英文版本，语义完全对应，英文表达符合学术规范
5. 选择题的中英文选项必须一一对应，顺序和含义完全一致
6. 简答题和论述题的参考答案要完整、准确；困难题的参考答案需体现跨知识点的整合与推理过程
7. **题目必须独立成立**，严禁在题干中出现任何引用上传文件位置或呈现方式的表述，例如"如第X章所述""见PPT第X张幻灯片""根据上图""如材料图表所示""结合上文"等——考生在考试时只能看到题目本身，无法看到你所参考的PPT或PDF文件

**双语输出格式（必须严格遵守）：**

---
**双语单选题格式：**
[单选][正确选项字母]
中文题目内容？
[A]中文选项A
[B]中文选项B
[C]中文选项C
[D]中文选项D
[A_en]English option A
[B_en]English option B
[C_en]English option C
[D_en]English option D
<解析>
中文解析说明
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:English version of the question?
难度:easy|medium|hard
</解析>

---
**双语多选题格式：**
[多选][正确选项字母组合，如ABD]
中文题目内容？
[A]中文选项A
[B]中文选项B
[C]中文选项C
[D]中文选项D
[A_en]English option A
[B_en]English option B
[C_en]English option C
[D_en]English option D
<解析>
中文解析说明
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:English version of the question?
难度:easy|medium|hard
</解析>

---
**双语是非题格式：**
[是非][正确|错误]
中文题目陈述句。
<解析>
中文解析说明
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:English version of the statement.
难度:easy|medium|hard
</解析>

---
**双语简答题格式：**
[简答]
中文题目内容？
<参考答案>
中文参考答案（要点1；要点2；要点3……）
</参考答案>
<解析>
中文解析说明（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:English version of the question?
难度:easy|medium|hard
</解析>

---
**双语论述题格式：**
[简答>论述]
中文题目内容？
<参考答案>
中文参考答案，分点论述，逻辑清晰。
</参考答案>
<解析>
中文解析说明（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:English version of the question?
难度:hard
</解析>

---
**双语材料分析题格式：**
[简答>材料分析]
【材料】
材料内容（中文）

【问题】
中文问题？
<参考答案>
中文参考答案
</参考答案>
<解析>
中文解析（可选）
知识点:对应的章节或知识点名称
标签:标签1,标签2
英文题目:【Material】English material content. 【Question】English question?
难度:hard
</解析>

---

### 双语格式关键规则

1. **选择题选项顺序**：先列全部4个中文选项 [A][B][C][D]，再列全部4个英文选项 [A_en][B_en][C_en][D_en]，英文选项必须与对应中文选项语义一致，字母编号对应
2. **英文题目字段**：所有题型均在 <解析> 区段内写一行 `英文题目:` 提供英文题干，是非题、简答题等非选择题同样需要此字段
3. **材料分析题英文**：在 `英文题目:` 字段内将材料和问题合并写出，用 【Material】/【Question】 分隔
4. **题型标识符**：始终使用中文标识符 [单选]、[多选]、[是非]、[简答] 等，不要改为英文
5. **答案格式**：选择题答案字母 [A]～[D]、是非题答案 [正确]/[错误] 均保持不变
6. **冒号格式**：`英文题目:` 使用英文半角冒号，`英文题目:` 之后直接跟英文内容，不加空格
7. **解析语言**：<解析> 内的中文解析文字可以用中文，但字段名（知识点、标签、英文题目、难度）格式不变
8. 不要添加题号，不要在题目外添加任何说明文字

现在请开始出题，直接输出题目内容，不需要任何前言。
```

---

## 模式三：【纯英文出题主提示词】

> 纯英文模式：题目、选项、解析全部用英文书写，适合全英文授课课程。导入后系统将题目标记为纯英文语言类型。

```
You are a professional academic content designer specializing in creating exam questions.

Please carefully read the uploaded file (PPT/PDF), fully understand all knowledge points, concepts, principles and cases, then generate a complete question bank following the requirements below.

### Question Requirements

**Types and quantities:**
- Single-choice questions: 15 (4 options A/B/C/D, only 1 correct answer)
- Multiple-choice questions: 8 (4 options A/B/C/D, 2~4 correct answers)
- True/False questions: 10 (answer: True or False)
- Short answer questions: 5 (provide reference answers)
- Essay questions: 3 (provide detailed reference answers)
- Case analysis questions: 2 (analysis based on real cases or materials)

**Quality requirements:**
1. Content must be faithfully based on the knowledge points in the file; do not fabricate content
2. Difficulty distribution: approximately 30% easy, 50% medium, 20% hard. Apply the following criteria for each level:
   - **Easy**: The answer can be found directly in the original text of the uploaded material. Tests recall and comprehension of definitions, concepts, and procedures. True/False and single-choice questions should be mostly easy.
   - **Medium**: Requires combining course concepts with concrete examples or real-world application scenarios. Students cannot rely on rote memorization alone — they must transfer concepts to new contexts. Typical forms: "Give an example of…", "Analyze a given case", "Compare two approaches".
   - **Hard**: Requires integrating multiple knowledge points across chapters and demonstrating a holistic understanding of the subject. Typical forms: "Compare the applicability of multiple theories/methods", "Describe a complete solution path for a problem", "Critically analyze a given scenario". Essay and case analysis questions should be mostly hard.
3. Cover major chapters and core concepts from the file
4. Each question must include the corresponding knowledge point (from chapter/section titles)
5. Distractors for choice questions must be plausible, not obviously wrong
6. Reference answers for short answer and essay questions must be complete and accurate; hard question answers should explicitly show cross-topic integration and reasoning
7. **Every question must be self-contained.** Do not include any references to the source material's location or presentation, such as "as discussed in Chapter X", "refer to slide Y", "as shown in the figure above", "according to the passage", or "based on the chart" — students taking the exam can only see the questions themselves, not the PPT or PDF file you are reading

**Output format (must follow strictly):**

---
**Single-choice format:**
[单选][Correct option letter]
Question content in English?
[A]Option A
[B]Option B
[C]Option C
[D]Option D
[A_en]Option A (same text repeated for bilingual storage)
[B_en]Option B
[C_en]Option C
[D_en]Option D
<解析>
Explanation in English.
知识点:Knowledge point name (can be in English)
标签:tag1,tag2
英文题目:Question content in English? (same as above)
难度:easy|medium|hard
</解析>

---
**Multiple-choice format:**
[多选][Correct letters combined, e.g. ABD]
Question content in English?
[A]Option A
[B]Option B
[C]Option C
[D]Option D
[A_en]Option A
[B_en]Option B
[C_en]Option C
[D_en]Option D
<解析>
Explanation in English.
知识点:Knowledge point name
标签:tag1,tag2
英文题目:Question content in English?
难度:easy|medium|hard
</解析>

---
**True/False format:**
[是非][正确|错误]
Statement in English.
<解析>
Explanation in English.
知识点:Knowledge point name
标签:tag1,tag2
英文题目:Statement in English. (same as above)
难度:easy|medium|hard
</解析>

---
**Short answer format:**
[简答]
Question in English?
<参考答案>
Reference answer in English (point 1; point 2; point 3...)
</参考答案>
<解析>
Explanation (optional).
知识点:Knowledge point name
标签:tag1,tag2
英文题目:Question in English?
难度:easy|medium|hard
</解析>

---
**Essay format:**
[简答>论述]
Question in English?
<参考答案>
Detailed reference answer in English, logically structured.
</参考答案>
<解析>
知识点:Knowledge point name
标签:tag1,tag2
英文题目:Question in English?
难度:hard
</解析>

---
**Case analysis format:**
[简答>材料分析]
[Case]
Case material content in English.

[Question]
Based on the above case, analyze...?
<参考答案>
Reference answer in English, integrating theory and case.
</参考答案>
<解析>
知识点:Knowledge point name
标签:tag1,tag2
英文题目:[Case] Case material. [Question] Question in English?
难度:hard
</解析>

---

### Format rules

1. **Question type markers**: Keep Chinese markers [单选], [多选], [是非], [简答], [简答>论述], [简答>材料分析] — these are system codes, do NOT translate them
2. **Answer markers**: Keep [A]~[D] for choices; use [正确] for True, [错误] for False — do NOT change these
3. **Metadata field names**: Keep Chinese field names 知识点, 标签, 英文题目, 难度 exactly as shown — do NOT translate them
4. **For single-choice/multiple-choice**: List all Chinese-slot options [A]~[D] first (with English text), then repeat the same options as [A_en]~[D_en]. This stores the English text in both the options and bilingual options fields.
5. **英文题目 field**: Fill in the same English question text — this enables bilingual export from the system
6. **Difficulty**: Must be one of: easy, medium, hard (lowercase English)
7. Do not add question numbers; do not add any explanatory text outside question blocks

Now please start generating questions. Output question content directly without any preamble.
```

---

## 【补充指令】（可按需追加到任意模式之后）

### 调整题型数量
```
请将题型数量调整为：
- 单选题：[数量]题
- 多选题：[数量]题
- 是非题：[数量]题
- 简答题：[数量]题
- 论述题：[数量]题
- 材料分析题：[数量]题
其余格式要求不变，重新生成。
```

### 指定章节出题
```
请只针对文件中"[章节名称]"这一章节的内容出题，其他章节忽略。
题型和数量保持原来的要求不变。
```

### 指定难度分布
```
请将本次出题的难度偏向困难，easy:medium:hard 的比例调整为 1:3:6。
```

### 按知识点均匀分布
```
请确保每个知识点至少出1道题，知识点从文件的目录或各级标题中提取。
如果某个知识点内容较少，可以只出是非题或简答题。
```

### 增加计算题
```
请额外增加 [数量] 道计算题（格式使用 [简答>计算]），
给出完整的解题步骤和过程作为参考答案。
```

### 为已有中文题库补充英文版本（仅追加英文字段）
```
以下是已有的中文题库，请为每道题补充英文版本，具体要求：
1. 选择题：在所有中文选项 [A][B][C][D] 之后，添加对应的 [A_en][B_en][C_en][D_en] 英文选项
2. 所有题型：在 <解析> 区段内添加一行 "英文题目:English version of the question"
3. 其他所有格式保持不变，不要改动中文内容
请输出补充了英文字段的完整题目。
```

---

## 格式速查表

### 题型标识符对照

| 题型 | 系统标识符 | 答案格式 | 是否有中文选项 | 是否有英文选项 |
|------|-----------|---------|--------------|--------------|
| 单选题 | `[单选]` | `[A]`～`[D]` 之一 | 有 `[A]...[D]` | 可选 `[A_en]...[D_en]` |
| 多选题 | `[多选]` | `[AB]`、`[ACD]` 等 | 有 `[A]...[D]` | 可选 `[A_en]...[D_en]` |
| 是非题 | `[是非]` | `[正确]` 或 `[错误]` | 无 | 无 |
| 简答题 | `[简答]` | 无（写参考答案） | 无 | 无 |
| 计算题 | `[简答>计算]` | 无（写参考答案） | 无 | 无 |
| 论述题 | `[简答>论述]` | 无（写参考答案） | 无 | 无 |
| 材料分析题 | `[简答>材料分析]` | 无（写参考答案） | 无 | 无 |

### `<解析>` 区段元数据字段

| 字段名 | 格式示例 | 是否必填 | 说明 |
|--------|---------|---------|------|
| `知识点` | `知识点:市场结构` | 必填 | 来自文件章节/标题，冒号后无空格 |
| `标签` | `标签:基础,概念` | 建议填 | 多个标签用英文逗号 `,` 分隔 |
| `英文题目` | `英文题目:What is...?` | 双语/英文模式必填 | 所有题型均需填写，包括是非题和简答题 |
| `难度` | `难度:medium` | 必填 | 只能是 `easy`、`medium`、`hard` 之一 |

### 选项格式对照

| 场景 | 格式 | 说明 |
|------|------|------|
| 中文选项 | `[A]选项内容` | 字母 A-D 大写，紧跟内容，无空格 |
| 英文选项 | `[A_en]Option content` | 在所有中文选项 [A]-[D] 之后统一列出 |
| 选项排列 | [A][B][C][D] 然后 [A_en][B_en][C_en][D_en] | 先全部中文，再全部英文，勿交替排列 |

---

## 各模式完整示例

### 模式一：纯中文示例

```
[单选][B]
下列哪项属于完全竞争市场的特征？
[A]市场中只有少数几个卖家
[B]产品同质，买卖双方均为价格接受者
[C]存在较高的市场进入壁垒
[D]卖家对价格有完全控制权
<解析>
完全竞争市场的核心特征是产品同质化和价格接受者，买卖双方均无法影响市场价格。
知识点:市场结构与竞争类型
标签:完全竞争,市场结构,微观经济
难度:easy
</解析>

[是非][错误]
在完全垄断市场中，垄断者的边际收益等于价格。
<解析>
在垄断市场中，厂商面对向下倾斜的需求曲线，边际收益小于价格（MR < P），而非相等。
知识点:垄断市场分析
标签:垄断,边际收益,定价
难度:medium
</解析>

[简答]
什么是机会成本？举例说明其在经济决策中的应用。
<参考答案>
机会成本是指为了得到某种东西而必须放弃的其他东西的最高价值。
举例：大学生选择上学而非工作，机会成本包括放弃的工资收入；企业用自有资金投资某项目，机会成本是将该资金存入银行所能获得的利息。
</参考答案>
<解析>
知识点:基本经济概念
标签:机会成本,稀缺性,决策
难度:easy
</解析>
```

### 模式二：双语示例

```
[单选][B]
下列哪项属于完全竞争市场的特征？
[A]市场中只有少数几个卖家
[B]产品同质，买卖双方均为价格接受者
[C]存在较高的市场进入壁垒
[D]卖家对价格有完全控制权
[A_en]There are only a few sellers in the market
[B_en]Products are homogeneous and both buyers and sellers are price takers
[C_en]There are high barriers to market entry
[D_en]Sellers have full control over prices
<解析>
完全竞争市场的核心特征是产品同质化和价格接受者，买卖双方均无法影响市场价格。
知识点:市场结构与竞争类型
标签:完全竞争,市场结构,微观经济
英文题目:Which of the following is a characteristic of a perfectly competitive market?
难度:easy
</解析>

[是非][错误]
在完全垄断市场中，垄断者的边际收益等于价格。
<解析>
在垄断市场中，厂商面对向下倾斜的需求曲线，边际收益小于价格（MR < P），而非相等。
知识点:垄断市场分析
标签:垄断,边际收益,定价
英文题目:In a pure monopoly market, the monopolist's marginal revenue equals the price.
难度:medium
</解析>

[简答]
什么是机会成本？举例说明其在经济决策中的应用。
<参考答案>
机会成本是指为了得到某种东西而必须放弃的其他东西的最高价值。
举例：大学生选择上学而非工作，机会成本包括放弃的工资收入；企业用自有资金投资某项目，机会成本是将该资金存入银行所能获得的利息。
</参考答案>
<解析>
知识点:基本经济概念
标签:机会成本,稀缺性,决策
英文题目:What is opportunity cost? Illustrate its application in economic decision-making with examples.
难度:easy
</解析>

[简答>材料分析]
【材料】
2020年新冠疫情期间，口罩价格暴涨数十倍。部分地区政府随即出台最高限价令，然而限价令实施后，口罩供应量反而急剧减少，出现"一罩难求"局面。

【问题】
运用供求理论分析口罩限价令为何导致供应短缺，并提出更合理的应对措施。
<参考答案>
一、限价令导致短缺：最高限价低于均衡价格，需求增加而供给减少，出现超额需求。
二、合理措施：政府采购统一分配、给予企业补贴扩产、降低进口关税、打击囤积行为。
</参考答案>
<解析>
知识点:价格机制与政府干预
标签:价格管制,供求理论,市场均衡
英文题目:【Material】During the COVID-19 pandemic in 2020, mask prices surged dramatically. Some local governments imposed price caps, but mask supplies dropped sharply afterward, leading to severe shortages. 【Question】Using supply and demand theory, analyze why the price cap led to shortages, and propose more effective policy responses.
难度:hard
</解析>
```

### 模式三：纯英文示例

```
[单选][B]
Which of the following is a characteristic of a perfectly competitive market?
[A]There are only a few sellers in the market
[B]Products are homogeneous and both buyers and sellers are price takers
[C]There are high barriers to market entry
[D]Sellers have full control over prices
[A_en]There are only a few sellers in the market
[B_en]Products are homogeneous and both buyers and sellers are price takers
[C_en]There are high barriers to market entry
[D_en]Sellers have full control over prices
<解析>
In a perfectly competitive market, products are homogeneous and no single buyer or seller can influence the market price — they are all price takers.
知识点:Market Structure and Competition
标签:perfect competition,market structure,microeconomics
英文题目:Which of the following is a characteristic of a perfectly competitive market?
难度:easy
</解析>

[是非][错误]
In a pure monopoly market, the monopolist's marginal revenue equals the price.
<解析>
This is false. A monopolist faces a downward-sloping demand curve, so marginal revenue is less than price (MR < P). Only in a perfectly competitive market does MR = P.
知识点:Monopoly Market Analysis
标签:monopoly,marginal revenue,pricing
英文题目:In a pure monopoly market, the monopolist's marginal revenue equals the price.
难度:medium
</解析>

[简答]
What is opportunity cost? Illustrate its application in economic decision-making with examples.
<参考答案>
Opportunity cost is the value of the next best alternative forgone when making a decision.
Example 1: A student who chooses to attend university foregoes the salary they could have earned by working full-time — that forgone salary is the opportunity cost of higher education.
Example 2: A firm that invests its own capital in a project forgoes the interest income it could have earned by depositing those funds in a bank — that interest is the opportunity cost of the investment.
</参考答案>
<解析>
知识点:Fundamental Economic Concepts
标签:opportunity cost,scarcity,decision-making
英文题目:What is opportunity cost? Illustrate its application in economic decision-making with examples.
难度:easy
</解析>
```

---

## 常见问题

**Q：导入失败怎么办？**
- 检查文件编码是否为 UTF-8（Windows 记事本保存时选择"UTF-8"，不是"ANSI"）
- 检查题型标识符是否用半角方括号包围，如 `[单选]`，不能有空格或全角括号
- 检查选项格式是否正确：`[A]内容`，字母大写，紧跟内容，无空格
- 检查 `<解析>` 和 `</解析>`、`<参考答案>` 和 `</参考答案>` 标签是否成对出现
- 检查 `难度:` 值是否为 `easy`、`medium`、`hard` 之一（英文小写）

**Q：双语模式下英文题目没有被导入进去？**
- 确认 `英文题目:` 字段写在 `<解析>` 和 `</解析>` 标签之间
- 确认字段名是 `英文题目`（中文），冒号为英文半角冒号 `:`，冒号后直接跟英文内容
- 导入成功后，在题目详情中查看"英文版本"字段是否有内容

**Q：纯英文模式下题目语言如何识别？**
- 填写了 `英文题目:` 字段的题目，系统会自动将 `language` 标记为 `both`（双语）
- 如需标记为纯英文，在导入后可在系统编辑界面修改语言设置

**Q：如何生成更多题目？**
- 在补充指令中调大各题型数量即可，建议单次不超过 100 题，分批生成更稳定

**Q：题目中需要包含公式或图表怎么办？**
- 公式建议用 Unicode 字符（如 σ²、Σ、∫、≤、→）或文字描述代替
- 含图的题目导入后可通过编辑功能手动完善

**Q：选择题超过4个选项怎么办？**
- 系统支持任意数量选项，直接按 [A][B][C][D][E] 顺序排列即可
- 英文选项同理：[A_en][B_en][C_en][D_en][E_en]

---

*此提示词文件适用于：试题管理系统 v2.0+，格式版本：2025*
