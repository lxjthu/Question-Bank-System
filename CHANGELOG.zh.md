# 更新日志

## 1.26.0 - 2026-03-25

### 新功能

- **套题质量检查** — 历史场次列表新增「检查」按钮（位于「查看套题」和「删除场次」之间），调用 DeepSeek 对场次内全部题目进行两类检查：① 题干答案混淆（答案混入题干、多题混为一题、参考答案为空但题干含定义）；② 英文题干语法错误（`content_en` 字段明确语法问题）
- 检查结果以弹窗展示，每条问题原文/建议双栏对比，可逐条勾选后批量一键修复（调用现有 `PUT /api/questions/<id>` 接口）
- 误报自动过滤：`suggested == original` 或建议为空时不显示

### 后端新增 API

- `POST /api/interview/sessions/<id>/quality-check` — 检查场次题目质量，返回 `{total_checked, issues_found, results}`

---

## 1.25.0 - 2026-03-25

### 优化

- **随机抽取套数可配置** — 随机抽选面板新增「抽取套数」数字输入框（默认 1，范围 1-20），按钮文案改为「随机抽取」；全屏展示配色从 3 色扩展至 10 色，支持更多套数循环配色

---

## 1.24.0 - 2026-03-25

### 新功能

- **历史场次删除** — 套题生成与管理面板的历史场次列表每行新增「删除场次」按钮；删除后级联清除该场次所有套题，并自动重置受影响题目在池中的 `drawn` 状态（若题目未出现在其他套题中），三个 `interview_*` 状态字段同步重算
- **套题替换与编辑** — 「查看套题」Modal 重构为「查看/编辑」视图：每道题旁新增「编辑」按钮（弹出现有编辑 Modal，支持修改题干/答案/解析等）和「替换」按钮（内联展开候选题列表，从同池 `drawn=0`、同题型的题目中选用，替换后自动维护 `drawn` 状态）
- **随机抽选全屏展示** — 点击「随机抽取一套」后改为连续抽取最多 3 套（全部标记已使用），弹出覆盖全屏的优雅展示页面：深色渐变背景、大字体（1.25rem）题干、无答案按钮、三套题以 A/B/C 彩色标识区分；顶部固定导航含场次名和「关闭展示」按钮

### 后端新增 API

- `DELETE /api/interview/sessions/<id>` — 删除场次（级联删套题 + 重置 drawn + 同步 interview 状态）
- `GET /api/interview/sets/<set_id>/candidates?slot_index=N` — 获取指定槽位的候选替换题（同池、`drawn=0`、同题型，最多 60 道）
- `POST /api/interview/sets/<set_id>/replace` — 替换套题中某槽位题目（`slot_index` + `new_question_id`）

---

## 1.23.0 - 2026-03-25

### 新功能

- **面试池题干搜索** — 筛选条件区新增「题干搜索」输入框，可按题目正文关键词过滤（如输入"一号文件"，命中题干含该词的全部题目）；后端 `_build_filter_query` 新增 `search` 参数，对 `q.content` 做 `LIKE` 模糊查询
- **预览命中题目多选** — 点击「预览筛选」后，命中题目列表每条附带多选框（默认全选）；新增「全选」「全不选」按钮和已勾选计数提示；点击「加入面试池」时：若预览已展示，仅将**已勾选**的题目加入池（通过 `question_ids` 直传后端，跳过二次筛选）；若未预览，则仍按筛选条件全量加入
- **面试池完整题干展示** — 面试池当前题目列表从表格"题目摘要"（80字截断）改为显示**完整题干纯文本**（word-wrap，无截断），可直接在列表中阅读题目
- **题目查看 / 编辑 Modal** — 面试池列表每行新增「查看/编辑」按钮（蓝色），点击弹出模态框，展示完整题目信息并支持在线编辑：题型、科目、难度、知识点、题干 HTML（含「预览渲染」切换）、答案、参考答案、解析；保存调用 `PUT /api/questions/<id>`，成功后自动刷新列表；支持 ESC 关闭

### 优化

- **预览内容展示加长** — 预览命中题目摘要截断从 80 字提升至 200 字，显示更多题干信息
- **面试池表格精简** — 表格从 8 列压缩为 5 列（题型 / 科目 / 难度+状态 / 题干 / 操作），去除重复展示的题号、语言列

