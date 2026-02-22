# 试题管理系统

基于 Flask + SQLAlchemy 的通用试题管理与自动组卷系统，支持题库增删改查、按科目分类管理、自动组卷、富文本内容（图片/表格）、Word 文档导入/导出（含重复检测）、双语预览、课程设置等功能。

## 功能特性

- **富文本编辑** — 题目内容、参考答案、解析均支持 Quill 富文本编辑器，可插入图片、设置加粗/斜体/列表格式
- **图片支持** — 编辑时可直接上传图片，导入含图片的 `.docx` 文件时自动提取图片并嵌入内容；导出 Word 试卷时图片原样保留
- **表格支持** — 导入含表格的 `.docx` 文件时自动转换为 HTML 表格；导出时转换为 Word 表格
- **科目管理** — 题目支持关联考试科目，题库管理和组卷均可按科目筛选切换；导入时必须指定科目
- **题库管理** — 支持单选、多选、是非、简答、计算、论述、材料分析等多种题型的增删改查
- **批量操作** — 多选题目后批量删除（自动清理试卷关联）或批量修改题型
- **题型管理** — 支持自定义题型（含层级题型如 `简答>计算`），内置题型不可删除
- **自动组卷** — 根据动态题型配置，从未使用的题目中自动抽取组成试卷，可指定组卷科目
- **使用追踪** — 仅在确认试卷时标记题目为已使用，防止跨年度重复出题；支持确认和撤销操作
- **使用管理** — 独立的使用管理标签页，按使用日期、题型筛选已使用题目，支持一键释放
- **题目替换** — 在试卷中替换同类型题目，支持按关键词、知识点、难度搜索候选题目
- **Word 导入** — 从 `.docx` 或 `.txt` 文件批量导入，支持双语内容、元数据解析、多段落题目、内嵌图片和表格；导入时自动查重，重复题目跳过并在结果中计数
- **Word 导出** — 将试卷导出为格式化的 `.docx` 文件，支持中文/英文/中英对照三种模式，可选含答案或仅题目；层级题型（`简答>材料分析`）在导出中只显示子类型名（`材料分析`）
- **动态模板生成** — 导入模板按需从内存生成（不依赖磁盘缓存文件），自动包含所有已注册题型的正确格式示例，含双语选项和元数据字段说明
- **双语支持** — 题目支持中英文并存，提供英文内容时自动标记为双语；试卷预览和导出均支持语言切换
- **元数据管理** — 每道题可设置知识点、标签（逗号分隔）、难度（简单/中等/困难）
- **搜索过滤** — 按科目、关键词、题型、语言、难度、知识点多维度搜索题目
- **课程设置** — 支持自定义课程名称、课程代号、考试形式等，导出试卷自动使用配置信息
- **AI 出题提示词** — 内置 `AI出题提示词.md`，提供纯中文、中英双语、纯英文三套提示词；支持上传复习要点文档（`.docx`/`.txt`），将要点内容自动嵌入提示词，无需向 AI 上传 PPT/PDF，直接发送即可出题
- **单页应用** — 前端为完整 SPA（六标签页：题库导入与模板下载、题库管理、试卷生成、题型管理、使用管理、系统设置）

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask 3.x + Blueprint |
| 数据库 | SQLite + Flask-SQLAlchemy |
| ORM 模型 | SQLAlchemy (QuestionModel, ExamModel, QuestionTypeModel, CourseSettingsModel, QuestionImageModel) |
| 文档处理 | python-docx |
| 富文本编辑器 | Quill.js 1.3.7（CDN） |
| 测试框架 | pytest（115 个用例） |
| 前端 | 原生 HTML/CSS/JS 单页应用 |

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
├── requirements.txt                # Python 依赖
├── 一键启动.bat                     # Windows 一键启动脚本
├── AI出题提示词.md                  # AI 自动出题提示词（纯中文/双语/纯英文三套）
├── exam_system.db                  # SQLite 数据库文件（运行后自动生成）
├── uploads/images/                 # 题目图片存储目录（运行后自动生成）
├── exports/                        # 导出文件存放目录（运行后自动生成）
├── app/
│   ├── factory.py                  # Flask 应用工厂，初始化 DB 和内置题型
│   ├── db_models.py                # SQLAlchemy ORM 模型定义
│   ├── routes.py                   # 所有 API 路由（Blueprint）
│   ├── utils.py                    # Word 模板生成、试卷导出、HTML↔Word 转换
│   ├── docx_importer.py            # .docx 富内容解析器（图片+表格+软换行）
│   └── templates/
│       └── index.html              # 前端 SPA 页面（含 Quill 编辑器）
└── tests/
    ├── conftest.py                 # pytest fixtures
    ├── test_models.py              # ORM 模型单元测试（13 个）
    ├── test_question_api.py        # 题库 API 测试（22 个）
    ├── test_exam_api.py            # 试卷 API 测试（20 个）
    ├── test_business_logic.py      # 业务逻辑测试（10 个）
    ├── test_edge_cases.py          # 边界情况测试（9 个）
    ├── test_question_types.py      # 题型管理 API 测试（10 个）
    ├── test_batch_delete.py        # 批量删除 API 测试（5 个）
    ├── test_usage_management.py    # 使用管理 API 测试（7 个）
    └── test_course_settings.py     # 课程设置 API 测试（11 个）
