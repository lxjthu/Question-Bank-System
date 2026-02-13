# 林业经济学（双语）试题管理系统

基于 Flask + SQLAlchemy 的双语试题管理与自动组卷系统，支持题库增删改查、自动组卷、Word 文档导入/导出、双语预览等功能。

## 功能特性

- **题库管理** — 支持单选、多选、是非、简答、计算、论述、材料等多种题型的增删改查
- **批量操作** — 多选题目后批量删除（自动清理试卷关联）或批量修改题型
- **题型管理** — 支持自定义题型的添加、编辑、删除，内置题型不可删除
- **自动组卷** — 根据动态题型配置，从未使用的题目中自动抽取组成试卷
- **动态组卷配置** — 组卷页题型配置行可动态增删，不再硬编码题型
- **使用追踪** — 仅在确认试卷时标记题目为已使用，防止跨年度重复出题；支持确认和撤销操作
- **使用管理** — 独立的使用管理标签页，支持按使用日期、题型筛选已使用题目，一键释放（标记为未使用）
- **题目替换** — 在试卷中替换同类型题目，支持按关键词、知识点、难度搜索候选题目
- **Word 导入** — 从 `.docx` 或 `.txt` 文件批量导入题目，支持双语内容和元数据解析
- **Word 导出** — 将试卷导出为格式化的 `.docx` 文件，支持中文/英文/中英对照三种模式，可选含答案或仅题目
- **动态模板生成** — 导入模板自动包含所有已注册题型（含自定义题型）的格式示例，含双语和元数据格式说明
- **双语支持** — 题目支持中文题目和英文题目并存，提供英文内容时自动标记为双语；试卷预览和导出均支持语言切换
- **元数据管理** — 每道题可设置知识点、标签（逗号分隔）、难度（简单/中等/困难）
- **搜索过滤** — 按关键词、题型、语言、难度、知识点多维度搜索题目
- **单页应用** — 前端为完整 SPA（五标签页：题库管理、试卷生成、模板下载、题型管理、使用管理），通过 REST API 与后端通信

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask 3.x + Blueprint |
| 数据库 | SQLite + Flask-SQLAlchemy |
| ORM 模型 | SQLAlchemy (QuestionModel, ExamModel, QuestionTypeModel) |
| 文档处理 | python-docx |
| 测试框架 | pytest (104 个用例) |
| 前端 | 原生 HTML/CSS/JS 单页应用 |

## 快速开始

### 1. 安装依赖

```bash
pip install flask flask-sqlalchemy python-docx pytest
```

### 2. 启动服务器

```bash
python server.py
```

服务器默认运行在 `http://localhost:5000`（开发模式），端口可通过环境变量 `PORT` 配置。

### 3. 数据迁移（从旧版 JSON 迁移）

如果有旧版 `question_bank.json` 数据文件，运行迁移脚本将数据导入 SQLite：

```bash
python migrate_json_to_db.py
```

脚本会自动处理重复 ID 的去重问题。

### 4. 运行测试

```bash
python -m pytest tests/ -v
```

测试使用内存 SQLite 数据库，完全隔离，不影响开发/生产数据。

## 项目结构

```
试卷生成/
├── server.py                  # 应用入口
├── config.py                  # 配置类（开发/生产/测试）
├── migrate_json_to_db.py      # JSON → SQLite 数据迁移脚本
├── exam_system.db             # SQLite 数据库文件（运行后自动生成）
├── question_bank.json         # 旧版 JSON 数据文件（迁移源）
├── app/
│   ├── __init__.py
│   ├── factory.py             # Flask 应用工厂
│   ├── db_models.py           # SQLAlchemy ORM 模型定义（QuestionModel, ExamModel, QuestionTypeModel）
│   ├── models.py              # 旧版数据类（Question/Exam，保留供参考）
│   ├── routes.py              # 所有 API 路由（Blueprint）
│   ├── utils.py               # Word 模板生成、试卷导出、文件解析
│   └── templates/
│       └── index.html         # 前端 SPA 页面
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # pytest fixtures 和测试辅助函数
│   ├── test_models.py         # ORM 模型单元测试（13 个）
│   ├── test_question_api.py   # 题库 API 测试（22 个）
│   ├── test_exam_api.py       # 试卷 API 测试（20 个）
│   ├── test_business_logic.py # 业务逻辑测试（10 个）
│   ├── test_edge_cases.py     # 边界情况测试（9 个）
│   ├── test_question_types.py # 题型管理 API 测试（10 个）
│   ├── test_batch_delete.py   # 批量删除 API 测试（5 个）
│   └── test_usage_management.py # 使用管理 API 测试（7 个）
├── exports/                   # 导出文件存放目录
├── temp/                      # 临时文件目录
└── uploads/                   # 上传文件目录
```

