# 试题管理系统

基于 Flask + SQLAlchemy 的通用试题管理与自动组卷系统，支持题库增删改查、按科目分类管理、自动组卷、富文本内容（图片/表格）、Word 文档导入/导出、双语预览、AI 智能出题（RAG）、知识图谱可视化等功能。

## 功能特性

### 核心题库功能

- **富文本编辑** — 题目内容、参考答案、解析均支持 Quill 富文本编辑器，可插入图片、设置加粗/斜体/列表格式
- **图片支持** — 编辑时可直接上传图片，导入含图片的 `.docx` 文件时自动提取图片并嵌入内容；导出 Word 试卷时图片原样保留
- **表格支持** — 导入含表格的 `.docx` 文件时自动转换为 HTML 表格；导出时转换为 Word 表格
- **科目管理** — 题目支持关联考试科目，题库管理和组卷均可按科目筛选切换；导入时可指定科目
- **题库管理** — 支持单选、多选、是非、简答、计算、论述、材料分析等多种题型的增删改查
- **批量操作** — 多选题目后批量删除（自动清理试卷关联）、批量修改题型，或批量导出为 xlsx（`muban_zh.xlsx` 格式），导出时若字段超出 500 字符逐题提示截断或跳过；标签自动限制最多 3 个
- **题型管理** — 支持自定义题型（含层级题型如 `简答>计算`），内置题型不可删除
- **自动组卷** — 根据动态题型配置，从未使用的题目中自动抽取组成试卷，可指定组卷科目；题型行可拖动手柄（⋮⋮）自由调整顺序
- **试卷列表** — 生成的试卷自动保存到数据库，可通过"保存试卷"按钮刷新并展示已保存试卷列表；列表显示科目、题型概况、确认状态及确认时间；点击列表项可加载任意历史试卷；支持从列表直接删除试卷
- **最终确认锁定** — 点击"最终确认"后，试卷题目被锁定（不可编辑/替换/删除），并标记为已使用，防止跨年度重复出题；确认后按钮切换为"取消确认"；`ExamModel` 新增 `is_confirmed`、`confirmed_at`、`subject` 字段追踪确认状态
- **使用追踪** — 仅在最终确认时标记题目为已使用；支持取消确认（恢复未使用状态）
- **使用管理** — 独立的使用管理标签页，按使用日期、题型筛选已使用题目，支持一键释放
- **题目替换** — 在试卷中替换同类型题目，支持按关键词、知识点、难度搜索候选题目
- **导入** — 从 `.docx`、`.txt` 或 `.xlsx` 文件批量导入；xlsx 格式兼容本系统导出模板及外部题库（标题行自动检测），答案格式自动规范化；`.docx` 支持双语内容、内嵌图片和表格；所有格式均自动查重，重复题目跳过
- **Word 导出** — 将试卷导出为格式化的 `.docx` 文件，支持中文/英文/中英对照三种模式，可选含答案
- **双语支持** — 题目支持中英文并存，提供英文内容时自动标记为双语；试卷预览和导出均支持语言切换
- **元数据管理** — 每道题可设置知识点、标签（逗号分隔）、难度（easy/medium/hard）
- **课程设置** — 自定义课程名称、课程代号、考试形式等，导出试卷自动使用配置信息

### AI 智能出题（「知识图谱」标签页）

「知识图谱」标签页提供两种出题模式，可在顶部切换：

#### DeepSeek 直出模式（默认，无 GPU 要求）