### 后端变更

- `_build_filter_query`：新增 `search` 参数（`q.content LIKE :search`）
- `add_to_pool`：支持 `question_ids` 直传列表，有此参数时跳过筛选条件直接加入
- `preview_filter`：`content_preview` 截断从 80 → 200 字

---

## 1.22.0 - 2026-03-25

### 修复

- **ds_generate 400 错误** — `max_tokens` 从 `16000` 修正为 `8192`（DeepSeek API 输出上限），消除 `Invalid max_tokens value` 报错

### 优化

- **非分批出题 KP 智能采样** — 非分批模式不再堆入全部知识点，改为从过滤后的 KP 中随机采样与题目数等量的知识点，并自动扩展每个 KP 的关联知识点（`relations_json`）作为背景 context；KP 总数 ≤ 题目数时退化为全量使用
- **Token 溢出自动分批** — 新增预检逻辑：估算输出 token（`total_q × 350`）> 7500 或估算输入 token > 40000 时，自动将 `batch_mode` 切换为 `true`，`batch_size = max(5, total_q // 2)`，无需用户手动开启分批；返回 `stats.auto_batched=true` 标记
- **kp_index 全局共用** — `kp_index`（KP 名称 → 行的字典）提前构建，稀疏采样模式和非分批模式共用同一份，消除重复构建

---

## 1.21.0 - 2026-03-25

### 新功能

- **题库面试状态字段** — `questions` 表新增三个面试状态字段，在题库管理列表的"状态"列中以彩色徽章展示：
  - `interview_pool`（蓝色「面试池」）— 该题目当前在至少一个面试题库池中
  - `interview_set`（黄色「套题」）— 该题目已被分配进某套面试套题
  - `interview_used`（紫色「面试用」）— 该题目所在套题已被标记为面试使用
- **自动同步** — 面试抽题模块所有关键操作（加入/移出池、生成套题、标记使用、释放套题、批量标记、Excel 导入、删除池）均调用 `_sync_question_interview_status()` 自动重新计算并写回这三个字段；字段始终与面试表实际状态保持一致

### 数据库变更（自动迁移，无需手动操作）

`questions` 表新增三列（`ALTER TABLE … ADD COLUMN … DEFAULT 0`，幂等）：
- `interview_pool BOOLEAN DEFAULT 0`
- `interview_set BOOLEAN DEFAULT 0`
- `interview_used BOOLEAN DEFAULT 0`

---

## 1.20.0 - 2026-03-25

### 新功能

- **面试抽题标签页** — 新增第 8 个标签页「面试抽题」，专为面试场景的题目管理与抽选设计，包含以下子功能：
  - **多命名题库池** — 支持创建多个命名的面试题库池（如「春招池」「秋招池」），每个池独立管理；题库池之间互不干扰，主题库的 `is_used` 字段不受影响
  - **题库筛选入池** — 按科目（多选）、题型（多选）、难度（多选）、语言、知识点、考点/标签从题库中筛选题目，支持预览命中数量后一键加入池；自动排除已在池中的题目
  - **套题配置** — 为每个题库池配置套题槽位（题型+语言偏好+难度偏好+备注），支持动态增删行，持久化保存
  - **批量生成套题** — 输入场次名称、面试人数、备用倍数（如 10 人×3 倍=30 套），自动用 Fisher-Yates 洗牌后全局无重复分配，同一题目不会出现在两套题中；不足时返回分槽位警告，提示缺少的题型和缺口数量
  - **随机抽选** — 从指定场次中随机取一套未使用套题，自动标记已使用并展示完整题干（含答案折叠查看）
  - **套题状态管理** — 逐套标记已使用（附使用时间）/ 批量标记 / 释放（重置题目在池中的可抽状态）
  - **Word 导出** — 将选定场次的套题（全部/仅未使用/仅已使用）导出为 Word 文档，保留 HTML 富文本格式（图片/表格），可选是否含答案，每套题之间加分页符
  - **Excel 导出导入**（支持跨机器迁移）：
    - 面试题库池导出为 Excel（含题目全字段），导入时若题目 ID 不在本地数据库则自动新建再入池
    - 套题记录导出为双 Sheet Excel（Sheet1: 套题列表，Sheet2: 题目详情），导入时还原场次和套题状态，题目不存在时从 Sheet2 自动补建
  - **警告系统** — 题目不足或题型缺失时模态弹窗提示，含一键跳转「去筛选题目」按钮

