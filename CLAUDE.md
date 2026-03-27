# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

将单用户桌面版试卷生成系统改造为支持约 200 人的线上多用户版本。核心特性：邀请制注册（普通用户可无码自注册）、用户隔离题库、团队共享、Fernet 加密存储 API Key、Gunicorn + Nginx 生产部署。

## 常用命令

```bash
# 开发启动
python server.py

# 生产启动（Gunicorn）
gunicorn -w 5 wsgi:app

# 运行全部测试
pytest tests/

# 运行单个测试文件
pytest tests/test_isolation.py

# 运行单个测试函数
pytest tests/test_isolation.py::test_function_name -v

# 环境初始化（复制 .env.example 为 .env 并填写）
cp .env.example .env
```

## 环境变量（.env）

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | Flask Session 加密密钥，必须修改 |
| `ADMIN_PASSWORD` | 管理员初始密码，默认 `admin123` |
| `FERNET_KEY` | API Key 加密密钥（留空则从 SECRET_KEY 派生） |
| `FLASK_ENV` | `production` / `development` |
| `EXAM_DATA_DIR` | 数据根目录，不设则为项目根目录 |

## 架构概览

### 应用工厂 (`app/factory.py`)

`create_app(config_name)` 是唯一入口：
1. 加载 `config.py` 中对应配置类
2. 创建上传/临时/导出目录
3. `db.init_app` + `db.create_all`
4. 执行 `_migrate_db()`（`ALTER TABLE ADD COLUMN` 幂等迁移）
5. 注册所有 Blueprint（rag/kg/interview 注册时捕获异常，允许缺依赖）
6. 初始化 admin / guest 系统账号

### Blueprint 路由结构

| Blueprint | 前缀 | 文件 | 说明 |
|-----------|------|------|------|
| `main` | `/api/` | `routes.py` | 题目、试卷、导入导出、图片 |
| `auth` | `/api/auth/` | `auth_routes.py` | 登录、注册、API Key 管理、admin 用户管理 |
| `team` | `/api/teams/` | `team_routes.py` | 团队 CRUD、成员管理 |
| `rag` | `/api/rag/` | `rag_routes.py` | AI 出题（DeepSeek 直出模式，文档上传/知识点提取） |
| `kg` | `/api/kg/` | `kg_routes.py` | 知识图谱可视化 |
| `interview` | `/api/interview/` | `interview_routes.py` | 面试题库池、套题配置、抽题 |

### 数据库模型 (`app/db_models.py`)

核心关系：
- `User` ←(1:N)→ `QuestionModel` / `ExamModel`（通过 `owner_id`）
- `User` ←(M:N)→ `Team`（通过 `TeamMember`）
- `ExamModel` ←(M:N)→ `QuestionModel`（通过 `exam_questions` 关联表，含 `position`）
- `QuestionModel.options` / `ExamModel.config`：JSON 序列化为 Text 列

**数据可见性**（`visibility` 字段）：
- `private`：仅 owner 可见（**所有新建/导入题目强制为此值，前端不再暴露选择**）
- `team`：team 成员可见（配合 `team_id`，保留字段但前端已禁止用户设置）
- `guest_preview`：游客也可见（同上，仅历史数据可能存在）

**API Key 加密**：`User.set_api_key()` / `User.get_api_key()` 使用 Fernet 对称加密，密钥来自 `FERNET_KEY` 环境变量。

### 数据库迁移策略

无 Alembic，使用 `factory._migrate_db()` 手动执行幂等 `ALTER TABLE ADD COLUMN`。新增列时在 `new_cols` 列表中追加 `(表名, 列名, 类型定义)` 三元组；新增表在 `new_tables` 列表中追加 DDL 字符串。

### 认证与权限

- 认证：Flask Session（`session['user_id']`），保持 7 天
- 装饰器：`@login_required`（需登录）、`@admin_required`（需 admin）、`@guest_readonly`（游客只读）、`@ai_required`（需 vip 或 admin）
- `get_current_user()` → 返回当前 User 对象
- 可见性过滤：`_visible_q_filter(user)` / `_visible_e_filter(user)` 返回 SQLAlchemy OR 条件

### 用户角色与权限矩阵

| 功能 | guest | user | vip | admin |
|------|-------|------|-----|-------|
| 浏览题库/试卷 | ✓（guest_preview） | ✓（自己） | ✓（自己） | ✓（全部） |
| 增删改题目/试卷 | ✗ | ✓ | ✓ | ✓ |
| 题型管理 | ✗ | ✓（自定义） | ✓（自定义） | ✓（全部） |
| 设置 API Key | ✗ | ✗ | ✓ | ✓ |
| 文档上传（知识图谱） | ✗ | ✗ | ✓ | ✓ |
| AI 知识点提取/出题 | ✗ | ✗ | ✓ | ✓ |
| 系统 API Key 配置 | ✗ | ✗ | ✗ | ✓ |
| 用户管理/邀请码 | ✗ | ✗ | ✗ | ✓ |

### 测试架构 (`tests/`)

- 使用内存 SQLite（`TestingConfig.SQLALCHEMY_DATABASE_URI = 'sqlite://'`），每个测试函数完全隔离
- `conftest.py` 提供 `app`, `client`, `db`, `admin_user`, `user_a`, `user_b`, `guest_user` fixtures
- 辅助函数：`login()`, `login_as()`, `guest_login()`, `make_question()`, `make_exam()`

