# 更新日志

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