### 新增文件

- `app/interview_routes.py` — 面试抽题 Blueprint（31 个 API 端点）
- `tests/test_interview.py` — 43 个自动化测试（39 通过，4 因测试环境无 openpyxl 跳过）

### 数据库变更（自动迁移，无需手动操作）

新增 5 张表（`CREATE TABLE IF NOT EXISTS`，幂等）：
- `interview_pools` — 命名题库池
- `interview_pool_questions` — 池中题目（含 `drawn`/`drawn_at` 状态）
- `interview_configs` — 套题槽位配置
- `interview_sessions` — 面试场次
- `interview_sets` — 套题记录（含 `is_used`/`used_at`）

---

## 1.19.0 - 2026-03-25

### 新功能

- **分批出题稀疏随机采样模式** — 分批出题时新增自动检测逻辑：若当前知识点总数 > 题目总数 × 3（包含全选/全不选两种典型场景），自动切换为稀疏随机采样模式：每批从全部知识点池中随机采样等于该批题目数的知识点，并自动扩展每个采样KP的关联知识点（`relations_json` 中的 `target`）作为背景上下文；各批独立随机，互不影响；批次数由 `ceil(总题数 / batch_size)` 决定（`batch_size` 此时含义为每批题数）；结果标题显示「随机采样 N 个知识点，题目 M-K」；返回 `stats.sparse_mode=true`；知识点数 ≤ 题目数×3 时保持现有顺序切片分批逻辑不变

---

## 1.18.0 - 2026-03-24

### 新功能

- **知识点 Excel 导入回写** — 知识图谱 Modal 工具栏新增「导入 Excel」按钮（与「导出 Excel」并列）：用户将导出的 `.xlsx` 修改后重新上传，系统按知识点名称匹配，将教学属性（重点/难点/考点、知识类型、认知维度）、关系（前提/并列）、层级（L4 子节 `sub_section_name`，支持五层）一次性回写数据库；Excel 中空字段保留数据库原值（不覆盖）；数据库中有但 Excel 里没有的知识点保留不删；L1 名称变更写入 `ds_docs.display_name`，导出时优先使用；导入完成后自动刷新图谱视图；新增后端端点 `POST /api/rag/ds-import-xlsx`

### 数据库变更（自动迁移，无需手动操作）

- `ds_docs` 新增 `display_name TEXT DEFAULT ''` — 用户自定义文档显示名
- `ds_kps` 新增 `sub_section_name TEXT DEFAULT ''` — L4 子节名，支持导出五层层级（`section_name → sub_section_name → kp`）

---

## 1.17.0 - 2026-03-23

### 新功能

- **重难点文件智能匹配** — 导入重难点列表文件（`.txt`/`.md`）后，系统自动解析文件结构（去除 `#`/`-`/序号等标记），提取纯主题字符串；通过三级匹配策略（①KP 名称直接出现在主题行 ②主题冒号前标题出现在 KP 文本 ③≥2 个中文关键词出现在 KP 文本）直接匹配知识点，无需 AI 介入；命中的知识点自动标注为"重点"，前端实时显示「解析 N 条 → 匹配 M/K 个知识点 ✓」；侧边栏知识点属性标签同步刷新；新增后端端点 `POST /api/rag/ds-match-focus`（`_parse_focus_topics` + `_match_kp_to_topics` 两个辅助函数）

### 修复

- **AI批量标注 `KeyError: 'seq'`** — 前端传入的用户提示词含 JSON 示例（`{"seq": 1, ...}`），后端 `str.format(kp_list=...)` 将 `{seq}` 解析为格式化字段，抛出 `KeyError: 'seq'`；改用 `str.replace('{kp_list}', ...)` 精确替换，避免误解析 JSON 中的花括号

---

## 1.16.0 - 2026-03-22

### 新功能