- **两阶段知识图谱** — ① 上传文档后点击「提取」逐章（节）调用 DeepSeek，提取知识点（含定义/特征/分类/示例）及知识点间关联关系，写入本地 `ds_knowledge.db`；② 出题时将筛选后的知识图谱作为上下文再次调用 DeepSeek 生成题目
- **智能标题层级分析** — 上传时自动扫描文档所有标题（`#` / `##` / `###`），找出"出现≥2次的最高级别"作为章级别，并识别更深一级为节级别；知识点提取以**节**为最小单元（而非整章），内容更聚焦；若文档无子节则以章整体提取（自动降级）
- **断点续传** — 提取可随时暂停（进度条右侧「暂停」按钮），已提取部分持久化保存；文档列表显示「已提取 X/Y 章」；下次点击「继续」从断点恢复，无需重新提取
- **动态题型配置** — 出题配置区的题型与数量表格支持增删行和下拉切换题型；提示词编辑器中的格式示例随所选题型实时联动
- **知识点属性筛选** — 出题配置区可按教学属性（重点/难点/考点，可多选）、知识类型（事实性/概念性/程序性/元认知）、认知维度（记忆/理解/应用/分析/评价/创造）筛选知识点；筛选后知识点列表实时更新并展示彩色属性标签；筛选条件同步传递给后端 SQL 查询，确保 DeepSeek 仅使用符合条件的知识点出题
- **轻量部署** — 无需向量数据库和嵌入模型，仅依赖 DeepSeek API Key
- **格式全兼容** — 上传 `.md`/`.txt`/`.docx` 同步解析；`.pptx`/`.ppt`/`.pdf` 异步调用 PaddleOCR（每次发送 ≤10 页切片），OCR 完成后自动解析章节

#### RAG 向量检索模式（高精度，需 GPU）

- **本地向量知识库** — 上传文档后自动分块向量化，建立本地 Qdrant 知识库
- **混合检索** — BGE-large-zh-v1.5 稠密向量 + BM25 稀疏检索，RRF 融合排序
- **OCR 支持** — `.pptx`/`.pdf` 异步后台调用 PaddleOCR Layout Parsing API 转换为 Markdown 后摄入
- **章节/知识点联动筛选** — 选定章节后，知识点列表自动过滤；PPTX 展示每页首行内容
- **硬件要求** — 推荐 GPU 显存 ≥4 GB；首次使用需下载 BGE-large-zh 模型（约 1.3 GB）；需额外安装 `qdrant-client sentence-transformers`

#### 共同功能

- **DeepSeek 出题** — 两种模式均调用 DeepSeek API 生成格式化题目
- **多维度出题筛选** — 文档 → 章节 → 知识点逐级过滤；同时可按教学属性/知识类型/认知维度进一步筛选出题范围
- **一键导入** — 生成结果直接导入题库，支持指定目标科目
- **API 配置界面** — 页面内配置 PaddleOCR 和 DeepSeek API Key，保存至 `.env` 文件
- **提示词模板管理** — 「知识图谱」出题页与「题库导入」AI 提示词区均支持命名保存：点击「保存当前」输入名称即可；已保存模板显示在选择器"我的提示词"分组，随时切换；重名时提示覆盖或自动追加日期后缀（如 `我的提示词 2026-03-18`）；自定义模板可删除，默认模板（中文/双语/English）始终保留且不可删除；数据存储于浏览器 `localStorage`，刷新不丢失

### 知识图谱可视化

#### AI 智能出题内嵌图谱（DS 直出模式）