```

## API 接口一览

### 题目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/questions` | 获取题目列表（支持 `keyword`/`type`/`language`/`difficulty`/`knowledge_point`/`is_used`/`subject` 查询参数） |
| `POST` | `/api/questions` | 新增题目（支持双语字段、元数据、科目、HTML 富文本内容） |
| `GET` | `/api/questions/<id>` | 获取单个题目 |
| `PUT` | `/api/questions/<id>` | 更新题目 |
| `DELETE` | `/api/questions/<id>` | 删除题目（级联删除关联图片文件） |
| `GET` | `/api/questions/subjects` | 获取所有已有科目列表（去重） |
| `POST` | `/api/questions/import` | 从文件导入题目（multipart，含 `subject` 字段；自动查重跳过重复） |
| `GET` | `/api/questions/export` | 导出题库（支持 `format=json` 或 `format=csv`） |
| `POST` | `/api/questions/batch-delete` | 批量删除题目（自动清理试卷关联和图片文件） |
| `POST` | `/api/questions/batch-update-type` | 批量修改题目的题型 |
| `POST` | `/api/questions/batch-release` | 批量释放题目（标记为未使用） |

### 图片管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/images/upload` | 上传图片文件（multipart），返回 `{image_id, url}` |
| `GET` | `/api/images/<image_id>` | 获取图片文件（Quill 编辑器和导出时使用） |
| `DELETE` | `/api/images/<image_id>` | 删除图片文件及数据库记录 |

### 试卷管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/exams` | 获取所有试卷 |
| `POST` | `/api/exams` | 创建试卷 |
| `GET` | `/api/exams/<id>` | 获取单个试卷 |
| `PUT` | `/api/exams/<id>` | 更新试卷 |
| `DELETE` | `/api/exams/<id>` | 删除试卷 |
| `POST` | `/api/exams/generate` | 自动组卷（支持 `subject` 参数按科目筛选题源） |
| `POST` | `/api/exams/<id>/add_question` | 向试卷添加题目 |
| `DELETE` | `/api/exams/<id>/remove_question/<qid>` | 从试卷移除题目 |
| `POST` | `/api/exams/<id>/replace_question` | 替换试卷中的题目 |
| `POST` | `/api/exams/<id>/confirm` | 确认试卷（标记题目为已使用） |
| `POST` | `/api/exams/<id>/revert_confirmation` | 撤销确认 |
| `GET` | `/api/exams/<id>/export` | 导出试卷为 Word 文档（支持 `mode=zh\|en\|both` 和 `show_answer=0\|1`） |