- **知识图谱 Modal 侧边栏可拖拽调宽** — 左侧筛选面板右边缘新增拖拽分隔条（hover 变紫），可拖动调整宽度（120px~420px）；右侧知识点详情面板左边缘同样支持拖拽（200px~600px），宽度在节点切换时保持；面板关闭（width:0）时分隔条同步隐藏
- **知识图谱 Modal 字体大小调节** — 标题栏新增 `A−  100%  A+` 控件（6 档：75%/85%/100%/115%/130%/150%），通过 CSS `zoom` 属性同步缩放左侧筛选面板、图例栏、右侧详情面板的所有文本（包含 `rem`/`px` 等各种单位），D3 画布不受影响

---

## 1.15.0 - 2026-03-22

### 新功能

- **出题配置知识点属性筛选** — 出题配置区新增「知识点属性筛选」面板，支持按教学属性（重点/难点/考点，可同时勾选）、知识类型（事实性/概念性/程序性/元认知）、认知维度（记忆/理解/应用/分析/评价/创造）筛选；不勾选任何项表示不限制；各组之间为 AND，组内多选为 OR；知识点列表中每项展示彩色属性标签（重/难/考 + 知识类型 + 认知维度）；筛选参数透传后端 `ds_generate` SQL 查询（`teaching_focus` 用 `INSTR` 匹配，支持逗号分隔多值）

---

## 1.14.0 - 2026-03-22

### 新功能

- **AI批量标注提示词可见/可编辑** — 知识图谱左侧面板新增折叠式「查看/编辑提示词」区域（默认收起）：系统提示词和用户提示词分别用 textarea 展示，可直接修改；「恢复默认」按钮一键重置；修改后的提示词在本次标注中生效（传递给后端，覆盖模块级默认常量）
- **重难点列表文件导入** — 新增「导入重难点列表」文件上传按钮（支持 `.txt`/`.md`）：上传后自动将文件内容嵌入提示词的 `{focus_section}` 占位区，并自动勾选「同时标注教学属性」复选框
- **同时标注教学属性（teaching_focus）** — AI批量标注新增可选项：勾选后同时判断并写回 `teaching_focus`（重点/难点/考点，逗号分隔多值；使用含教学属性的扩展版提示词模板）；`ds_batch_classify` 端点新增 `classify_focus`、`system_prompt`、`user_prompt` 参数

### 修复

- **AI批量标注 `KeyError: 'name'`** — `_classify_batch()` 访问 `kp['name']` 和 `kp.get('content')`，但 SQL 返回字段为 `kp_name` / `kp_content`，导致标注时报错；改为正确字段名

---

## 1.13.0 - 2026-03-22

### 新功能

- **题库 xlsx 导入** — 导入功能新增支持 `.xlsx` 格式，与导出使用相同的 `muban_zh.xlsx` 模板；自动检测标题行（兼容本系统导出格式和外部题库格式）；答案自动规范化：多选 `A,B`→`AB`，判断 `true`→`正确`；未知题型跳过并在返回值 `parse_errors` 中列出；文件选择框新增 `.xlsx` 扩展名支持

### 修复

- **测试：`test_confirm_marks_then_generate_no_overlap`** — 该测试因抽题为 `random()` 顺序而硬编码期望值 `co2`，导致约 50% 概率随机失败；改为记录第一次抽题结果，断言两次试卷 ID 不重叠，消除随机性依赖

---

## 1.9.0 - 2026-03-22

### 新功能

- **题库 xlsx 批量导出** — 题库管理页批量操作栏新增「导出xlsx」按钮：勾选题目后一键导出为 `muban_zh.xlsx` 标准格式；导出前自动检查各字段（题干/答案/解析/选项）是否超出 500 字符，超限题目逐一弹窗提示「截断导出」或「跳过」；标签自动限制最多 3 个（优先取 `knowledge_point`，再取 `tags`）

---

## 1.7.0 - 2026-03-18

### 新功能