- **内嵌于 AI 智能出题标签页** — 点击文档旁「知识图谱」按钮，弹出 D3.js 力导向图，展示知识点节点与关联关系边
- **点击节点查看/编辑** — 单击任意知识点节点，右侧滑入**详情面板**（340 px），显示：知识点完整名称、所属章节、完整内容（不截断）、全部关联关系列表
- **在线编辑保存** — 面板内点击「编辑」进入编辑模式：名称可改、内容可改（textarea）、关联关系可增删改类型；点击「保存」调用 `PUT /api/rag/ds-kps/<id>` 写回数据库，图谱节点文字同步刷新；「取消」恢复原值
- **悬停快速预览** — 鼠标悬停仍显示小 tooltip（含名称/章节/内容摘要），tooltip 提示"点击查看完整详情"
- **切换保护** — 编辑未保存时切换节点或关闭面板弹出二次确认
- **ESC 行为** — 面板开启时 ESC 收起面板；面板已关闭时 ESC 关闭整个图谱弹窗
- **筛选** — 左侧面板支持章节筛选、关键词搜索、关系类型筛选
- **AI批量标注** — 左侧面板「AI批量标注」区一键调用 DeepSeek 批量写入 `knowledge_type`（知识类型）和 `cognitive_dimension`（认知维度）；可选开启 `teaching_focus`（重点/难点/考点）标注；支持查看/编辑提示词（系统提示词 + 用户提示词均可修改，「恢复默认」一键重置）；支持上传重难点列表文件（`.txt`/`.md`），**智能匹配模式**：系统自动解析文件结构、提取主题、通过三级关键词匹配直接标注命中知识点（无需 AI，即时完成），匹配结果实时显示；AI 批量标注可继续补充未匹配知识点的教学属性
- **Excel 导入回写** — 工具栏「导入 Excel」按钮（与「导出 Excel」并列）：选择修改后的 `.xlsx` 文件后，系统按知识点名称匹配，将表格中的教学属性（重难点/知识类型/认知维度）、关系、层级（最深支持五层）一次性回写数据库；空值保留原值，不删除知识点；L1 名称变更同步更新文档显示名；导入完成后自动刷新图谱

#### 独立知识图谱页面（RAG 向量模式）

- **独立可视化页面** (`/kg`) — D3.js 力导向图，展示文档→章节→节/页→概念的完整知识网络
- **双数据源** — 始终展示 chunks 结构层级；若运行过 KG 提取，叠加展示概念节点和语义关系边
- **语义关系边** — is_a（蓝）/ depends_on（红）/ leads_to（绿）/ contrasts_with（橙）四种关系类型，颜色区分
- **节点类型** — 文档（深蓝大圆）/ 章节（蓝）/ 节/页（青绿）/ 普通概念（紫）/ 重点概念（红）/ 难点概念（橙）
- **三级联动筛选** — 左侧边栏依次提供"文档筛选 → 章节筛选 → 知识点筛选"三个可折叠面板，层级联动
- **交互** — 单击选中节点，右侧面板显示定义、所属章节；点击"加载更多"分页查看对应知识原文
- **视图模式** — 支持结构+概念 / 仅文档结构 / 仅概念图谱三种视图切换
- **搜索** — 顶部搜索框实时高亮匹配节点，不匹配节点淡出

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask 3.x + Blueprint |
| 数据库 | SQLite + Flask-SQLAlchemy |
| ORM 模型 | SQLAlchemy (`QuestionModel`, `ExamModel`, `QuestionTypeModel`, `CourseSettingsModel`, `QuestionImageModel`) |
| 文档处理 | python-docx |
| 富文本编辑器 | Quill.js 1.3.7（CDN） |
| 可视化 | D3.js v7（CDN，力导向图） |
| 测试框架 | pytest（115 个用例，全部通过） |
| 前端 | 原生 HTML/CSS/JS 单页应用 |
| AI 出题（DS 直出） | DeepSeek API + SQLite（ds_knowledge.db，无嵌入模型）|
| AI 出题（RAG） | DeepSeek API + BGE-large-zh-v1.5 + Qdrant（本地）+ BM25（rank_bm25 + jieba）|
| OCR | PaddleOCR Layout Parsing API（PPTX/PDF → Markdown）|
| 配置管理 | python-dotenv（`.env` 文件读写）|

## 快速开始

### Windows 一键启动（推荐）

1. 解压 release 包
2. 双击 `一键启动.bat`

脚本会自动：创建 Python 虚拟环境 → 安装依赖（官方源失败时自动切换清华/阿里云镜像）→ 启动服务器 → 打开浏览器

