# 试卷生成系统（Online 版）技术参考手册

> 最后更新：2026-03-29
> 分支：`online`
> 服务器：`root@8.162.14.154`，应用目录 `/root/exam-system-online`

---

## 目录

1. [项目概述](#1-项目概述)
2. [目录结构](#2-目录结构)
3. [技术栈与依赖](#3-技术栈与依赖)
4. [环境配置](#4-环境配置)
5. [数据库模型](#5-数据库模型)
6. [应用工厂与启动流程](#6-应用工厂与启动流程)
7. [Blueprint 路由总览](#7-blueprint-路由总览)
8. [认证与权限系统](#8-认证与权限系统)
9. [核心业务模块](#9-核心业务模块)
   - 9.1 题目管理
   - 9.2 试卷管理
   - 9.3 题型管理
   - 9.4 数据导入导出
   - 9.5 数据库备份与迁移
   - 9.6 AI 出题（RAG 模块）
   - 9.7 知识图谱
   - 9.8 面试套题系统
   - 9.9 团队协作
10. [前端架构](#10-前端架构)
11. [生产部署](#11-生产部署)
12. [数据库迁移策略](#12-数据库迁移策略)
13. [测试架构](#13-测试架构)
14. [API 接口完整列表](#14-api-接口完整列表)
15. [关键设计约定](#15-关键设计约定)

---

## 1. 项目概述

将单用户桌面版试卷生成系统改造为支持约 200 人的线上多用户版本。

**核心特性：**
- 邀请制注册（无码可自注册为普通用户，有码升级为 vip）
- 用户数据完全隔离（owner_id + visibility 机制）
- 团队共享题库
- Fernet 对称加密存储 DeepSeek API Key
- AI 出题、知识图谱提取（DeepSeek 直出模式）
- 面试套题生成、管理、导出
- Gunicorn + Nginx 生产部署，SQLite WAL 模式

---

## 2. 目录结构

```
exam-system-online/
├── app/
│   ├── __init__.py
│   ├── factory.py              # 应用工厂，唯一入口
│   ├── db_models.py            # SQLAlchemy ORM 模型
│   ├── routes.py               # 主 Blueprint（题目/试卷/导入导出）
│   ├── auth_routes.py          # 认证 Blueprint
│   ├── team_routes.py          # 团队 Blueprint
│   ├── rag_routes.py           # AI 出题 Blueprint（独立 ds_knowledge.db）
│   ├── kg_routes.py            # 知识图谱可视化 Blueprint
│   ├── interview_routes.py     # 面试套题 Blueprint（raw SQL）
│   ├── docx_importer.py        # Word 文档解析器
│   ├── utils.py                # 工具函数
│   └── templates/
│       └── index.html          # 单页应用（全部前端）
├── tests/
│   ├── conftest.py             # pytest fixtures
│   ├── test_isolation.py       # 用户隔离测试
│   └── ...
├── docs/                       # 技术文档
├── exports/                    # 导出文件临时目录
├── uploads/
│   └── images/                 # 题目图片存储
├── rag_uploads/                # RAG 文档上传
├── config.py                   # Flask 配置类
├── factory.py → app/factory.py # 应用工厂
├── wsgi.py                     # Gunicorn 入口
├── server.py                   # 开发启动入口
├── fix_headings.py             # OCR 文档标题修复工具
├── muban_zh.xlsx               # 题库导入模板（第3行为列头）
├── requirements.txt
├── nginx.conf
├── exam-system-online.service  # systemd 服务文件
└── .env                        # 环境变量（不入 git）
```

---

## 3. 技术栈与依赖

| 类别 | 技术 |
|------|------|
| 后端框架 | Flask 3.x |
| ORM | Flask-SQLAlchemy |
| 数据库 | SQLite（WAL 模式，30s busy_timeout） |
| AI 调用 | openai SDK >= 1.0（指向 DeepSeek API） |
| 文档处理 | python-docx（Word 导入/导出）、openpyxl（Excel） |
| 加密 | cryptography（Fernet，API Key 加密存储） |
| 生产服务器 | Gunicorn 21+（5 worker，sync 模式） |
| 反向代理 | Nginx |
| 前端图形 | D3.js（知识图谱力导向图） |
| 前端编辑器 | Quill.js（富文本） |

```
# requirements.txt
flask
flask-sqlalchemy
python-docx
openai>=1.0
python-dotenv>=1.0
openpyxl>=3.0
pandas>=2.0
cryptography>=42.0
gunicorn>=21.0
```

---

## 4. 环境配置

### `.env` 变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `SECRET_KEY` | ✅ | Flask Session 加密密钥，生产必须修改 |
| `ADMIN_PASSWORD` | 推荐 | 管理员初始密码，默认 `admin123` |
| `FERNET_KEY` | 可选 | API Key 加密密钥；留空则从 SECRET_KEY 派生 |
| `FLASK_ENV` | 推荐 | `production` / `development` |
| `EXAM_DATA_DIR` | 可选 | 数据根目录；不设则为项目根目录 |
| `DEEPSEEK_API_KEY` | 可选 | 系统兜底 API Key（管理员在知识图谱面板配置） |
| `DATABASE_URL` | 可选 | 自定义数据库 URI；默认 SQLite |

### 配置类层级

```python
config = {
    'development': DevelopmentConfig,   # DEBUG=True
    'production':  ProductionConfig,    # DEBUG=False
    'testing':     TestingConfig,       # 内存 SQLite，WTF_CSRF_ENABLED=False
    'default':     DevelopmentConfig
}
```

`TestingConfig.SQLALCHEMY_DATABASE_URI = 'sqlite://'`，每个测试完全隔离。

---

## 5. 数据库模型

### 5.1 User（用户）

```
表名: users
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| username | String(64) unique | |
| email | String(128) unique nullable | |
| password_hash | String(256) | Werkzeug bcrypt |
| role | String(16) | `admin` / `vip` / `user` / `guest` |
| api_key_encrypted | Text nullable | Fernet 加密的 DeepSeek Key |
| invited_by | Integer FK(users) nullable | |
| is_active | Boolean default=True | |
| created_at | DateTime | |
| last_login | DateTime nullable | |

**方法：**
- `set_api_key(plaintext)` → Fernet 加密写入 `api_key_encrypted`
- `get_api_key()` → 解密返回明文；解密失败返回 None

### 5.2 InviteCode（邀请码）

```
表名: invite_codes
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| code | String(32) unique | |
| created_by | Integer FK(users) | |
| used_by | Integer FK(users) nullable | |
| used_at | DateTime nullable | |
| expires_at | DateTime nullable | |
| max_uses | Integer default=1 | 支持多次使用 |
| use_count | Integer default=0 | |
| note | String(256) nullable | |
| created_at | DateTime | |

**方法：** `is_valid()` → 检查 use_count < max_uses 且未过期

### 5.3 Team / TeamMember（团队）

```
表名: teams, team_members
```

Team 字段：id, name, description, created_by(FK), created_at
TeamMember 字段：id, team_id(FK), user_id(FK), role(member/admin), joined_at
唯一约束：`(team_id, user_id)`

### 5.4 QuestionTypeModel（题型）

```
表名: question_types
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK autoincrement | |
| name | String(64) | 内部标识，如 `简答>论述` |
| label | String(64) | 显示名，如 `论述题` |
| has_options | Boolean | 是否有选项（单选/多选/是非 = True） |
| is_builtin | Boolean | 内置题型（全用户可见，不可删） |
| owner_id | Integer FK nullable | NULL=内置；用户ID=自定义 |
| created_at | DateTime | |

**隔离规则：** 查询时过滤 `owner_id IS NULL OR owner_id = 当前用户ID`

**内置题型（7个）：**
单选、多选、是非、简答、简答>计算、简答>论述、简答>材料分析

### 5.5 QuestionModel（题目）

```
表名: questions
```

| 字段 | 类型 | 说明 |
|------|------|------|
| question_id | String(64) PK | 格式：`q_YYYYMMDDHHMMSS_N` 或导入时原ID |
| question_type | String(32) indexed | 对应 question_types.name |
| owner_id | Integer FK nullable indexed | 题目归属用户 |
| visibility | String(16) default='private' indexed | private/team/guest_preview |
| team_id | Integer FK nullable indexed | 团队共享时使用 |
| content | Text | 题干（中文） |
| options | Text | JSON 数组，选择题选项 |
| answer | Text | 答案 |
| reference_answer | Text | 参考答案 |
| explanation | Text | 解析 |
| content_en | Text nullable | 英文题干 |
| options_en | Text nullable | JSON 数组，英文选项 |
| subject | String(128) nullable indexed | 考试科目 |
| knowledge_point | String(256) nullable | 知识点 |
| tags | String(512) nullable | 逗号分隔标签 |
| difficulty | String(32) nullable | easy/medium/hard |
| language | String(10) default='zh' indexed | zh/en/both |
| metadata_json | Text default='{}' | 附加元数据 JSON |
| is_used | Boolean default=False indexed | 已出题标记 |
| used_date | DateTime | |
| imported_at | DateTime nullable | 导入时间 |
| interview_pool | Boolean default=False | 已加入面试题库池 |
| interview_set | Boolean default=False | 已被分配进套题 |
| interview_used | Boolean default=False | 所在套题已被标记使用 |
| created_at | DateTime | |
| updated_at | DateTime | |

**语言判断规则（`_detect_language`）：**
- 无中文字符 → `en`
- 有中文 + content_en 非空 → `both`
- 有中文 + content_en 为空 → `zh`

### 5.6 ExamModel（试卷）

```
表名: exams
```

| 字段 | 类型 | 说明 |
|------|------|------|
| exam_id | String(64) PK | |
| name | String(256) | 试卷名称 |
| owner_id | Integer FK nullable indexed | |
| visibility | String(16) default='private' indexed | |
| team_id | Integer FK nullable indexed | |
| config | Text default='{}' | JSON，题型配置信息 |
| subject | String(128) nullable | |
| is_confirmed | Boolean default=False | 是否已最终确认 |
| confirmed_at | DateTime nullable | |
| created_at | DateTime | |
| updated_at | DateTime | |

关联：`questions` (M:N via exam_questions 关联表，含 position 字段)

### 5.7 exam_questions（关联表）

```python
exam_questions = db.Table('exam_questions',
    db.Column('exam_id',     String(64), FK('exams.exam_id'),     primary_key=True),
    db.Column('question_id', String(64), FK('questions.question_id'), primary_key=True),
    db.Column('position',    Integer)   # 题目在试卷中的顺序
)
```

### 5.8 QuestionImageModel（图片元数据）

```
表名: question_images
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| image_id | String(64) unique | 格式：`img_` + uuid8 |
| question_id | String(64) FK nullable indexed | |
| field | String(32) | content / reference_answer / explanation |
| filename | String(256) | 磁盘文件名（basename） |
| original_name | String(256) | 原始上传文件名 |
| content_type | String(64) default='image/png' | |
| file_size | Integer | |
| created_at | DateTime | |

实际文件存放：`uploads/images/<filename>`
访问路径：`/api/images/<image_id>`

### 5.9 面试系统表（Raw SQL，无 ORM）

```
interview_pools          -- 题库池
interview_pool_questions -- 池-题目关联（pool_id, question_id, drawn）
interview_configs        -- 套题配置（slots_json）
interview_sessions       -- 抽题场次
interview_sets           -- 套题记录（question_ids_json）
demo_kp_hidden           -- 示例知识图谱软删除记录
```

**interview_pools**：id, pool_name, description, created_at, owner_id
**interview_pool_questions**：id, pool_id, question_id, drawn, drawn_at, added_at
**interview_configs**：id, pool_id, config_name, slots_json (JSON数组), created_at, updated_at
**interview_sessions**：id, pool_id, config_id, session_name, interview_count, sets_multiplier, score_per_slot_json, created_at, owner_id
**interview_sets**：id, session_id, set_code, question_ids_json, is_used, used_at, created_at

---

## 6. 应用工厂与启动流程

```python
# wsgi.py
from app.factory import create_app
app = create_app('production')
```

`create_app(config_name)` 执行顺序：

1. `app.config.from_object(config[config_name])`
2. 创建 UPLOAD_FOLDER / TEMP_FOLDER / EXPORTS_FOLDER / uploads/images
3. `db.init_app(app)` + `db.create_all()`（建表，幂等）
4. `_migrate_db()`（ALTER TABLE ADD COLUMN，幂等，异常静默跳过）
5. `_seed_question_types()`（内置题型不存在时写入）
6. `_seed_system_users(app)`（admin + guest 账号初始化；旧无主题目归 admin）
7. 注册 Blueprint：main → auth → team → rag（可缺依赖）→ kg → interview
8. 注册 `/api/shutdown` 热重启路由

**SQLite WAL 模式**（解决 Gunicorn 多 worker 写锁）：

```python
@event.listens_for(Engine, "connect")
def _set_sqlite_wal(dbapi_conn, connection_record):
    if isinstance(dbapi_conn, sqlite3.Connection):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=30000")
```

---

## 7. Blueprint 路由总览

| Blueprint | 前缀 | 文件 |
|-----------|------|------|
| `main` (bp) | `/api/` | `routes.py` |
| `auth` (auth_bp) | `/api/auth/` 和 `/api/admin/` | `auth_routes.py` |
| `team` (team_bp) | `/api/teams/` | `team_routes.py` |
| `rag` (rag_bp) | `/api/rag/` | `rag_routes.py` |
| `kg` (kg_bp) | `/` 和 `/api/kg/` | `kg_routes.py` |
| `interview` (interview_bp) | `/api/interview/` | `interview_routes.py` |

---

## 8. 认证与权限系统

### 8.1 用户角色矩阵

| 功能 | guest | user | vip | admin |
|------|:-----:|:----:|:---:|:-----:|
| 浏览 guest_preview 题目 | ✅ | ✅ | ✅ | ✅ |
| 浏览自己的题目/试卷 | ❌ | ✅ | ✅ | ✅（全部） |
| 增删改题目/试卷 | ❌ | ✅ | ✅ | ✅ |
| 自定义题型管理 | ❌ | ✅ | ✅ | ✅ |
| 设置个人 API Key | ❌ | ❌ | ✅ | ✅ |
| 文档上传 / 知识图谱 | ❌ | ❌ | ✅ | ✅ |
| AI 知识点提取/出题 | ❌ | ❌ | ✅ | ✅ |
| 系统 API Key 配置 | ❌ | ❌ | ❌ | ✅ |
| 用户管理 / 邀请码 | ❌ | ❌ | ❌ | ✅ |

### 8.2 认证装饰器

```python
@login_required     # session['user_id'] 必须存在
@admin_required     # role == 'admin'
@guest_readonly     # guest 只读（写操作返回 403）
@ai_required        # role in ('vip', 'admin')
```

Session 基于 Flask Cookie，`PERMANENT_SESSION_LIFETIME = 7天`

### 8.3 注册流程

```
POST /api/auth/register
├── 无邀请码 → role='user'（不开通 AI）
├── 有效邀请码 → role='vip'（开通 AI）
└── 邮箱：langxiaojuan@zuel.edu.cn

POST /api/auth/upgrade
└── 已注册 user → 提供邀请码 → 升级为 vip
```

### 8.4 API Key 管理

两种 Key 并存，优先级：用户个人 Key > 系统兜底 Key

```python
# rag_routes._get_api_key_for_current_user()
# 1. user.get_api_key()   → Fernet 解密 User.api_key_encrypted
# 2. fallback: os.environ.get('DEEPSEEK_API_KEY')  (来自 .env)
```

**Fernet 密钥派生：**
```python
# 若 FERNET_KEY 未设置，从 SECRET_KEY 派生：
import base64, hashlib
key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
```

### 8.5 数据可见性过滤

```python
def _visible_q_filter(user):
    if user.role == 'admin':
        return True  # 无过滤
    return db.or_(
        QuestionModel.owner_id == user.id,
        QuestionModel.visibility == 'guest_preview',
        db.and_(QuestionModel.visibility == 'team',
                QuestionModel.team_id.in_(用户所在团队ID列表))
    )
```

---

## 9. 核心业务模块

### 9.1 题目管理

**主要接口：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/questions` | 列表（支持 subject/type/language/difficulty/search/page 过滤） |
| POST | `/api/questions` | 新建（owner_id=当前用户，visibility='private'） |
| GET | `/api/questions/<id>` | 详情 |
| PUT | `/api/questions/<id>` | 更新 |
| DELETE | `/api/questions/<id>` | 删除（仅 owner 或 admin） |
| POST | `/api/questions/batch-delete` | 批量删除 |
| POST | `/api/questions/batch-update-type` | 批量修改题型 |

**题型匹配（`_match_question_type`）：**
1. 精确匹配已知题型名
2. 反向映射（`_XLSX_TYPE_REVERSE`：单选题→单选）
3. 模糊匹配内置模式（`_XLSX_TYPE_PATTERNS`）
4. 包含关系匹配
5. 均无匹配 → 需要创建新题型（`needs_create=True`）

### 9.2 试卷管理

**主要接口：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/exams` | 列表（可见性过滤） |
| POST | `/api/exams/generate` | AI 自动生成试卷（按题型配置抽题） |
| POST | `/api/exams/<id>/add_question` | 手动添加题目 |
| DELETE | `/api/exams/<id>/remove_question/<qid>` | 移除题目 |
| POST | `/api/exams/<id>/replace_question` | 替换题目 |
| POST | `/api/exams/<id>/confirm` | 最终确认（标记 is_used） |
| POST | `/api/exams/<id>/revert_confirmation` | 撤销确认 |
| GET | `/api/exams/<id>/export` | 导出 Word |

### 9.3 题型管理

```
GET    /api/question-types          # 当前用户可见题型（内置 + 自定义）
POST   /api/question-types          # 创建自定义题型（owner_id=当前用户）
PUT    /api/question-types/<id>     # 修改（仅 owner 或 admin）
DELETE /api/question-types/<id>     # 删除（仅 owner 或 admin；内置不可删）
```

**去重检查在应用层**（历史原因：SQLite 不支持在线 DROP CONSTRAINT）

### 9.4 数据导入导出

#### Excel 导入（`POST /api/questions/import`）

- 模板：`muban_zh.xlsx`，第 3 行为列头（含"题干"列定位），第 4 行起数据
- 解析函数：`_parse_xlsx_questions()`，自动检测标题行
- 去重范围：**仅当前用户自己的题库**（`filter_by(owner_id=user.id)`）
- 超长警告：字段超 500 字符弹 Modal（`id="export-warn-modal"`）

#### 文本粘贴导入（`POST /api/questions/import-text`）

- 接受 AI 生成的题库文本（豆包、千问、DeepSeek 等）
- 自动解析题型、题干、选项、答案等字段

#### Excel 导出（`POST /api/questions/export-xlsx`）

- 使用 `muban_zh.xlsx` 模板
- 支持选中导出（`question_ids` 参数）
- 超长字段警告机制（`POST /api/questions/check-export` 预检）

#### 模板下载

```
GET /api/templates/download       # 下载 Word 版题库模板
GET /api/templates/download-xlsx  # 下载 Excel 版题库模板（muban_zh.xlsx）
```

### 9.5 数据库备份与迁移

#### 导出

| 接口 | 格式 | 内容 |
|------|------|------|
| `GET /api/export/full-xlsx` | Excel | Sheet1:题目，Sheet2:试卷，Sheet3:自定义题型 |
| `GET /api/export/full-json` | JSON | 结构化备份（version:1.0），含题型/题目/试卷 |

文件名格式：`数据库备份_{username}_{YYYYMMDD_HHMMSS}.{ext}`

#### JSON 备份结构

```json
{
  "version": "1.0",
  "exported_by": "用户名",
  "exported_at": "ISO8601时间",
  "question_count": 100,
  "exam_count": 10,
  "question_types": [
    {"name": "简答>论述", "label": "论述题", "has_options": false}
  ],
  "questions": [ /* QuestionModel.to_dict() 数组 */ ],
  "exams": [
    {
      "exam_id": "...", "name": "...", "subject": "...",
      "config": {}, "is_confirmed": false,
      "question_ids": ["q1", "q2"]  /* 有序 */
    }
  ]
}
```

#### 导入（`POST /api/import/full-json`）

**执行顺序：**
1. 自定义题型：按 `name` 匹配，不存在则创建
2. 题目：建立 `{旧ID: 新ID}` 映射
   - 原 question_id 不存在 → 沿用原 ID
   - 冲突 → 生成 `q_imp_{时间戳}_{序号}`
3. 试卷：通过映射更新 question_ids；exam_id 冲突时生成 `exam_imp_{时间戳}_{序号}`
4. 关联关系通过 `exam_questions.insert()` 写入，保留 position

**安全性：** 不覆盖已有数据，多次导入幂等

### 9.6 AI 出题（RAG 模块）

**独立数据库：** `ds_knowledge.db`（路径 `EXAM_DATA_DIR/ds_knowledge.db`），不走主 ORM，`json` 模块在该文件中别名为 `_json_mod`

**主要流程：**
```
上传文档（.md/.txt/.docx）
  → _clean_ocr_md()           # 清理OCR页码标记
  → _extract_all_headings()   # 提取H1-H6标题
  → _clean_headings_with_ai() # DeepSeek Layer 0 分析
  → _detect_doc_type()        # 教材型 vs PPT型
  → _remove_non_content_sections()  # 删除学习目标/小结等
  → _apply_semantic_heading_remaps() # 修复标题层级
  → _parse_md_by_nodes() / _parse_md_multilevel()  # 按知识点切片
  → 存入 ds_knowledge.db
```

**Layer 0 AI 返回字段：**
- `flat_detected` / `flat_level`：是否扁平化及其层级
- `semantic_map`：`{'章':2, '节':3, '大目':4, '小目':5, '细目':6}`
- `chapters_tree`：`[{name, sections:[{name}]}]`
- `non_content_texts`：应删除的标题文本集合
- `extraction_nodes`：知识点提取目标节标题列表

**标题层级修复两轨道：**
- 轨道A：精确/模糊匹配 `chapters_tree` 中章/节名称
- 轨道B：正则模式匹配（大目：`^[一二三…]+[、．]`，小目：`^（[一二…]+）`，细目：`^\d+[.．）\s]`）

**PPT 型文档检测：** H1 出现 ≥3 次且占比 ≥20%，总层级 ≤3 → 不做 remap，仅删非内容

### 9.7 知识图谱

- 入口：知识图谱面板 → `showDsKgModal()` → 打开全屏 Modal
- 数据接口：`GET /api/rag/ds-graph`（返回当前用户知识点 + 关系）
- 渲染：D3.js 力导向图（`window.d3` 检测，不直接用 `d3` 变量）
- 示例图谱：`GET /api/rag/demo-graph`，固定 kp_id `[8,9,10,11,12]`（农产品供给曲线）

**前端访问控制：**
- AI 用户（vip/admin）：隐藏示例，显示完整功能
- 非 AI 用户：显示示例图谱，隐藏 AI 功能，弹升级提示

### 9.8 面试套题系统

**数据流：**
```
题库池（interview_pools）
  ↓ 添加题目
池-题目关联（interview_pool_questions）
  ↓ 创建套题配置
套题配置（interview_configs，slots_json）
  ↓ 抽题生成场次
场次（interview_sessions）
  ↓ 每套题
套题（interview_sets，question_ids_json）
```

**关键特性：**
- `interview_routes.py` 全部使用 raw SQL + `db.engine`，参数传 `dict(enumerate(params, 1))`
- 抽题算法：Fisher-Yates 随机，按槽位类型从池中取题，避免重复
- 套题检查：`ivBasicCheck`（所有用户，检查空题）、`ivQualityCheck`（vip/admin，AI 流式检查）
- 质量检查使用 SSE（Server-Sent Events）流式接口

**模板导出（`GET /api/interview/pools/<pool_id>/config/<config_id>/export-template`）：**
- `simplified=0`（默认）：通用模板，Sheet1:套题列表 + Sheet2:题目详情
- `simplified=1`：简化模板，仅 Sheet1:套题列表，列头格式 `槽位N-题型名`，列宽60

**简化版模板导入流程：**
1. `_detect_simplified_template(wb)`：检测单Sheet + `槽位N-题型名` 列头
2. `_parse_simplified_slots(headers)`：解析槽位配置
3. `_import_simplified_sets(...)`：逐行读内容 → 创建题目 → 加池 → 生成套题
4. question_id 格式：`iv_q_{时间戳}_{行号}_{槽位号}_{毫秒尾数}`

**面试 Word 导出：** `POST /api/interview/export/word`

### 9.9 团队协作

```
GET    /api/teams                          # 我的团队列表
POST   /api/teams                          # 创建团队
GET/PUT/DELETE /api/teams/<id>             # 团队详情/修改/删除
GET    /api/teams/<id>/members             # 成员列表
POST   /api/teams/<id>/members             # 邀请成员（by username）
DELETE /api/teams/<id>/members/<uid>       # 移除成员
PUT    /api/teams/<id>/members/<uid>/role  # 修改成员角色
POST   /api/teams/<id>/leave               # 退出团队
```

---

## 10. 前端架构

**单页应用**：`app/templates/index.html`（全部前端代码，约 15,000+ 行）

### 10.1 Tab 结构

| Tab ID | 标签 | 内容 |
|--------|------|------|
| `template-download` | 题库导入与模板下载 | 导入、模板下载、AI提示词、数据库备份 |
| `question-bank` | 题库管理 | 题目列表、筛选、批量操作 |
| `exam-generation` | 组卷管理 | 试卷创建、题目管理 |
| `settings` | 系统设置 | 课程设置、账号设置 |
| `ai-generation` | 知识图谱 | AI出题、文档管理、知识图谱可视化 |
| `interview-draw` | 面试套题 | 面试全功能（题库池、配置、场次、套题） |

### 10.2 面试 Tab 子面板（`ivSwitchPanel`）

```
iv-pool     — 题库池管理
iv-config   — 套题题型配置
iv-session  — 抽题场次
iv-sets     — 套题管理
iv-export   — 导出
iv-import   — 导入
```

### 10.3 关键全局变量

```javascript
ivPools         // 题库池列表缓存
ivCurrentPoolId // 当前选中池
ivSlots         // 当前编辑中的槽位配置数组
_ivImportFile   // 套题导入暂存文件
_ivImportSessionName // 套题导入暂存场次名
```

### 10.4 重要约定

- DOMContentLoaded 内定义的函数若需 `onclick` 调用，必须赋给 `window`：
  ```javascript
  window.hideDemoNodeFromDetail = hideDemoNodeFromDetail;
  ```
- D3 加载检测用 `window.d3`，不能直接用 `d3`（未声明会 ReferenceError）
- 移动端适配（≤768px）：知识图谱 Tab 三处横向 flex 布局改为竖向堆叠
  - `#demo-kp-layout`（示例图+详情）
  - `#ai-two-col`（文档管理+出题配置）
  - `#rag-chapters-kp-row`（章节筛选+知识点）

### 10.5 导出超长警告机制

```
POST /api/questions/check-export  → 返回超500字符字段警告列表
  ↓ 弹 Modal（id="export-warn-modal"，置于 </body> 前顶层）
  ↓ 支持"对其余题也执行此选择"复选框批量决策
  ↓ 用户确认后 POST /api/questions/export-xlsx
```

---

## 11. 生产部署

### 11.1 服务器信息

- IP：`8.162.14.154`
- 用户：`root`
- 应用目录：`/root/exam-system-online`
- 服务名：`exam-system-online`

### 11.2 常用命令

```bash
# 单文件部署（最常用）
scp app/routes.py       root@8.162.14.154:/root/exam-system-online/app/routes.py
scp app/interview_routes.py root@8.162.14.154:/root/exam-system-online/app/interview_routes.py
scp app/templates/index.html root@8.162.14.154:/root/exam-system-online/app/templates/index.html

# 重启服务
ssh root@8.162.14.154 "systemctl restart exam-system-online"

# 查看状态
ssh root@8.162.14.154 "systemctl status exam-system-online --no-pager"

# 查看错误日志
ssh root@8.162.14.154 "tail -50 /var/log/exam-system-online/error.log"

# 批量同步（排除数据库/日志/venv）
rsync -avz \
  --exclude='*.db' --exclude='*.db-*' \
  --exclude='venv/' --exclude='rag_uploads/' \
  --exclude='uploads/' --exclude='exports/' \
  --exclude='*.log' --exclude='__pycache__/' \
  ./ root@8.162.14.154:/root/exam-system-online/
ssh root@8.162.14.154 "systemctl restart exam-system-online"
```

### 11.3 Gunicorn 配置

```
wsgi:app
--workers 5
--bind 127.0.0.1:5000
--timeout 300
--access-logfile /var/log/exam-system-online/access.log
--error-logfile  /var/log/exam-system-online/error.log
```

### 11.4 注意事项

- **服务器无 git 仓库**，部署方式为 scp 直传
- Python 版本：**3.11**（注意 f-string 嵌套引号在 3.11 不支持，需用 `.format()`）
- SQLite WAL 模式解决多 worker 写锁，无需其他配置

---

## 12. 数据库迁移策略

无 Alembic，使用 `factory._migrate_db()` 手动幂等迁移：

```python
new_cols = [
    ('表名', '列名', '类型定义'),   # 追加新列
    ...
]
new_tables = [
    "CREATE TABLE IF NOT EXISTS ...",  # 追加新表
    ...
]
# 执行：ALTER TABLE ... ADD COLUMN ...
# 异常（列已存在）静默跳过
```

**新增列时：** 在 `new_cols` 列表末尾追加三元组
**新增表时：** 在 `new_tables` 列表末尾追加 DDL 字符串

---

## 13. 测试架构

```bash
# 运行全部测试
pytest tests/

# 运行单个文件
pytest tests/test_isolation.py

# 运行单个函数
pytest tests/test_isolation.py::test_function_name -v
```

**fixtures（`tests/conftest.py`）：**

| Fixture | 说明 |
|---------|------|
| `app` | 使用内存 SQLite 的 Flask 测试应用 |
| `client` | Flask 测试客户端 |
| `db` | 数据库会话 |
| `admin_user` | admin 账号 |
| `user_a`, `user_b` | 普通用户（隔离测试） |
| `guest_user` | guest 账号 |

**辅助函数：** `login()`, `login_as()`, `guest_login()`, `make_question()`, `make_exam()`

每个测试函数独立事务，测试间完全隔离。

---

## 14. API 接口完整列表

### 主 Blueprint（`/api/`）

```
GET     /                                    # 返回 index.html
POST    /api/images/upload                   # 上传图片
GET     /api/images/<image_id>               # 获取图片
DELETE  /api/images/<image_id>               # 删除图片
GET     /api/questions                       # 题目列表
GET     /api/questions/count                 # 题目数量
GET     /api/questions/subjects              # 科目列表
POST    /api/questions                       # 新建题目
GET     /api/questions/<question_id>         # 题目详情
PUT     /api/questions/<question_id>         # 更新题目
DELETE  /api/questions/<question_id>         # 删除题目
POST    /api/questions/batch-delete          # 批量删除
POST    /api/questions/batch-update-type     # 批量修改题型
POST    /api/questions/batch-release         # 批量标记未使用
POST    /api/questions/check-export          # 导出前超长检查
POST    /api/questions/export-xlsx           # 导出 Excel
POST    /api/questions/import                # 导入 Excel
POST    /api/questions/import-text           # 文本粘贴导入
GET     /api/questions/export                # 导出 JSON/CSV（旧接口，保留）
GET     /api/export/full-xlsx                # 全量 Excel 备份
GET     /api/export/full-json                # 全量 JSON 备份
POST    /api/import/full-json                # 从 JSON 备份导入
GET     /api/exams                           # 试卷列表
POST    /api/exams                           # 新建试卷
GET     /api/exams/<exam_id>                 # 试卷详情
PUT     /api/exams/<exam_id>                 # 更新试卷
DELETE  /api/exams/<exam_id>                 # 删除试卷
POST    /api/exams/<exam_id>/add_question    # 添加题目
DELETE  /api/exams/<exam_id>/remove_question/<qid>  # 移除题目
POST    /api/exams/generate                  # 生成试卷
GET     /api/exams/<exam_id>/export          # 导出 Word
POST    /api/exams/<exam_id>/replace_question # 替换题目
POST    /api/exams/<exam_id>/confirm         # 最终确认
POST    /api/exams/<exam_id>/revert_confirmation # 撤销确认
GET     /api/templates/download              # 下载 Word 模板
GET     /api/templates/download-xlsx         # 下载 Excel 模板
GET     /api/question-types                  # 题型列表
POST    /api/question-types                  # 创建题型
PUT     /api/question-types/<type_id>        # 修改题型
DELETE  /api/question-types/<type_id>        # 删除题型
GET     /api/course-settings                 # 课程设置
PUT     /api/course-settings                 # 更新课程设置
POST    /api/parse-review-notes              # 解析复习要点
```

### 认证 Blueprint（`/api/auth/`，`/api/admin/`）

```
POST    /api/auth/login                      # 登录
POST    /api/auth/logout                     # 登出
POST    /api/auth/guest                      # 游客一键登录
POST    /api/auth/register                   # 注册
POST    /api/auth/upgrade                    # 升级为 vip
GET     /api/auth/me                         # 当前用户信息
GET     /api/auth/apikey                     # 获取 API Key 状态
POST    /api/auth/apikey                     # 设置/更新 API Key
POST    /api/auth/change-password            # 修改密码
GET     /api/admin/invites                   # 邀请码列表（admin）
POST    /api/admin/invites                   # 创建邀请码（admin）
DELETE  /api/admin/invites/<invite_id>       # 删除邀请码（admin）
GET     /api/admin/users                     # 用户列表（admin）
POST    /api/admin/users/<user_id>/toggle    # 启用/禁用用户（admin）
```

### 团队 Blueprint（`/api/teams/`）

```
GET     /api/teams                           # 我的团队
POST    /api/teams                           # 创建团队
GET     /api/teams/<team_id>                 # 团队详情
PUT     /api/teams/<team_id>                 # 更新团队
DELETE  /api/teams/<team_id>                 # 删除团队
GET     /api/teams/<team_id>/members         # 成员列表
POST    /api/teams/<team_id>/members         # 添加成员
DELETE  /api/teams/<team_id>/members/<uid>   # 移除成员
PUT     /api/teams/<team_id>/members/<uid>/role  # 修改角色
POST    /api/teams/<team_id>/leave           # 退出团队
```

### RAG Blueprint（`/api/rag/`）

```
GET     /api/rag/config                      # 获取 RAG 配置
PUT     /api/rag/config                      # 更新 RAG 配置（系统Key）
GET     /api/rag/ds-docs                     # 文档列表
DELETE  /api/rag/ds-docs/<doc_id>            # 删除文档
POST    /api/rag/ds-upload                   # 上传文档
POST    /api/rag/ds-extract/<doc_id>         # 提取知识点（SSE流）
GET     /api/rag/ds-kps/<kp_id>              # 知识点详情
PUT     /api/rag/ds-kps/<kp_id>              # 更新知识点
PUT     /api/rag/ds-chapters                 # 更新章节名
POST    /api/rag/ds-match-focus              # 匹配重点/难点
POST    /api/rag/ds-batch-classify           # 批量分类（异步）
GET     /api/rag/ds-classify-tasks/<task_id> # 分类任务状态
GET     /api/rag/ds-export-xlsx              # 导出知识点 Excel
POST    /api/rag/ds-import-xlsx              # 导入知识点 Excel
GET     /api/rag/ds-tasks/<task_id>          # 提取任务状态（SSE）
POST    /api/rag/ds-tasks/<task_id>/pause    # 暂停提取
GET     /api/rag/ds-docs/<doc_id>/kps        # 文档的知识点列表
GET     /api/rag/ds-graph                    # 知识图谱数据
POST    /api/rag/ds-generate                 # AI 出题（SSE流）
GET     /api/rag/demo-graph                  # 示例知识图谱
DELETE  /api/rag/demo-graph/<kp_id>          # 软删除示例节点（保留备用）
GET     /api/rag/ds-generate-tasks/<task_id> # 出题任务状态
```

### 知识图谱 Blueprint（`/api/kg/`）

```
GET     /kg                                  # 知识图谱页面
GET     /api/kg/graph                        # 图谱数据（主数据库）
GET     /api/kg/chunks                       # 知识块列表
```

### 面试 Blueprint（`/api/interview/`）

```
GET     /api/interview/pools                 # 题库池列表
POST    /api/interview/pools                 # 创建题库池
PUT     /api/interview/pools/<pool_id>       # 更新题库池
DELETE  /api/interview/pools/<pool_id>       # 删除题库池
GET     /api/interview/pools/<pool_id>/questions         # 池题目列表
GET     /api/interview/pools/<pool_id>/stats             # 池统计
POST    /api/interview/pools/<pool_id>/questions/preview # 预览可加入题目
POST    /api/interview/pools/<pool_id>/questions/add     # 添加题目到池
POST    /api/interview/pools/<pool_id>/questions/remove  # 从池移除题目
DELETE  /api/interview/pools/<pool_id>/questions         # 清空池
GET     /api/interview/pools/<pool_id>/config            # 套题配置列表
PUT     /api/interview/pools/<pool_id>/config            # 保存/更新配置
DELETE  /api/interview/pools/<pool_id>/config/<config_id> # 删除配置
GET     /api/interview/pools/<pool_id>/config/<config_id>/export-template  # 导出模板
POST    /api/interview/pools/<pool_id>/check             # 抽题前检查
GET     /api/interview/templates/pool-xlsx               # 下载池导入模板
GET     /api/interview/sessions                          # 场次列表
POST    /api/interview/sessions                          # 创建场次（抽题）
GET     /api/interview/sessions/<session_id>/sets        # 场次套题列表
POST    /api/interview/sessions/<session_id>/draw        # 追加抽题
DELETE  /api/interview/sessions/<session_id>             # 删除场次
POST    /api/interview/sessions/<session_id>/release-all # 释放全部套题
GET     /api/interview/sessions/<session_id>/quality-check/stream  # AI质检（SSE）
GET     /api/interview/sets/<set_id>                     # 套题详情
POST    /api/interview/sets/<set_id>/use                 # 标记已使用
POST    /api/interview/sets/<set_id>/release             # 释放套题
POST    /api/interview/sets/batch-use                    # 批量标记已使用
GET     /api/interview/sets/<set_id>/candidates          # 候选替换题目
POST    /api/interview/sets/<set_id>/replace             # 替换套题中的题目
POST    /api/interview/export/word                       # 导出 Word
GET     /api/interview/pools/<pool_id>/questions/export-xlsx     # 导出池题目 Excel
GET     /api/interview/sessions/<session_id>/export-xlsx         # 导出场次 Excel
POST    /api/interview/pools/<pool_id>/questions/import-xlsx     # 导入池题目
POST    /api/interview/sessions/import-xlsx/prepare              # 预检导入文件
POST    /api/interview/sessions/import-xlsx                      # 导入套题（自动检测格式）
```

---

## 15. 关键设计约定

### 15.1 Python 版本兼容性

服务器运行 **Python 3.11**，注意：
- **f-string 嵌套引号**在 3.12 才支持：`f"{''.join(list)}"` 会报 SyntaxError
- 必须改用 `.format()`：`'{}' .format('、'.join(list))`

### 15.2 interview_routes.py 的 Raw SQL 约定

```python
# 参数传递方式（positional dict）
result = db.session.execute(
    text("SELECT * FROM t WHERE a=:1 AND b=:2"),
    {1: val_a, 2: val_b}
)
# 或命名参数
result = db.session.execute(
    text("SELECT * FROM t WHERE a=:a AND b=:b"),
    dict(a=val_a, b=val_b)
)
```

辅助函数：`_fetch(sql, **kw)` → 列表，`_fetch_one(sql, **kw)` → 单行

### 15.3 rag_routes.py 的模块隔离

```python
import json as _json_mod   # 避免与其他变量冲突
```

独立 SQLite 文件 `ds_knowledge.db`，不通过 SQLAlchemy ORM 操作。

### 15.4 标题清洗流水线顺序约定

**Step 4（删非内容节）必须在 Step 5（remap 层级）之前执行。**

原因：remap 后节从 H2 升为 H3，若先 remap 再删，`skip_level=2` 会把整章内容误删。

### 15.5 新建/导入题目的 visibility

所有新建和导入的题目强制 `visibility='private'`，前端不再暴露 visibility 选择控件。

### 15.6 图片存储

- 文件路径：`uploads/images/<filename>`（filename 为 `image_id.ext` 格式）
- 元数据：`QuestionImageModel`
- 访问：`GET /api/images/<image_id>`
- 题目字段中以 `![alt](/api/images/img_xxxx)` Markdown 格式引用

### 15.7 fix_headings.py 命令行工具

```bash
# 修复单个文件（自动备份为 .bak.md）
python fix_headings.py file.md --subject 农业经济学

# 仅预览
python fix_headings.py file.md --subject 农业经济学 --dry-run

# API Key 优先级：--api-key > .env DEEPSEEK_API_KEY > 环境变量
python fix_headings.py file.md --api-key sk-xxxxx
```

### 15.8 题库去重范围

`POST /api/questions/import` 去重仅在**当前用户自己的题库**（`filter_by(owner_id=user.id)`）中查重，不跨用户。

### 15.9 面试套题配置保存流程

1. 点击「保存配置」
2. 若 `iv-config-pool-select` 未选池 → 弹 `iv-config-pool-modal`
3. 弹窗内可选已有池或新建池
4. 新建池：`POST /api/interview/pools` → `ivLoadPools()` → 同步更新下拉选择器
5. 确认后调 `_ivDoSaveConfig(poolId)` → `PUT /api/interview/pools/<pool_id>/config`