- **提示词模板命名保存** — 「知识图谱」出题页与「题库导入」AI 提示词区均新增提示词保存/加载功能：点击「保存当前」输入名称即可；已保存模板显示在下拉选择器"我的提示词"分组，随时切换；重名时提示覆盖或自动追加日期后缀；自定义模板可删除，默认模板不可删；数据存于 `localStorage`
- **题库导入提示词可编辑** — 「题库导入」页的 AI 出题提示词文本框由只读改为可编辑，可直接在页面内修改模板内容
- **智能标题层级解析（两层并行提取）** — 上传文档后自动统计各级标题出现次数，以"出现≥2次的最高级别"为章级别，下一级为节级别；知识点以**节**为最小提取单元，内容更聚焦；若无子节则整章提取（自动降级）
- **知识点在线编辑** — 知识图谱弹窗右侧新增滑入式详情面板（340px），单击任意节点可查看完整内容并直接编辑名称、正文和关联关系；保存后图谱节点文字同步更新；编辑未保存时切换节点或关闭弹窗弹出二次确认
- **Windows EXE 打包支持** — 新增 `build_win.bat` 和 `exam_system_win.spec`，支持 PyInstaller 打包为 Windows 单文件可执行程序
- **macOS DMG 打包支持** — 新增 `build_mac.sh` 和 `exam_system.spec`，支持打包为 Apple Silicon arm64 安装包
- **试卷列表保存与最终确认锁定** — 生成的试卷自动保存至数据库，可查看历史试卷列表；"最终确认"后试卷题目锁定，标记为已使用，防止跨年度重复出题
- **组卷随机抽题** — 一键生成试卷时改为随机抽取，每次组卷结果不同

### 修复

- **zip 文件名改为 ASCII** — 修复 release 包文件名含中文时 GitHub release 上传失败的问题
- **DMG 版本支持 DS 模式** — 修复 macOS 打包版未包含 DS 直出模式所需模块的问题
- **release 包补全打包项** — `make_release.py` 补充 `kg_routes.py` 和 `kg.html` 打包逻辑

### 文档

- 新增 Windows/macOS 双平台打包完整指引
- 新增 API Key 申请和 PDF 转 Markdown 使用说明

---

## 1.6.2 - 2026-02-27

### 修复

- **DS 出题无文档/无 KP 时返回明确错误** — 未勾选文档或知识点提取未完成时，`ds-generate` 接口提前返回 400 错误，不再将错误提示文字填入提示词发送给 DeepSeek
- **提示词强调题干不得引用知识图谱** — 三套提示词模板（中文/双语/英文）各新增两处警告，明确禁止在题干中出现"根据知识图谱"等表述（考生看不见背景材料）

### 文档

- 新增《闪卡自测系统技术方案》，涵盖 SRS 算法、数据模型、API 设计、UI 原型及三阶段实施计划

---

## 1.6.1 - 2026-02-27

### 新功能

- **WPS Office 转 PDF 支持** — `pptx_ocr` 转换器新增 WPS Office (`KWPP.Application`) 作为备选，优先尝试 Microsoft Office，失败后自动切换 WPS

### 修复

- **Release 包补全 RAG 模块** — `make_release.py` 新增 `rag_pipeline/`、`pptx_ocr/`、`app/rag_routes.py`、`requirements-rag.txt` 的打包逻辑，修复之前 release 包缺少 RAG 相关代码的问题

### 维护

- 两段式依赖安装：启动时只安装基础包，切换 RAG 模式时自动安装向量库依赖
- 添加 `pymupdf` 依赖用于 OCR PDF 处理
- `.gitignore` 多项修正（排除运行时数据文件夹、大模型权重文件、测试输出等）

---

## 1.6.0 - 2026-02-26

### 新功能

- **DS知识图谱左侧筛选面板** — 知识图谱模态框左侧新增章节/知识点/关系类型三维筛选面板，可按章节复选框筛选节点、关键词搜索知识点、勾选关系类型显隐边；筛选结果实时重渲染图谱，右上角节点/边数量同步更新
- **幻灯片 KG 自动提取** — DS 模式新增 PPTX/PDF 上传后自动触发 KG 提取的流程，与文本格式文档统一处理入口

### 修复

- **DS 模式章节列表初始化** — 修复进入「知识图谱」Tab 时章节/知识点列表显示 RAG 向量检索数据的问题（根因：Tab 点击固定调用 `loadRagDocs()`）；改为根据当前模式（`_aiMode`）分别调用 `loadDsDocs()` / `loadRagDocs()`
- **知识图谱 relColors 未定义** — 修复知识图谱渲染时 `ReferenceError: relColors is not defined` 导致图谱加载失败；将箭头 marker 判断中的 `relColors` 更正为 `_dsKgRelColors`
- **chNames 未定义** — 修复 `_renderDsKg()` 中 `chNames is not defined` 错误