> **前提**：系统已安装 Python 3.8+（[下载地址](https://www.python.org/downloads/)）

### 手动启动

```bash
# 安装依赖（国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple/）
pip install -r requirements.txt

# 启动服务器
python server.py
```

服务器默认运行在 `http://localhost:5000`（开发模式），端口可通过环境变量 `PORT` 配置。

### AI 智能出题依赖（按需安装）

RAG 向量检索需要额外依赖（首次使用会自动下载约 1.3 GB BGE 模型）：

```bash
pip install -r rag_pipeline/requirements_rag.txt
```

### 运行测试

```bash
python -m pytest tests/ -v
```

测试使用内存 SQLite 数据库，完全隔离，不影响开发/生产数据。

## 项目结构

```
试卷生成/
├── server.py                       # 应用入口
├── config.py                       # 配置类（开发/生产/测试）
├── requirements.txt                # Python 依赖（基础）
├── .env                            # API 密钥配置（不纳入 git）
├── 一键启动.bat                     # Windows 一键启动脚本
├── exam_system.db                  # SQLite 主数据库（运行后自动生成）
├── ds_knowledge.db                 # DS 直出模式知识图谱库（首次使用后自动生成）
├── uploads/images/                 # 题目图片存储目录
├── exports/                        # 导出文件目录
├── rag_uploads/                    # 用户上传的知识库文档
├── app/
│   ├── factory.py                  # Flask 应用工厂（注册 3 个 Blueprint）
│   ├── db_models.py                # SQLAlchemy ORM 模型定义
│   ├── routes.py                   # 题库/试卷/题型等 API 路由
│   ├── rag_routes.py               # RAG 知识库 & 出题 API（RAG 8 端点 + DS 直出 7 端点）
│   ├── kg_routes.py                # 知识图谱可视化 API（3 个端点）
│   ├── utils.py                    # Word 模板生成、试卷导出、HTML↔Word 转换
│   ├── docx_importer.py            # .docx 富内容解析器（图片+表格+软换行）
│   └── templates/
│       ├── index.html              # 主页 SPA（7 个标签页）
│       └── kg.html                 # 知识图谱可视化页面（D3.js）
├── rag_pipeline/                   # RAG 向量检索与出题 Pipeline
│   ├── config.py                   # 路径、模型名、检索参数配置
│   ├── chunker.py                  # 文档分块（教材章节 / 幻灯片页）
│   ├── embedder.py                 # BGE-large-zh-v1.5 向量嵌入
│   ├── vector_store.py             # Qdrant 本地向量库
│   ├── bm25_index.py               # BM25 稀疏索引
│   ├── retriever.py                # 混合检索 → RRF → 上下文扩展
│   ├── ingest.py                   # 摄入流水线（写 Qdrant + SQLite）
│   ├── db.py                       # kg.db SQLite（KG 表 + chunks 表）
│   ├── kg_extractor.py             # DeepSeek KG 提取（概念+关系）
│   ├── slides_kg.py                # 幻灯片 KG 流程（主题分组 + DeepSeek 提取）
│   ├── question_generator.py       # 基于 KG 的题目生成
│   └── kg.db / qdrant_storage/ / bm25_index/  # 运行时生成
├── pptx_ocr/                       # PPTX/PDF → Markdown OCR 模块
│   ├── config.py                   # 从 .env 读取 PaddleOCR URL/Token
│   ├── pipeline.py                 # process_pptx() + process_pdf()（支持运行时传参）
│   ├── api_client.py               # Layout Parsing API 客户端
│   ├── pdf_splitter.py             # PDF 分块工具
│   └── converter.py                # PPTX → PDF 转换
└── tests/
    ├── conftest.py                 # pytest fixtures
    ├── test_models.py              # ORM 模型测试（13）
    ├── test_question_api.py        # 题库 API 测试（22）
    ├── test_exam_api.py            # 试卷 API 测试（20）
    ├── test_business_logic.py      # 业务逻辑测试（10）
    ├── test_edge_cases.py          # 边界情况测试（9）
    ├── test_question_types.py      # 题型管理测试（10）
    ├── test_batch_delete.py        # 批量删除测试（5）
    ├── test_usage_management.py    # 使用管理测试（7）
    └── test_course_settings.py     # 课程设置测试（11）
```

## API 接口一览

### 题目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/questions` | 获取题目列表（支持 `keyword`/`type`/`language`/`difficulty`/`knowledge_point`/`is_used`/`subject` 查询参数） |
| `POST` | `/api/questions` | 新增题目（支持双语字段、元数据、科目、HTML 富文本） |
| `GET` | `/api/questions/<id>` | 获取单个题目 |
| `PUT` | `/api/questions/<id>` | 更新题目 |
| `DELETE` | `/api/questions/<id>` | 删除题目（级联删除关联图片） |
| `GET` | `/api/questions/subjects` | 获取所有已有科目列表 |
| `POST` | `/api/questions/import` | 从文件导入（multipart，支持 `subject` 字段；自动查重） |
| `GET` | `/api/questions/export` | 导出题库（`format=json` 或 `format=csv`） |
| `POST` | `/api/questions/batch-delete` | 批量删除 |
| `POST` | `/api/questions/batch-update-type` | 批量修改题型 |
| `POST` | `/api/questions/batch-release` | 批量释放（标记为未使用） |

### 试卷管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/exams` | 获取列表 / 创建试卷 |
| `GET/PUT/DELETE` | `/api/exams/<id>` | 单个试卷 CRUD |
| `POST` | `/api/exams/generate` | 自动组卷（支持 `subject` 参数） |
| `POST` | `/api/exams/<id>/add_question` | 向试卷添加题目 |
| `DELETE` | `/api/exams/<id>/remove_question/<qid>` | 从试卷移除题目 |
| `POST` | `/api/exams/<id>/replace_question` | 替换试卷中的题目 |
| `POST` | `/api/exams/<id>/confirm` | 确认试卷（标记题目为已使用） |
| `POST` | `/api/exams/<id>/revert_confirmation` | 撤销确认 |
| `GET` | `/api/exams/<id>/export` | 导出试卷为 Word（`mode=zh\|en\|both`，`show_answer=0\|1`） |

### 题型 / 课程设置 / 模板

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/question-types` | 获取全部题型 / 创建自定义题型 |
| `PUT/DELETE` | `/api/question-types/<id>` | 更新 / 删除题型（内置不可删） |
| `GET/PUT` | `/api/course-settings` | 获取 / 更新课程设置 |
| `GET` | `/api/templates/download` | 下载导入模板（内存动态生成） |
| `POST` | `/api/parse-review-notes` | 解析复习要点文档，返回纯文本 |
| `POST/GET` | `/api/images/upload` / `/api/images/<id>` | 图片上传 / 获取 |

### AI 智能出题 — RAG 向量检索模式

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/rag/docs` | 列出知识库中所有文档 |
| `GET` | `/api/rag/docs/<doc_id>/meta` | 获取文档章节/节名（含 `display_name`、`chapter_name`） |
| `DELETE` | `/api/rag/docs/<doc_id>` | 删除文档（同步清理向量库和 KG 数据） |
| `POST` | `/api/rag/ingest` | 上传并摄入文档（`.md`/`.txt`/`.docx` 同步；`.pptx`/`.pdf` 异步 OCR）|
| `GET` | `/api/rag/tasks/<task_id>` | 轮询 OCR / KG 提取任务状态 |
| `POST` | `/api/rag/generate` | RAG 混合检索 → DeepSeek 出题 |
| `GET` | `/api/rag/config` | 读取 API 配置（PaddleOCR URL/Token、DeepSeek Key） |
| `PUT` | `/api/rag/config` | 保存 API 配置到 `.env` 文件 |

### AI 智能出题 — DeepSeek 直出模式

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/rag/ds-upload` | 上传文档并解析章/节结构（`.md`/`.txt`/`.docx` 同步；`.pptx`/`.pdf` 异步 OCR 后解析） |
| `POST` | `/api/rag/ds-extract/<doc_id>` | 启动异步提取（`resume=true` 跳过已提取章节，实现断点续传） |
| `GET` | `/api/rag/ds-tasks/<task_id>` | 轮询 OCR 或知识点提取任务状态（含 `progress`/`total_chapters`） |
| `POST` | `/api/rag/ds-tasks/<task_id>/pause` | 请求暂停正在进行的提取任务（当前章节完成后生效） |
| `GET` | `/api/rag/ds-docs` | 列出所有 DS 文档（含状态、章节数、知识点数） |
| `GET` | `/api/rag/ds-docs/<doc_id>/kps` | 获取文档的章节列表和知识点列表 |
| `DELETE` | `/api/rag/ds-docs/<doc_id>` | 删除 DS 文档及其章节和知识点数据 |
| `GET` | `/api/rag/ds-kps/<kp_id>` | 获取单个知识点完整信息（name/content/relations） |
| `PUT` | `/api/rag/ds-kps/<kp_id>` | 更新单个知识点（name/content/relations），kp_id 不存在返回 404 |
| `POST` | `/api/rag/ds-match-focus` | 解析重难点主题列表，关键词匹配知识点并批量写入 teaching_focus（v1.17.0） |
| `GET` | `/api/rag/ds-graph` | 获取知识图谱节点 + 边数据（D3 可视化） |
| `POST` | `/api/rag/ds-generate` | 基于 DS 知识图谱 → DeepSeek 出题 |

### 知识图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/kg` | 知识图谱可视化页面 |
| `GET` | `/api/kg/graph` | 图谱节点 + 边数据（D3.js 格式，支持 `doc_id` 过滤） |
| `GET` | `/api/kg/chunks` | 指定节点的原文 chunk 列表（支持分页） |

## 导入格式说明

### 纯中文题目示例

```
[单选][D]
湖北省的省会城市是（）？
[A]长沙
[B]宜昌
[C]荆州
[D]武汉
<解析>
武汉是湖北省省会城市
知识点:中国地理
标签:地理,省会
难度:easy
</解析>

[是非][正确]
黄河是中国第二长河。
<解析>
知识点:中国地理
难度:easy
</解析>

[简答>材料分析]
【材料】...案例内容...
【问题】根据材料分析...？
<参考答案>
...
</参考答案>
<解析>
知识点:某知识点
难度:medium
</解析>
```

### 双语题目（中英并存）

```
[单选][D]
湖北省的省会城市是（）？
[A]长沙
[B]宜昌
[C]荆州
[D]武汉
[A_en]Changsha
[B_en]Yichang
[C_en]Jingzhou
[D_en]Wuhan
<解析>
知识点:中国地理
英文题目:What is the capital city of Hubei Province?
难度:easy
</解析>
```

### 格式要点

| 要点 | 说明 |
|------|------|
| 括号类型 | 必须用半角 `[]`、`<>`，不能用全角 `【】`、`（）` |
| 题型标识 | `[单选]`、`[多选]`、`[是非]`、`[简答]`、`[简答>论述]`、`[简答>材料分析]` |
| 选择题答案 | 紧跟题型后，单选 `[A]`，多选 `[ABD]`，大写字母 |
| 是非题答案 | `[正确]` 或 `[错误]`，不可替代 |
| 难度值 | 只能是 `easy`、`medium`、`hard`（全小写英文） |
| 查重 | 按题目内容自动去重，重复跳过并在响应中计入 `skipped` |

## AI 智能出题使用指南

### 方式一：提示词复制（外部 AI，无需配置）

在"题库导入与模板下载"标签页的 **AI 出题提示词** 卡片中选择或编辑提示词，复制后发给外部 AI（DeepSeek、豆包、千问等）。

- **有课件**：提示词 + PPT/PDF 一起发送
- **无课件**：点击"上传复习要点"→ 生成含要点的提示词 → 直接发送
- **自定义并保存**：直接在文本框中修改提示词，点击「保存当前」命名保存，下次可从选择器直接切换

AI 返回结果保存为 `.txt`（UTF-8）后通过导入功能上传。

### 方式二：AI 智能出题（内置，推荐 DeepSeek 直出模式）

**配置步骤：**

1. 打开"知识图谱"标签页，在左下角 **API 配置** 卡片中填入：
   - DeepSeek API Key（两种模式均需要）
   - PaddleOCR 服务地址 + API Key（仅上传 PPTX/PDF 时需要）
2. 点击"保存"，配置写入项目根目录 `.env` 文件

#### DeepSeek 直出模式（默认）

无需 GPU，无需安装向量库依赖。

1. **上传文档** — 在左侧「文档知识提取」面板拖拽上传教材（支持 `.md`/`.txt`/`.docx`/`.pptx`/`.pdf`），PPTX/PDF 自动异步 OCR（每批 ≤10 页）
2. **提取知识点** — 上传完成后点击文档旁的「提取」按钮，DeepSeek 逐章提取知识点及关联关系，进度实时展示；提取中可随时点击「暂停」，已完成的章节已保存；下次点击「继续」从断点恢复
3. **筛选范围** — 右侧「出题配置」中勾选参考文档（暂停中文档也可参与出题），章节和知识点列表自动联动加载，可进一步筛选
4. **配置参数** — 设置题型数量（支持增删行）、出题语言（中文/双语/英文）；提示词编辑器中的格式示例随题型选择自动更新；可直接编辑提示词并点击「保存当前」命名保存，通过选择器随时切换默认或已保存模板
5. **一键出题** — 点击「一键出题」，系统将筛选后的知识图谱作为上下文调用 DeepSeek 生成题目
6. **导入题库** — 点击"导入题库"，确认目标科目后自动导入

#### RAG 向量检索模式

需要 GPU（推荐显存 ≥4 GB）。切换时页面会提示所需安装：

```bash
pip install qdrant-client sentence-transformers
```

1. **上传文档** — 切换到 RAG 模式后，在「知识库管理」面板上传文档，PPTX/PDF 后台 OCR 后自动摄入向量库
2. **筛选范围** — 选择文档和章节，知识点列表自动联动
3. **一键出题** — 系统混合检索知识库（稠密+BM25）→ 构建上下文 → 调用 DeepSeek

**知识图谱：** 点击「知识库管理」右上角 **"知识图谱"** 按钮，在新标签页打开交互式知识图谱可视化页面（RAG 模式专属）。

## .env 配置说明

项目根目录的 `.env` 文件（不纳入 git）存储敏感配置：

```env
# DeepSeek API（AI 出题必需）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# PaddleOCR Layout Parsing（处理 PPTX/PDF 必需）
PADDLEOCR_API_URL=https://your-paddleocr-service/layout-parsing
PADDLEOCR_TOKEN=your_token_here
PADDLEOCR_TIMEOUT=120
```

> 也可以直接在 AI 智能出题标签页的 API 配置卡片中填写，无需手动编辑文件。

## 计划功能（Roadmap）

以下功能已完成详细规划（见 `plans/` 目录），待实施：

| 功能 | 规划文档 | 核心变更 |
|------|----------|----------|
| **知识图谱内联编辑** — 在章节/知识点列表直接点击 ✎ 修改名称，Enter 确认，Esc 取消；章节名级联更新所有知识点 | `plan_feature1_kg_edit.md` | 新增 `PUT /api/rag/ds-chapters`；`ds_doc_kps` 返回 `doc_id`；`PUT /api/rag/ds-kps/<id>` 改为部分更新 |
| **题库导入时间字段** — `questions` 表新增 `imported_at`，记录批量导入批次；题库搜索支持按导入时间范围筛选；便于批量撤销误导入 | `plan_feature2_import_datetime.md` | `QuestionModel` 新增 `imported_at`；`GET /api/questions` 新增时间范围参数；导入时写入时间戳 |
| **一键出题高级筛选** — 组卷配置页新增「高级筛选」折叠区：难度/知识点关键词/标签 chip 多选/题目状态；实时预估可用题目数量 | `plan_feature3_exam_filter.md` | `POST /api/exams/generate` 扩展筛选参数；新增 `GET /api/questions/count` 预估接口 |

## 许可证

本项目为内部教学工具。