### 题型管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/question-types` | 获取所有题型（含内置和自定义） |
| `POST` | `/api/question-types` | 创建自定义题型（支持层级格式如 `简答>案例`） |
| `PUT` | `/api/question-types/<id>` | 更新题型 |
| `DELETE` | `/api/question-types/<id>` | 删除自定义题型（内置题型不可删除） |

### 课程设置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/course-settings` | 获取课程设置 |
| `PUT` | `/api/course-settings` | 更新课程设置 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页（SPA 前端） |
| `GET` | `/api/templates/download` | 下载题库导入模板（动态生成，内存流直接下载） |
| `POST` | `/api/parse-review-notes` | 解析复习要点文档（multipart，含 `file` 字段；支持 `.docx`/`.txt`），返回纯文本内容供前端嵌入 AI 提示词 |

## 导入格式说明

### 纯中文题目

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

[多选][ABD]
以下属于长江流域城市的有？
[A]武汉
[B]南京
[C]广州
[D]重庆
<解析>
知识点:中国地理
难度:medium
</解析>

[是非][正确]
黄河是中国第二长河。
<解析>
知识点:中国地理
难度:easy
</解析>

[简答>材料分析]
材料：...（案例正文，支持多段落）...
问题：根据材料分析...
<参考答案>
...
</参考答案>
<解析>
知识点:农业家庭承包经营
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
武汉是湖北省省会城市
知识点:中国地理
标签:地理,省会
英文题目:What is the capital city of Hubei Province?
难度:easy
</解析>
```

### 含图片/表格的 `.docx` 文件

导入含图片和表格的 `.docx` 文件时，系统会自动：

- 提取内嵌图片，存储到 `uploads/images/`，并在题目内容中嵌入 `<img>` 引用
- 将 `<w:tbl>` 表格转换为 HTML `<table>`，在页面中正常渲染
- 导出试卷时，图片和表格均会还原到 Word 文档中

**格式要点：**

| 要点 | 说明 |
|------|------|
| 题型标识符 | 用半角方括号包围，如 `[单选]`、`[简答>材料分析]` |
| 选择题答案 | 紧跟题型后，单选 `[A]`，多选 `[ABD]` |
| 是非题答案 | 只能是 `[正确]` 或 `[错误]`，无需列选项 |
| 英文选项排列 | 先列全部中文选项 `[A][B][C][D]`，再统一列英文选项 `[A_en][B_en][C_en][D_en]` |
| `<解析>` 元数据 | `知识点:`、`标签:`、`英文题目:`、`难度:` 四个字段，冒号后直接跟内容 |
| 难度值 | 只能是 `easy`、`medium`、`hard`（英文小写） |
| 查重机制 | 导入时按题目内容自动去重，重复题目跳过并在返回结果中计数 |

## AI 辅助出题

`AI出题提示词.md` 提供三套可直接使用的提示词，均可在系统"题库导入与模板下载"标签页的 **AI 出题提示词** 卡片中选择和复制。

| 模式 | 适用场景 |
|------|---------|
| 纯中文出题 | 普通中文课程，生成纯中文题库 |
| 中英双语出题 | 双语课程，每题同时包含中英文版本 |
| 纯英文出题 | 全英文授课课程，题目和解析全部英文 |

### 两种使用方式

**方式一：上传 PPT/PDF（有课件）**

复制提示词 → 连同 PPT 或 PDF 文件一起发给支持文件上传的 AI（DeepSeek、豆包、千问等）→ AI 自动出题。

**方式二：上传复习要点（无课件）**

1. 在 AI 出题提示词卡片中点击"上传复习要点"，选择 `.docx` 或 `.txt` 格式的复习要点文件
2. 点击 **生成含复习要点的提示词**，系统自动将要点内容嵌入提示词
3. 复制生成的提示词直接发给 AI，无需再上传任何文件
4. 切换出题模式（中文/双语/英文）时，提示词自动同步更新

### 导入结果

AI 生成的题目内容保存为 `.txt` 文件（UTF-8 编码）后，通过"题库导入与模板下载"标签页直接上传导入。

## 许可证

本项目为内部教学工具。