---

## 1.5.0 - 2026-02-26

### 新功能

- **知识图谱标签页改名** — AI 智能出题标签页（第 7 个）由「AI智能出题」更名为「知识图谱」，与页面内容更匹配
- **知识图谱出题题型动态增删** — 出题配置区的题型与数量表格从静态 6 行改为可动态增删：每行有下拉选择题型、数量输入和删除按钮，表格下方有「+ 添加题型」按钮；题型变化时提示词编辑器中的格式示例区段随之联动（仅展示当前已选题型的格式示例）
- **提示词格式示例动态联动** — 三套提示词模板（中文/双语/英文）中原先固定的 6 种题型格式示例，改为按当前已选题型动态生成（`{format_examples}` 占位符），新增「简答>计算」格式和双语/英文多选格式，共 7 种题型格式示例
- **DS 模式知识提取断点续传** — 点击「提取」时支持两种模式：① 默认全新提取（清空重来）；② 「继续」恢复上次暂停处（`resume=true`，仅处理尚未提取的章节）；文档列表新增「继续」和重新提取（↺）两个独立按钮
- **DS 模式提取随时暂停** — 提取进行中，进度条右侧显示橙色「暂停」按钮；点击后在当前章节完成后优雅停止，已提取数据写入数据库；文档状态变为 `paused`，显示「已提取 X/Y 章 · N 个知识点」；暂停文档仍可参与出题
- **自动组卷题型拖拽排序** — 「一键自动组卷」配置区每个题型行左侧新增竖点手柄（`⋮⋮`），可拖动调整各题型在试卷中的排列顺序；拖过目标行时显示蓝色位置指示线，松手即完成排序

### 架构变更

- `app/rag_routes.py`：`ds_extract` 端点增加 `resume` 参数（跳过已提取章节）；`_worker` 在每章开始前检查 `pause_requested` 标志并优雅退出；新增 `POST /api/rag/ds-tasks/<task_id>/pause` 端点；`list_ds_docs` 返回新增字段 `ch_with_kps`（已提取 KP 的章节数）；`ds_docs.status` 新增 `'paused'` 状态值
- `app/templates/index.html`：新增 `RAG_TYPE_META` / `RAG_FORMAT_EXAMPLES` 常量（7 种题型 × 3 种语言的格式示例文本）；新增函数 `initRagTypeTable` / `addRagTypeRow` / `removeRagTypeRow` / `buildFormatExamples`；修改 `buildQuestionList()` 从动态表格 DOM 读取；修改 `setRagPromptMode()` 注入 `{format_examples}`；新增 `_currentDsTaskId` 状态变量和 `pauseDsExtract()` 函数；新增拖拽相关函数 `_examDragStart/Over/Leave/Drop/End` 及 `_bindDragEvents`

### 文档

- `CHANGELOG.zh.md` 新增 1.5.0 条目
- `README.md` 更新 DeepSeek 直出模式说明（断点续传/暂停）、自动组卷说明（拖拽排序）、DS 直出 API 表（新增 pause 端点）
- `技术文档.md` 更新 12.11 节（断点续传/暂停机制）

---

## 1.4.0 - 2026-02-26

### 新功能

