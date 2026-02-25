# 试题管理系统

基于 Flask + SQLAlchemy 的通用试题管理与自动组卷系统，支持题库增删改查、按科目分类管理、自动组卷、富文本内容（图片/表格）、Word 文档导入/导出、双语预览、AI 智能出题（RAG）、知识图谱可视化等功能。

## 功能特性

### 核心题库功能

- **富文本编辑** — 题目内容、参考答案、解析均支持 Quill 富文本编辑器，可插入图片、设置加粗/斜体/列表格式
- **图片支持** — 编辑时可直接上传图片，导入含图片的 `.docx` 文件时自动提取图片并嵌入内容；导出 Word 试卷时图片原样保留
- **表格支持** — 导入含表格的 `.docx` 文件时自动转换为 HTML 表格；导出时转换为 Word 表格
- **科目管理** — 题目支持关联考试科目，题库管理和组卷均可按科目筛选切换；导入时可指定科目
- **题库管理** — 支持单选、多选、是非、简答、计算、论述、材料分析等多种题型的增删改查
- **批量操作** — 多选题目后批量删除（自动清理试卷关联）或批量修改题型
- **题型管理** — 支持自定义题型（含层级题型如 `简答>计算`），内置题型不可删除
- **自动组卷** — 根据动态题型配置，从未使用的题目中自动抽取组成试卷，可指定组卷科目
- **使用追踪** — 仅在确认试卷时标记题目为已使用，防止跨年度重复出题；支持确认和撤销操作
- **使用管理** — 独立的使用管理标签页，按使用日期、题型筛选已使用题目，支持一键释放
- **题目替换** — 在试卷中替换同类型题目，支持按关键词、知识点、难度搜索候选题目
- **Word 导入** — 从 `.docx` 或 `.txt` 文件批量导入，支持双语内容、元数据解析、内嵌图片和表格；自动查重，重复题目跳过
- **Word 导出** — 将试卷导出为格式化的 `.docx` 文件，支持中文/英文/中英对照三种模式，可选含答案
- **双语支持** — 题目支持中英文并存，提供英文内容时自动标记为双语；试卷预览和导出均支持语言切换
- **元数据管理** — 每道题可设置知识点、标签（逗号分隔）、难度（easy/medium/hard）
- **课程设置** — 自定义课程名称、课程代号、考试形式等，导出试卷自动使用配置信息

### AI 智能出题（RAG）

- **本地向量知识库** — 上传 `.md`/`.txt`/`.docx`/`.pptx`/`.pdf` 文件，自动分块向量化，建立本地知识库
- **混合检索** — BGE-large-zh-v1.5 稠密向量 + BM25 稀疏检索，RRF 融合排序
- **OCR 支持** — `.pptx`/`.pdf` 异步后台调用 PaddleOCR Layout Parsing API 转换为 Markdown 后摄入
- **章节/知识点联动筛选** — 选定章节后，知识点列表自动过滤为仅展示该章节的节名；PPTX 分块展示每页首行内容而非 "Slide N"
- **DeepSeek 出题** — 检索上下文后调用 DeepSeek API 生成格式化题目
- **一键导入** — 生成结果直接导入题库，支持指定目标科目
- **API 配置界面** — 在页面内配置 PaddleOCR 服务地址、API Key 及 DeepSeek API Key，保存至 `.env` 文件，无需手动编辑

### 知识图谱可视化

- **独立可视化页面** (`/kg`) — D3.js 力导向图，展示文档→章节→节/页→概念的完整知识网络
- **幻灯片 KG 自动构建** — 上传 PPTX/PDF 后，OCR 完成即自动调用 DeepSeek 按讲次分组提取概念与语义关系，无需额外操作，幻灯片与教材在知识图谱页统一展示
- **双数据源** — 始终展示 chunks 结构层级；若运行过 KG 提取，叠加展示概念节点和语义关系边
- **语义关系边** — is_a（蓝）/ depends_on（红）/ leads_to（绿）/ contrasts_with（橙）四种关系类型，颜色区分
- **节点类型** — 文档（深蓝大圆）/ 章节（蓝）/ 节/页（青绿）/ 普通概念（紫）/ 重点概念（红）/ 难点概念（橙）
- **三级联动筛选** — 左侧边栏依次提供"文档筛选 → 章节筛选 → 知识点筛选"三个可折叠面板，层级联动：切换文档时章节与知识点自动重置；选定章节后知识点列表自动过滤；知识点面板内置搜索框
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
| 测试框架 | pytest（115 个用例） |
| 前端 | 原生 HTML/CSS/JS 单页应用 |
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
├── uploads/images/                 # 题目图片存储目录
├── exports/                        # 导出文件目录
├── rag_uploads/                    # 用户上传的知识库文档
├── app/
│   ├── factory.py                  # Flask 应用工厂（注册 3 个 Blueprint）
│   ├── db_models.py                # SQLAlchemy ORM 模型定义
│   ├── routes.py                   # 题库/试卷/题型等 API 路由
│   ├── rag_routes.py               # RAG 知识库 & 出题 API（8 个端点）
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

### AI 智能出题（RAG）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/rag/docs` | 列出知识库中所有文档 |
| `GET` | `/api/rag/docs/<doc_id>/meta` | 获取文档章节/节名（含 `display_name`、`chapter_name`） |
| `DELETE` | `/api/rag/docs/<doc_id>` | 删除文档 |
| `POST` | `/api/rag/ingest` | 上传并摄入文档（`.md`/`.txt`/`.docx` 同步；`.pptx`/`.pdf` 异步 OCR） |
| `GET` | `/api/rag/tasks/<task_id>` | 轮询 OCR 任务状态 |
| `POST` | `/api/rag/generate` | RAG 检索 → DeepSeek 出题 |
| `GET` | `/api/rag/config` | 读取 API 配置（PaddleOCR URL/Token、DeepSeek Key） |
| `PUT` | `/api/rag/config` | 保存 API 配置到 `.env` 文件 |

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

在"题库导入与模板下载"标签页的 **AI 出题提示词** 卡片中选择模式（中文/双语/英文），复制提示词后发给外部 AI（DeepSeek、豆包、千问等）。

- **有课件**：提示词 + PPT/PDF 一起发送
- **无课件**：点击"上传复习要点"→ 生成含要点的提示词 → 直接发送

AI 返回结果保存为 `.txt`（UTF-8）后通过导入功能上传。

### 方式二：AI 智能出题（内置 RAG）

**配置步骤：**

1. 打开"AI 智能出题"标签页，在左下角 **API 配置** 卡片中填入：
   - PaddleOCR 服务地址（如需处理 PPTX/PDF）
   - PaddleOCR API Key
   - DeepSeek API Key
2. 点击"保存"，配置写入项目根目录 `.env` 文件

**出题流程：**

1. **上传文档** — 拖拽上传课件或教材，`.pptx`/`.pdf` 后台 OCR 异步处理
2. **筛选范围** — 选择参考文档，勾选章节（知识点列表自动联动过滤）
3. **配置参数** — 设置题型数量、出题语言（中文/双语/英文）
4. **一键出题** — 系统自动检索知识库 → 构建上下文 → 调用 DeepSeek
5. **导入题库** — 点击"导入题库"，弹窗确认目标科目后自动导入

**知识图谱：** 点击"知识库管理"右上角 **"知识图谱"** 按钮，在新标签页打开交互式知识图谱可视化页面。

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

## 许可证

本项目为内部教学工具。
