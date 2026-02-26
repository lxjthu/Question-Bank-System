# 更新日志

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