- **DeepSeek 直出模式（DS Mode）** — AI 智能出题新增第二种出题模式，无需向量数据库和嵌入模型，纯靠 DeepSeek API 分两阶段完成：① 上传文档后逐章调用 DeepSeek 提取知识点（含定义/特征/分类/示例及知识点间关联关系），构建轻量级知识图谱；② 出题时将筛选后的知识图谱作为上下文调用 DeepSeek 生成题目
- **模式切换按钮** — AI 标签页顶部新增「DeepSeek 直出 / RAG 向量检索」切换，默认使用 DeepSeek 直出；切换到 RAG 模式时弹出说明弹窗，提示 GPU 显存要求（≥4GB）和所需安装的大型依赖（qdrant-client、sentence-transformers、BGE-large-zh 约1.3GB）
- **DS 文档知识提取面板** — 左侧新增独立面板，支持上传 `.md`/`.txt`/`.docx`/`.pptx`/`.ppt`/`.pdf`，文档解析章节后点击「提取」按钮异步调用 DeepSeek 逐章提取知识点，进度实时展示；提取完成后章节/知识点自动加载到右侧筛选区供三级联动
- **PDF / PPTX 支持** — DS 模式上传 `.pdf`/`.pptx` 时复用现有 PaddleOCR 异步 OCR 流程（每次发送 ≤10页切片），OCR 完成后自动解析章节结构并存入数据库，前端轮询进度；文本格式（`.md`/`.txt`/`.docx`）仍同步解析
- **提示词自适应** — `setRagPromptMode()` 感知当前模式：DS 模式下自动将 RAG 提示词的"检索到的参考内容"替换为"知识图谱信息"，无需维护两套完整模板

### 架构变更

- 新增独立数据库 `ds_knowledge.db`（项目根目录，运行时自动创建），含三张表：`ds_docs`（文档元信息）、`ds_chapters`（章节原文）、`ds_kps`（知识点及关联关系 JSON）
- `app/rag_routes.py` 新增 7 个 DS 模式端点：`POST /api/rag/ds-upload`、`POST /api/rag/ds-extract/<doc_id>`、`GET /api/rag/ds-tasks/<task_id>`、`GET /api/rag/ds-docs`、`GET /api/rag/ds-docs/<doc_id>/kps`、`DELETE /api/rag/ds-docs/<doc_id>`、`POST /api/rag/ds-generate`
- `app/rag_routes.py` 新增辅助函数：`_ds_db_path/conn/init`、`_parse_md_to_chapters`、`_parse_file_to_chapters`（支持 `.md`/`.txt`/`.docx`，PPTX/PDF 走 OCR 后再解析）
- 前端新增 JS 函数：`setAiMode`、`_applyAiMode`、`showRagWarning`、`closeRagWarning`、`loadDsDocs`、`renderDsDocList`、`renderDsDocCheckboxes`、`dsDeleteDoc`、`dsUploadFiles`、`pollDsUploadTask`、`dsExtract`、`pollDsTask`、`dsUpdateMeta`、`dsGenerate`、`_adaptPromptForDs`
- `ragGenerate()` 和 `updateRagMeta()` 新增模式分支，DS 模式分别调用 `dsGenerate()` / `dsUpdateMeta()`

### 文档

- `CHANGELOG.zh.md` 新增 1.4.0 条目
- `README.md` 更新功能特性、API 一览、项目结构、使用指南
- `技术文档.md` 新增 12.11 DeepSeek 直出模式章节（含架构概览、数据库设计、API 端点、OCR 机制、提示词设计、错误处理、参数速查表）
- `DS直出知识提取分析.md` 详细技术分析文档（728 行，完整描述 DS 直出模式实现细节）

---

## 1.3.0 - 2026-02-25

### 新功能

- **幻灯片 KG 自动提取** — PPTX/PDF 上传完成后，OCR 结束立即调用 DeepSeek 自动构建知识图谱：按标题页将幻灯片分组为"伪章节"，对每组提取概念与语义关系，存入与教材相同的 `chapters / concepts / relations` 表，知识图谱页完整展示"讲次 → 概念节点"层级
- **新增 `rag_pipeline/slides_kg.py`** — 幻灯片专属 KG 流程：`detect_topics()`（三级标题页判定 + 强制分组兜底）+ `build_kg_for_slides()`（DeepSeek API + 进度回调），约 200 行，与教材 KG 管道零重复
- **知识图谱三级联动筛选** — 左侧边栏新增可折叠的"章节筛选"和"知识点筛选"面板，文档/章节/知识点之间双向联动：切换文档时章节与知识点自动重置；选定章节后知识点列表自动过滤；知识点面板支持实时搜索框 + 全选/全不选

### Bug 修复