### 生产部署

- `wsgi.py`：Gunicorn 入口，`create_app('production')`
- `nginx.conf`：反向代理配置
- `deploy.sh`：部署脚本
- `exam-system-online.service`：systemd 服务文件

## 关键约定

- `interview_routes.py` 中直接使用 `db.engine` + raw SQL（未使用 SQLAlchemy ORM），参数用 `dict(enumerate(params, 1))` 传递
- `rag_routes.py` 单独维护自己的 SQLite 文件（`ds_knowledge.db`，路径由 `EXAM_DATA_DIR` 决定），用于文档和知识点存储，不走主 ORM；`json` 模块在该文件中别名为 `_json_mod`
- 题目语言由 `_detect_language(content, content_en)` 自动判断：无中文→`en`，有中文+content_en→`both`，有中文无content_en→`zh`
- 图片文件存储在 `uploads/images/`，元数据在 `QuestionImageModel`，通过 `/api/images/<image_id>` 访问
- 题型去重/名称冲突在应用层检查（`routes.py`），不依赖数据库唯一约束（历史原因：SQLite 不支持在线 DROP CONSTRAINT）

## 注册流程

`POST /api/auth/register`：
- 无邀请码 → 注册为 `user`（普通用户，不开通 AI）
- 有邀请码 → 注册为 `vip`（开通 AI 功能）
- 已注册的普通用户可通过 `POST /api/auth/upgrade` + 邀请码升级为 `vip`
- 邀请码申请邮箱：`langxiaojuan@zuel.edu.cn`

## 题型管理隔离

`QuestionTypeModel` 含 `owner_id` 字段：
- `owner_id = NULL`：内置题型，所有用户可见，不可修改/删除
- `owner_id = 用户ID`：用户自定义题型，仅本人（或 admin）可见/修改/删除

查询时过滤条件：`owner_id IS NULL OR owner_id = 当前用户ID`。

## 题目导入去重

`POST /api/questions/import` 的去重范围为**当前用户自己的题库**（`filter_by(owner_id=_import_user.id)`），不跨用户去重，避免不同用户导入相同内容时被误判为重复。

## API Key 管理

**两种 Key 并存，优先级不同：**
1. **用户个人 Key**（优先）：存储在 `User.api_key_encrypted`（Fernet 加密），通过设置 Modal 配置，仅 vip/admin 可设置
2. **系统兜底 Key**（Fallback）：存储在 `.env` 文件的 `DEEPSEEK_API_KEY`，通过知识图谱面板的管理员专属卡片配置

AI 调用时优先取用户个人 Key，无则 fallback 到系统 Key（`rag_routes._get_api_key_for_current_user()`）。

**前端入口**：
- **设置 Modal**：仅对 vip/admin 显示 API Key 输入区，含申请链接（`platform.deepseek.com`）
- **知识图谱面板**：admin 看到系统兜底 Key 配置卡片；vip 看到状态提示 + 跳转设置的按钮；普通用户/游客两个卡片均隐藏

## 题库导入导出（Excel）

- **模板文件**：项目根目录 `muban_zh.xlsx`，第3行为列头（含"题干"，代码以此定位），第4行起为数据
- **导出路由**：`POST /api/questions/export-xlsx`，依赖模板文件；`GET /api/templates/download-xlsx` 供用户下载模板
- **导入解析**：`_parse_xlsx_questions()`，自动检测标题行，兼容自建模板格式与外部题库格式
- **导出超长警告**：字段超 500 字符时弹 Modal（`id="export-warn-modal"`，置于 `</body>` 前顶层避免 tab `display:none` 遮挡），支持"对其余题也执行此选择"复选框批量决策

## 面试套题质量检查

套题管理按钮分两种：
- **检查**（所有用户）：`ivBasicCheck(sessionId)`，拉取套题 → 逐套调 `/api/interview/sets/{id}` → 检查题干/答案是否为空，结果展示在 `iv-qc-modal`，问题行附"查看/编辑"按钮
- **AI检查**（仅 vip/admin）：`ivQualityCheck(sessionId)`，调 SSE 流接口 `/api/interview/sessions/{id}/quality-check/stream`

## 知识图谱 Tab 的访问控制

`ai-generation` Tab（前端标签"知识图谱"）行为：
- **AI 用户（vip/admin）**：隐藏示例区块，显示完整 AI 功能（文档管理、知识点提取、出题）
- **非 AI 用户（user/guest）**：显示示例知识图谱（D3 力图，5个农产品供给曲线知识点），隐藏 AI 功能区，弹出升级提示 Modal

**示例图谱接口**：`GET /api/rag/demo-graph`，返回 `_DEMO_KP_IDS = [8,9,10,11,12]` 对应的知识点及关联关系（来自 `ds_knowledge.db`），`demo_kp_hidden` 表记录用户软删除（当前前端已不使用软删除功能，接口保留备用）。

**前端注意事项**：在 `index.html` 的 DOMContentLoaded 回调内定义的函数若需被 HTML `onclick` 属性调用，必须显式赋值给 `window`（如 `window.hideDemoNodeFromDetail = hideDemoNodeFromDetail`）。D3 是否加载须用 `window.d3` 检测，不能直接用 `d3`（未声明变量会抛 `ReferenceError`）。