## API 接口一览

### 题目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/questions` | 获取题目列表（支持 `keyword`/`type`/`language`/`difficulty`/`knowledge_point`/`is_used` 查询参数） |
| `POST` | `/api/questions` | 新增题目（支持双语字段和元数据） |
| `GET` | `/api/questions/<id>` | 获取单个题目 |
| `PUT` | `/api/questions/<id>` | 更新题目 |
| `DELETE` | `/api/questions/<id>` | 删除题目 |
| `POST` | `/api/questions/import` | 从文件导入题目（multipart/form-data，支持双语和元数据） |
| `GET` | `/api/questions/export` | 导出题库（支持 `format=json` 或 `format=csv`） |
| `POST` | `/api/questions/batch-delete` | 批量删除题目（自动清理试卷关联） |
| `POST` | `/api/questions/batch-update-type` | 批量修改题目的题型 |
| `POST` | `/api/questions/batch-release` | 批量释放题目（标记为未使用） |

### 试卷管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/exams` | 获取所有试卷 |
| `POST` | `/api/exams` | 创建试卷 |
| `GET` | `/api/exams/<id>` | 获取单个试卷 |
| `PUT` | `/api/exams/<id>` | 更新试卷 |
| `DELETE` | `/api/exams/<id>` | 删除试卷 |
| `POST` | `/api/exams/generate` | 自动组卷 |
| `POST` | `/api/exams/<id>/add_question` | 向试卷添加题目 |
| `DELETE` | `/api/exams/<id>/remove_question/<qid>` | 从试卷移除题目 |
| `POST` | `/api/exams/<id>/replace_question` | 替换试卷中的题目 |
| `POST` | `/api/exams/<id>/confirm` | 确认试卷（标记题目为已使用） |
| `POST` | `/api/exams/<id>/revert_confirmation` | 撤销确认 |
| `GET` | `/api/exams/<id>/export` | 导出试卷为 Word 文档（支持 `mode=zh\|en\|both` 和 `show_answer=0\|1` 参数） |

### 题型管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/question-types` | 获取所有题型（含内置和自定义） |
| `POST` | `/api/question-types` | 创建自定义题型 |
| `PUT` | `/api/question-types/<id>` | 更新题型 |
| `DELETE` | `/api/question-types/<id>` | 删除自定义题型（内置题型不可删除） |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页（SPA 前端） |
| `GET` | `/api/templates/download` | 下载题库导入模板（动态包含所有题型） |

## 配置说明

通过 `config.py` 管理多环境配置：

| 配置项 | 开发环境 | 测试环境 | 生产环境 |
|--------|---------|---------|---------|
| `DEBUG` | `True` | - | `False` |
| `TESTING` | - | `True` | - |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///exam_system.db` | `sqlite://`（内存） | `sqlite:///exam_system.db` |
| `MAX_CONTENT_LENGTH` | 16 MB | 16 MB | 16 MB |

数据库 URI 可通过环境变量 `DATABASE_URL` 覆盖。

## 题目导入模板格式

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

[简答]
你对今天这节课有什么评价？
<参考答案>
课程非常的生动
</参考答案>
<解析>
知识点:课程反馈
难度:easy
</解析>
```

**模板格式要点：**
- 英文选项使用 `[A_en]`、`[B_en]` 等标记，紧跟中文选项之后
- 解析区段内可包含元数据行：`知识点:xxx`、`标签:xxx`、`英文题目:xxx`、`难度:easy|medium|hard`
- 参考答案使用 `<参考答案>...</参考答案>` 包围（注意闭合标签用 `</参考答案>`）
- 详细格式说明请下载模板文件：`GET /api/templates/download`

## 许可证

本项目为内部教学工具，仅供林业经济学课程使用。