- **修复切换文档后仍显示旧文档概念的问题** — 后端为 `concept` 节点补充 `doc_id` 字段（通过 `chapters.doc_id` 直接获取），解决 `if (n.doc_id && ...)` 对 concept 节点永远为 false 的问题
- **修复幻灯片文档下误返全部概念** — 幻灯片无 chapter 节点（`totalCh=0`），原条件 `_selectedChapters.size >= 0` 恒为 true 导致返回所有概念；现先按 `doc_id` 过滤为 `docConcepts` 再做章节判断
- **修复删除文档时 KG 数据残留** — `DELETE /api/rag/docs/<doc_id>` 现同步调用 `db.delete_kg_by_doc()` 清理 chapters/concepts/relations

### 架构变更

- `rag_pipeline/db.py`：`chapters` 表新增 `doc_id TEXT DEFAULT ''` 列（向前兼容 `ALTER TABLE` 迁移）；`save_chapter()` 增加 `doc_id` 关键字参数；新增 `delete_kg_by_doc()` / `get_chapters_by_doc()`
- `rag_pipeline/prompts.py`：`kg_extraction_prompt()` 增加 `subject_hint` 参数（默认 `'农业经济学'`，幻灯片传文件名前缀）
- `rag_pipeline/kg_extractor.py`：`extract_kg_for_chapter()` 透传 `subject_hint`
- `app/rag_routes.py`：幻灯片 OCR 完成后自动串联 KG 提取，进度实时写入任务状态；删除端点联动调用 `delete_kg_by_doc()`；`ingest` 接受 `subject_hint` 表单字段
- `app/kg_routes.py`：概念 JOIN 带 `ch.doc_id`；幻灯片 KG 章节以 `kgch::` 前缀节点加入图且更新 `ch_name_to_nid`；概念连边兜底用概念自身 `doc_id`，不再硬取第一个文档

---

## 1.2.0 - 2026-02-25

### 新功能

- **AI 智能出题标签页（第 7 个标签）** — 将 RAG Pipeline 与 Flask 前端无缝集成，支持上传文档建立本地知识库，通过 DeepSeek API 自动生成符合系统导入格式的题目，一键导入题库
- 新增 `app/rag_routes.py` — RAG API Blueprint，6 个端点：`/api/rag/docs`、`/api/rag/docs/<id>/meta`、`/api/rag/docs/<id>`（DELETE）、`/api/rag/ingest`、`/api/rag/tasks/<id>`、`/api/rag/generate`
- 知识库摄入支持 5 种文件格式：`.md`/`.txt`/`.docx` 同步摄入，`.pptx`/`.pdf` 后台 OCR 异步摄入并轮询进度
- 出题前按文档、章节、知识点多维筛选检索范围，RAG 混合检索（稠密+BM25）自动构建上下文
- 内置三套完整提示词模板（中文/双语/英文），含 `{context}` 和 `{question_list}` 占位符，可在线编辑
- 新增 `pptx_ocr/pipeline.py::process_pdf()` — 直接处理 PDF，跳过 PPTX→PDF 转换步骤
- `app/rag_routes.py` 使用 `dotenv_values()` 直接读取 `.env` 文件，避免系统环境变量遮蔽正确的 API Key

### 架构变更

- `app/factory.py` 注册 `rag_bp` Blueprint
- 新增 `rag_uploads/` 目录（运行时自动创建），存放用户上传的知识库文档

### 文档

- `技术文档.md` 新增第 12 章 AI 智能出题模块
- `README.md` 更新功能列表、项目结构、API 一览、AI 辅助出题章节

---

## 1.1.0 - 2026-02-22

### 新功能

- 新增复习要点上传功能：在 AI 出题提示词卡片中上传 `.docx` 或 `.txt` 复习要点文档，系统自动将要点内容嵌入提示词，无需向 AI 另行上传 PPT/PDF 文件
- 新增 `POST /api/parse-review-notes` API 端点，支持解析 `.docx`（段落文本提取）和 `.txt` 文件
- 切换出题模式（纯中文 / 中英双语 / 纯英文）时，含复习要点的提示词自动同步更新
- 新增"清除要点"按钮，可一键还原为原始提示词

### 文档

- README 更新 AI 辅助出题章节，说明"上传 PPT/PDF"与"上传复习要点"两种使用方式
- README API 接口一览新增 `/api/parse-review-notes` 说明

---

## 1.0.1 - 2025-xx-xx

- 初始发布
