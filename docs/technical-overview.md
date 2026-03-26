# 试卷生成-online 技术文档

> 基于 `试卷生成-simple` 改造的线上多用户版本
> 文档生成日期：2026-03-26（最后更新：2026-03-26）
> 当前分支：master

---

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [功能清单](#2-功能清单)
3. [API 端点完整列表](#3-api-端点完整列表)
4. [数据库模型](#4-数据库模型)
5. [权限与安全机制](#5-权限与安全机制)
6. [自动化测试现状](#6-自动化测试现状)
7. [需要手动测试的功能](#7-需要手动测试的功能)
8. [已知遗留问题](#8-已知遗留问题)
9. [生产部署检查清单](#9-生产部署检查清单)

---

## 1. 系统架构概览

### 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | Flask + Flask-SQLAlchemy |
| 数据库 | SQLite（主库）+ 独立 ds_knowledge.db（RAG 文档库） |
| 加密 | Fernet 对称加密（`cryptography` 包） |
| 生产服务器 | Gunicorn 5 workers + Nginx 反向代理 |
| 认证 | Flask Session（cookie，7 天有效） |
| AI 接口 | OpenAI 兼容接口（对接 DeepSeek） |

### 应用入口

```
server.py          ← 开发启动（Flask dev server）
wsgi.py            ← 生产入口（Gunicorn 使用）
app/factory.py     ← create_app() 应用工厂
```

### 工厂初始化顺序（`create_app`）

1. 加载 `config.py` 对应配置类
2. 创建目录：`uploads/`、`temp/`、`exports/`
3. `db.init_app` → `db.create_all`
4. `_migrate_db()`：幂等 ALTER TABLE 补加新列
5. 注册所有 Blueprint（rag/kg/interview 捕获 ImportError，允许缺依赖）
6. `_seed_system_users()`：初始化 admin + guest 账号，迁移旧数据

---

## 2. 功能清单

### 2.1 用户与权限系统 ✅ 已完成

| 功能 | 状态 | 说明 |
|---|---|---|
| 用户登录/登出 | ✅ | 用户名+密码，Session 7 天 |
| 游客一键体验 | ✅ | 无需注册，自动登录 guest 账号，只读 |
| 邀请码注册 | ✅ | 邀请码可选（填了→vip，不填→user） |
| 注册后升级 vip | ✅ | `POST /api/auth/upgrade` 输入邀请码升级 |
| 修改密码 | ✅ | 需验证旧密码 |
| API Key 加密存储 | ✅ | Fernet 加密，仅返回脱敏 preview（前6…后4） |
| 禁用/启用用户 | ✅ | admin 操作，禁用后无法登录 |
| 四级角色体系 | ✅ | guest / user / vip / admin |

**角色权限对照：**

| 角色 | 题库增删改 | AI 出题/提取 | 管理后台 | 注册方式 |
|---|---|---|---|---|
| `guest` | ❌ 只读 | ❌ | ❌ | 一键体验 |
| `user` | ✅ | ❌ | ❌ | 自由注册 |
| `vip` | ✅ | ✅ | ❌ | 邀请码注册/升级 |
| `admin` | ✅ | ✅ | ✅ | 系统初始化 |

---

### 2.2 邀请码管理 ✅ 已完成

| 功能 | 状态 |
|---|---|
| 批量生成邀请码（指定数量、有效天数、备注） | ✅ |
| 查看邀请码列表（含使用状态） | ✅ |
| 删除邀请码 | ✅ |
| 邀请码有效期检查 | ✅ |
| 邀请码使用次数限制（max_uses） | ✅ |

---

### 2.3 团队管理 ✅ 已完成

| 功能 | 状态 |
|---|---|
| 创建团队（创建者自动成为 admin 成员） | ✅ |
| 查看自己所在的团队列表 | ✅ |
| 查看团队详情（含成员） | ✅ |
| 修改团队信息（仅团队 admin） | ✅ |
| 解散团队（仅创建者） | ✅ |
| 添加成员（用用户名，仅团队 admin） | ✅ |
| 移出成员（仅团队 admin） | ✅ |
| 修改成员角色（admin↔member，仅团队 admin） | ✅ |
| 主动退出团队（创建者不可退，需解散） | ✅ |

---

### 2.4 题库管理 ✅ 已完成（含用户隔离）

| 功能 | 状态 |
|---|---|
| 题目 CRUD（按可见性过滤） | ✅ |
| 题目可见性控制（private/team/guest_preview） | ✅ |
| 批量删除（只能删自己的题目） | ✅ |
| 批量修改题型 | ✅ |
| 批量发布（设为 guest_preview） | ✅ |
| 从 Excel/Word 导入题目（自动带 owner_id） | ✅ |
| 导出题目为 Excel / Word | ✅ |
| 图片上传与关联题目 | ✅ |
| 题型自定义管理 | ✅ |
| 课程设置（课程名、学期、出题标题等） | ✅ |
| 科目/知识点/标签筛选 | ✅ |
| 双语题目（zh/en/both） | ✅ |
| 题目数量统计 | ✅ |

---

### 2.5 试卷管理 ✅ 已完成（含用户隔离）

| 功能 | 状态 |
|---|---|
| 试卷 CRUD | ✅ |
| 智能生成试卷（按题型数量配置随机抽题） | ✅ |
| 手动加入/移出/替换题目 | ✅ |
| 试卷确认/取消确认 | ✅ |
| 导出试卷为 Word | ✅ |
| 组卷时仅从当前用户可见题目中抽取 | ✅ |
| 题目不足时返回 shortages 信息 | ✅ |

---

### 2.6 AI 出题（RAG 模式）✅ 用户隔离已完成

| 功能 | 状态 | 说明 |
|---|---|---|
| 上传章节文档（.md/.txt/.docx） | ✅ | |
| AI 异步提取知识点（DeepSeek） | ✅ | 有异步 task 轮询 |
| 知识点手动编辑 | ✅ | |
| 知识图谱可视化（D3.js） | ✅ | |
| 基于知识图谱异步生成题目 | ✅ | |
| AI 批量分类 | ✅ | |
| AI 匹配重难点 | ✅ | |
| 导出/导入知识点（Excel） | ✅ | |
| 用户 API Key 优先（个人 Key fallback 到环境变量） | ✅ | `_get_user_api_key()` |
| RAG 文档按用户隔离（ds_docs owner_id 过滤） | ✅ | 上传写 `owner_id`；列表/删除/提取/知识图谱均过滤 |
| RAG 知识点访问验证（`_check_doc_access`） | ✅ | 所有 kps 操作先验证父文档归属 |

---

### 2.7 面试抽题模块 ✅ 已完成用户隔离

| 功能 | 状态 | 说明 |
|---|---|---|
| 题库池 CRUD | ✅ | |
| 题库池配置（题型槽位） | ✅ | |
| 向池添加/移出题目 | ✅ | |
| 从池抽取套题 | ✅ | |
| 标记套题已使用/释放 | ✅ | |
| 替换套题中的题目 | ✅ | |
| 质量检测（流式输出） | ✅ | |
| 导出套题为 Word | ✅ | |
| 导入/导出 Excel | ✅ | |
| 面试题库池按用户隔离 | ✅ | `_check_pool_access` / `_check_session_access` 全面覆盖 |
| import-xlsx 题目写 owner_id | ✅ | 导入创建的题目归属当前用户 |
| interview_status 标志按用户计算 | ✅ | `_sync_question_interview_status` 加 `owner_id` 参数，只查当前用户的池/场次 |

---

### 2.8 前端 UI ✅ 已完成

| 功能 | 状态 |
|---|---|
| 登录页 Overlay（登录/注册双 Tab + 游客入口） | ✅ |
| 回车快捷提交登录 | ✅ |
| 顶部用户栏（用户名+角色+设置+登出） | ✅ |
| admin 专属管理按钮 | ✅ |
| 设置 Modal（API Key 查看/保存 + 修改密码） | ✅ |
| 管理员面板 Modal（邀请码管理 + 用户管理） | ✅ |
| 题目可见性选择器（添加/编辑时） | ✅ |
| AI 按钮权限拦截（非 vip/admin 提示升级） | ✅ |
| 开通 AI 升级 Modal（输入邀请码） | ✅ |
| 页面初始化：调 `/api/auth/me`，401 显示登录页 | ✅ |

---

### 2.9 知识图谱可视化

| 功能 | 状态 |
|---|---|
| 图谱节点+边数据接口 | ✅ |
| D3.js 可视化页面 | ✅ |
| 节点 chunk 懒加载 | ✅ |

---

## 3. API 端点完整列表

### 认证模块（`/api/auth/`、`/api/admin/`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 无 | 登录（用户名+密码） |
| POST | `/api/auth/logout` | 登录 | 登出 |
| POST | `/api/auth/guest` | 无 | 游客一键登录 |
| POST | `/api/auth/register` | 无 | 注册（邀请码可选） |
| POST | `/api/auth/upgrade` | 登录 | 升级为 vip（输入邀请码） |
| GET | `/api/auth/me` | 登录 | 当前用户信息 |
| POST | `/api/auth/change-password` | 登录 | 修改密码 |
| GET | `/api/auth/apikey` | 登录 | API Key 状态（脱敏 preview） |
| POST | `/api/auth/apikey` | 非 guest | 保存/更新 API Key |
| GET | `/api/admin/invites` | admin | 邀请码列表 |
| POST | `/api/admin/invites` | admin | 批量生成邀请码 |
| DELETE | `/api/admin/invites/<id>` | admin | 删除邀请码 |
| GET | `/api/admin/users` | admin | 用户列表 |
| POST | `/api/admin/users/<id>/toggle` | admin | 启用/禁用用户 |

### 团队模块（`/api/teams/`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/teams` | 登录 | 我的团队列表 |
| POST | `/api/teams` | 非 guest | 创建团队 |
| GET | `/api/teams/<id>` | 成员 | 团队详情 |
| PUT | `/api/teams/<id>` | 团队 admin | 修改团队信息 |
| DELETE | `/api/teams/<id>` | 创建者 | 解散团队 |
| GET | `/api/teams/<id>/members` | 成员 | 成员列表 |
| POST | `/api/teams/<id>/members` | 团队 admin | 添加成员（用用户名） |
| DELETE | `/api/teams/<id>/members/<uid>` | 团队 admin | 移出成员 |
| PUT | `/api/teams/<id>/members/<uid>/role` | 团队 admin | 修改成员角色 |
| POST | `/api/teams/<id>/leave` | 非创建者 | 主动退出团队 |

### 题库与试卷（`/api/`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/questions` | 登录 | 题目列表（可见性过滤） |
| GET | `/api/questions/count` | 登录 | 题目数量统计 |
| GET | `/api/questions/subjects` | 登录 | 科目列表 |
| POST | `/api/questions` | 非 guest | 新建题目（自动写 owner_id） |
| GET | `/api/questions/<id>` | 可见 | 题目详情 |
| PUT | `/api/questions/<id>` | owner/admin | 更新题目 |
| DELETE | `/api/questions/<id>` | owner/admin | 删除题目 |
| POST | `/api/questions/batch-delete` | 登录 | 批量删除（只删自己的） |
| POST | `/api/questions/batch-update-type` | 登录 | 批量修改题型 |
| POST | `/api/questions/batch-release` | 登录 | 批量发布（设为 guest_preview） |
| POST | `/api/questions/import` | 非 guest | 从 Excel/Word 导入 |
| GET | `/api/questions/export` | 登录 | 导出为 Word |
| POST | `/api/questions/export-xlsx` | 登录 | 导出为 Excel |
| POST | `/api/questions/check-export` | 登录 | 校验导出题目 |
| POST | `/api/images/upload` | 非 guest | 上传图片 |
| GET | `/api/images/<image_id>` | 可见 | 获取图片 |
| DELETE | `/api/images/<image_id>` | owner | 删除图片 |
| GET | `/api/exams` | 登录 | 试卷列表（可见性过滤） |
| POST | `/api/exams` | 非 guest | 新建试卷 |
| GET | `/api/exams/<id>` | 可见 | 试卷详情 |
| PUT | `/api/exams/<id>` | owner/admin | 修改试卷信息 |
| DELETE | `/api/exams/<id>` | owner/admin | 删除试卷 |
| POST | `/api/exams/generate` | 非 guest | 智能生成试卷 |
| POST | `/api/exams/<id>/add_question` | owner | 加入题目 |
| DELETE | `/api/exams/<id>/remove_question/<qid>` | owner | 移出题目 |
| POST | `/api/exams/<id>/replace_question` | owner | 替换题目 |
| POST | `/api/exams/<id>/confirm` | owner | 确认试卷 |
| POST | `/api/exams/<id>/revert_confirmation` | owner | 取消确认 |
| POST | `/api/exams/<id>/export` | 可见 | 导出试卷为 Word |
| GET | `/api/question-types` | 登录 | 题型列表 |
| POST | `/api/question-types` | 登录 | 新建题型 |
| PUT | `/api/question-types/<id>` | 登录 | 修改题型 |
| DELETE | `/api/question-types/<id>` | 登录 | 删除题型 |
| GET | `/api/course-settings` | 登录 | 课程设置 |
| PUT | `/api/course-settings` | 登录 | 修改课程设置 |
| GET | `/api/templates/download` | 登录 | 下载导入模板 |
| POST | `/api/parse-review-notes` | 登录 | 解析评卷笔记 |

### AI 出题（`/api/rag/`，ai_required=vip/admin）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET/PUT | `/api/rag/config` | ai | DeepSeek 配置读写 |
| GET | `/api/rag/ds-docs` | ai | 文档列表 |
| DELETE | `/api/rag/ds-docs/<id>` | ai | 删除文档 |
| POST | `/api/rag/ds-upload` | ai | 上传并解析章节 |
| POST | `/api/rag/ds-extract/<id>` | ai | 异步提取知识点 |
| GET | `/api/rag/ds-docs/<id>/kps` | ai | 章节+知识点列表 |
| GET/PUT | `/api/rag/ds-kps/<id>` | ai | 知识点详情/修改 |
| PUT | `/api/rag/ds-chapters` | ai | 修改章节信息 |
| GET | `/api/rag/ds-tasks/<id>` | ai | 提取任务状态轮询 |
| POST | `/api/rag/ds-tasks/<id>/pause` | ai | 暂停提取任务 |
| GET | `/api/rag/ds-graph` | ai | 知识图谱数据 |
| POST | `/api/rag/ds-generate` | ai | 异步出题 |
| GET | `/api/rag/ds-generate-tasks/<id>` | ai | 出题任务状态轮询 |
| POST | `/api/rag/ds-match-focus` | ai | AI 匹配重难点 |
| POST | `/api/rag/ds-batch-classify` | ai | AI 批量分类 |
| GET | `/api/rag/ds-classify-tasks/<id>` | ai | 分类任务状态轮询 |
| POST/GET | `/api/rag/ds-export-xlsx` | ai | 导出知识点 Excel |
| POST | `/api/rag/ds-import-xlsx` | ai | 导入知识点 Excel |

### 面试抽题（`/api/interview/`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/interview/pools` | 题库池列表/创建 |
| PUT/DELETE | `/api/interview/pools/<id>` | 修改/删除题库池 |
| GET | `/api/interview/pools/<id>/stats` | 池内题目统计 |
| GET/PUT | `/api/interview/pools/<id>/config` | 池配置读写 |
| POST | `/api/interview/pools/<id>/check` | 检查池是否满足配置 |
| GET | `/api/interview/pools/<id>/questions` | 池内题目列表 |
| POST | `/api/interview/pools/<id>/questions/preview` | 预览待加入题目 |
| POST | `/api/interview/pools/<id>/questions/add` | 加入题目 |
| POST | `/api/interview/pools/<id>/questions/remove` | 移出题目 |
| DELETE | `/api/interview/pools/<id>/questions` | 清空池 |
| GET/POST | `/api/interview/sessions` | 会话列表/创建 |
| GET | `/api/interview/sessions/<id>/sets` | 会话套题列表 |
| POST | `/api/interview/sessions/<id>/draw` | 抽取一套题 |
| GET | `/api/interview/sets/<id>` | 套题详情 |
| POST | `/api/interview/sets/<id>/use` | 标记已使用 |
| POST | `/api/interview/sets/<id>/release` | 释放套题 |
| POST | `/api/interview/sessions/<id>/release-all` | 释放全部套题 |
| POST/GET | `/api/interview/sessions/<id>/quality-check` | 质量检测 |
| GET | `/api/interview/sessions/<id>/quality-check/stream` | 检测流式输出 |
| GET | `/api/interview/sets/<id>/candidates` | 可替换题目列表 |
| POST | `/api/interview/sets/<id>/replace` | 替换题目 |
| POST | `/api/interview/sets/batch-use` | 批量标记已使用 |
| POST | `/api/interview/export/word` | 导出套题 Word |
| GET | `/api/interview/pools/<id>/questions/export-xlsx` | 导出池题目 Excel |
| GET | `/api/interview/sessions/<id>/export-xlsx` | 导出会话 Excel |
| POST | `/api/interview/pools/<id>/questions/import-xlsx` | 导入题目 Excel |
| POST | `/api/interview/sessions/import-xlsx/prepare` | 准备导入会话 |
| POST | `/api/interview/sessions/import-xlsx` | 执行导入会话 |

**API 端点总计：约 119 个**

---

## 4. 数据库模型

### 表结构速览

| 表名 | 说明 | 关键字段 |
|---|---|---|
| `users` | 用户账号 | `role`, `api_key_encrypted`, `is_active` |
| `invite_codes` | 邀请码 | `max_uses`, `use_count`, `expires_at` |
| `teams` | 团队 | `created_by` |
| `team_members` | 成员关系 | `role`（admin/member），UNIQUE(team_id, user_id) |
| `questions` | 题目 | `owner_id`, `visibility`, `team_id` |
| `exams` | 试卷 | `owner_id`, `visibility`, `team_id`, `is_confirmed` |
| `exam_questions` | 试卷-题目关联 | `position`（顺序） |
| `question_types` | 题型定义 | `has_options`, `is_builtin` |
| `course_settings` | 课程元信息 | 全局单条 |
| `question_images` | 题目图片 | `question_id`, `field`, `image_id` |

### 数据可见性规则

```
visibility = 'private'       → 仅 owner 本人可见
visibility = 'team'          → owner + 同 team_id 的所有成员可见
visibility = 'guest_preview' → 所有已登录用户（含 guest）可见
admin 角色                   → 可见全部数据（无视 visibility）
```

### API Key 加密

```python
# 加密密钥来源（优先级）
1. FERNET_KEY 环境变量（推荐生产使用）
2. SHA256(SECRET_KEY)（开发备用）

# 使用方法
user.set_api_key('sk-xxxx')  # 加密存入 api_key_encrypted 列
user.get_api_key()           # 解密返回明文，失败返回 None

# GET /api/auth/apikey 返回脱敏：
{ "configured": true, "preview": "sk-ab…1234" }  # 前6位…后4位
```

### 数据库迁移策略

无 Alembic。使用 `factory._migrate_db()` 手动执行幂等 ALTER TABLE：

```python
# 在 new_cols 列表中追加三元组即可
new_cols = [
    ('questions', 'owner_id',   'INTEGER'),
    ('questions', 'visibility', "VARCHAR(16) DEFAULT 'private'"),
    ('questions', 'team_id',    'INTEGER'),
    ('exams',     'owner_id',   'INTEGER'),
    ('exams',     'visibility', "VARCHAR(16) DEFAULT 'private'"),
    ('exams',     'team_id',    'INTEGER'),
]
```

---

## 5. 权限与安全机制

### 装饰器一览

```python
from app.auth_routes import (
    login_required,   # 需登录，否则 401
    admin_required,   # 需 admin 角色，否则 403
    guest_readonly,   # guest 只读保护，写操作返回 403
    ai_required,      # 需 vip 或 admin，否则 403
    get_current_user, # 返回当前 User 对象（无登录返回 None）
)
```

### 可见性过滤函数

`routes.py` 中定义，所有题目/试卷查询均经过此过滤：

```python
def _visible_q_filter(user):
    """返回当前用户可见题目的 SQLAlchemy OR 条件。"""
    if user.role == 'admin':
        return True  # admin 看全部
    my_team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user.id)]
    conditions = [
        QuestionModel.owner_id == user.id,        # 自己的
        QuestionModel.visibility == 'guest_preview',  # 公开预览
    ]
    if my_team_ids:
        conditions.append(db.and_(
            QuestionModel.visibility == 'team',
            QuestionModel.team_id.in_(my_team_ids)
        ))
    return db.or_(*conditions)
```

### 写操作权限检查

- 修改/删除题目：`owner_id == user.id` 或 `user.role == 'admin'`，否则 403
- 修改/删除试卷：同上
- 批量删除：仅删除 `owner_id == user.id` 的条目，静默忽略他人题目
- 创建题目/试卷：自动写入 `owner_id = user.id`，默认 `visibility = 'private'`
- 面试题库池所有操作：通过 `_check_pool_access(pool_id, user)` 验证 `owner_id`
- 面试场次/套题所有操作：通过 `_check_session_access` / `_check_set_access` 链式验证
- `import_pool_xlsx` / `import_sets_xlsx` 创建的题目：自动写 `owner_id = user.id, visibility = 'private'`

### interview_status 标志计算隔离

题目上的三个面试状态标志（`interview_pool` / `interview_set` / `interview_used`）由 `_sync_question_interview_status(qids, owner_id)` 维护：

```python
# owner_id 有值时：只查当前用户的池和场次（JOIN 过滤）
pool_rows = _fetch(
    "SELECT DISTINCT ipq.question_id FROM interview_pool_questions ipq "
    "JOIN interview_pools ip ON ip.id = ipq.pool_id WHERE ip.owner_id=:uid",
    uid=owner_id
)
all_sets = _fetch(
    "SELECT ist.question_ids_json, ist.is_used FROM interview_sets ist "
    "JOIN interview_sessions iss ON iss.id = ist.session_id WHERE iss.owner_id=:uid",
    uid=owner_id
)
```

每次调用均传入 `owner_id=user.id`，确保用户 A 的操作不会影响用户 B 题目上的标志。

---

## 6. 自动化测试现状

### 测试配置

- 框架：`pytest`
- 数据库：内存 SQLite（`SQLALCHEMY_DATABASE_URI = 'sqlite://'`）
- 每个测试函数完全独立，通过 `function` 作用域 fixture 隔离

### 运行命令

```bash
pytest tests/                           # 全部测试
pytest tests/test_auth.py               # 仅认证测试
pytest tests/test_isolation.py -v       # 仅隔离测试，详细输出
pytest tests/test_teams.py::TestTeamCRUD  # 单个测试类
```

---

### test_auth.py — 认证系统（31 个测试用例）

#### TestLogin（7 个）

| 测试函数 | 验证点 |
|---|---|
| `test_login_success` | 正确用户名+密码 → 200，返回用户信息 |
| `test_login_wrong_password` | 密码错误 → 401 |
| `test_login_nonexistent_user` | 用户不存在 → 401 |
| `test_login_disabled_user` | 禁用账户 → 401 |
| `test_logout` | 登出后 `/api/auth/me` 返回 401 |
| `test_me_without_login` | 未登录访问 me → 401 |
| `test_me_after_login` | 登录后 me 返回正确用户名 |

#### TestGuestLogin（2 个）

| 测试函数 | 验证点 |
|---|---|
| `test_guest_login_success` | 游客登录成功，role=guest |
| `test_guest_login_no_account` | 无 guest 账号时 → 404 |

#### TestRegister（6 个）

| 测试函数 | 验证点 |
|---|---|
| `test_register_success` | 有效邀请码注册成功，邀请码 use_count+1 |
| `test_register_duplicate_username` | 重名 → 409 |
| `test_register_invalid_code` | 不存在的邀请码 → 400 |
| `test_register_expired_code` | 过期邀请码 → 400 |
| `test_register_used_code` | 已用尽的邀请码 → 400 |
| `test_register_short_password` | 密码过短 → 400 |

#### TestApiKey（6 个）

| 测试函数 | 验证点 |
|---|---|
| `test_apikey_not_set_by_default` | 默认未配置，configured=false，preview=null |
| `test_set_apikey` | 保存后数据库存的是密文，不含明文 |
| `test_apikey_encrypted_then_decryptable` | 加密后能正确解密还原 |
| `test_apikey_preview` | 返回脱敏 preview，含 `…` |
| `test_guest_cannot_set_apikey` | guest 设置 API Key → 403 |
| `test_unauthenticated_cannot_get_apikey` | 未登录获取 → 401 |

#### TestAdminInvites（5 个）

| 测试函数 | 验证点 |
|---|---|
| `test_admin_create_invites` | 批量生成3个邀请码，备注正确 |
| `test_non_admin_cannot_create_invites` | 普通用户生成 → 403 |
| `test_admin_list_users` | 用户列表包含已创建用户 |
| `test_admin_toggle_user` | 禁用/恢复用户，is_active 正确切换 |
| `test_admin_cannot_toggle_admin` | 不能禁用自己 → 400 |

---

### test_teams.py — 团队管理（13 个测试用例）

#### TestTeamCRUD（5 个）

| 测试函数 | 验证点 |
|---|---|
| `test_create_team` | 创建成功，返回团队信息 |
| `test_creator_is_admin_member` | 创建者自动成为 role=admin 成员 |
| `test_list_own_teams` | 只看到自己加入的团队 |
| `test_guest_cannot_create_team` | guest 创建团队 → 403 |
| `test_only_creator_can_disband` | 非创建者解散 → 403，创建者解散 → 200 |

#### TestTeamMembers（8 个）

| 测试函数 | 验证点 |
|---|---|
| `test_add_member` | 添加成员成功，成员出现在列表 |
| `test_add_nonexistent_user` | 添加不存在用户 → 404 |
| `test_add_duplicate_member` | 重复添加 → 409 |
| `test_remove_member` | 移出成员后不在列表 |
| `test_leave_team` | 成员主动退出成功 |
| `test_creator_cannot_leave` | 创建者退出 → 400 |
| `test_change_member_role` | 修改角色后 role 更新 |
| `test_non_admin_cannot_add_member` | 普通成员添加 → 403 |
| `test_outsider_cannot_view_team` | 不在团队的用户查看 → 403 |

---

### test_isolation.py — 数据隔离（22 个测试用例）

#### TestUnauthenticated（8 个，参数化）

验证以下端点未登录时返回 401：
- `GET /api/questions`
- `POST /api/questions`
- `GET /api/exams`
- `POST /api/exams`
- `GET /api/teams`
- `POST /api/teams`
- `GET /api/auth/me`
- `GET /api/auth/apikey`

#### TestQuestionVisibility（6 个）

| 测试函数 | 验证点 |
|---|---|
| `test_user_sees_own_questions` | 只看到自己的 private 题目 |
| `test_guest_preview_visible_to_all` | guest_preview 对所有登录用户可见 |
| `test_team_visibility` | 团队成员能看到 team 题目 |
| `test_team_question_invisible_to_outsider` | 非团队成员看不到 team 题目 |
| `test_admin_sees_all` | admin 看到所有人的 private 题目 |
| `test_guest_sees_only_preview` | guest 只看到 guest_preview，看不到 private |

#### TestQuestionWritePermission（7 个）

| 测试函数 | 验证点 |
|---|---|
| `test_user_can_edit_own_question` | 编辑自己的题目 → 200 |
| `test_user_cannot_edit_others_question` | 编辑他人题目 → 403 |
| `test_user_cannot_delete_others_question` | 删除他人题目 → 403 |
| `test_admin_can_edit_any_question` | admin 编辑任意题目 → 200 |
| `test_guest_cannot_create_question` | guest 创建题目 → 403 |
| `test_created_question_has_owner` | 新建题目自动带 owner_id + visibility=private |
| `test_batch_delete_only_own` | 批量删除只删自己的，返回正确 deleted_count |

#### TestExamIsolation（3 个）

| 测试函数 | 验证点 |
|---|---|
| `test_user_sees_own_exam` | 只看到自己的试卷 |
| `test_user_cannot_delete_others_exam` | 删除他人试卷 → 403 |
| `test_created_exam_has_owner` | 新建试卷自动带 owner_id |

#### TestGenerateExamIsolation（2 个）

| 测试函数 | 验证点 |
|---|---|
| `test_generate_only_uses_visible_questions` | 组卷仅从可见题目中抽取 |
| `test_generate_reports_shortage` | 题目不足时 shortages 字段有信息 |

---

### test_p2_p3_rag.py — RAG 改造（2 个测试用例）

| 测试函数 | 验证点 |
|---|---|
| `TestGetUserApiKey::test_user_key_takes_priority` | 用户个人 Key 优先于环境变量 Key |
| `TestGetUserApiKey::test_fallback_to_env_key` | 用户无 Key 时 fallback 到环境变量 |

> **注意**：RAG 文档隔离（ds_docs owner_id 过滤）的测试尚未实现。

---

### 测试覆盖统计

| 文件 | 测试用例数 | 覆盖模块 |
|---|---|---|
| test_auth.py | 26 | 登录/注册/API Key/邀请码/用户管理 |
| test_teams.py | 13 | 团队 CRUD/成员管理 |
| test_isolation.py | 22 | 数据可见性/写权限/组卷隔离 |
| test_p2_p3_rag.py | 2 | RAG API Key 优先级 |
| **合计** | **63** | |

---

## 7. 需要手动测试的功能

以下功能**没有自动化测试覆盖**，需要在实际运行环境中手动验证：

### 7.1 前端 UI 交互流程（高优先级）

| 测试项 | 测试步骤 | 预期结果 |
|---|---|---|
| **登录页 Overlay 完整流程** | 打开系统，验证是否显示登录页而非主界面 | 显示登录 Overlay，背景主界面模糊不可操作 |
| **注册流程（user → vip）** | 1. 不填邀请码注册；2. 登录后进"设置"填邀请码升级 | 1. role=user；2. role 变为 vip，AI 按钮解锁 |
| **游客体验** | 点击"游客一键体验" | 以 guest 身份登录，题库只读，无创建/编辑按钮 |
| **回车提交** | 在登录/注册表单中按回车 | 正确提交，无须点击按钮 |
| **API Key 保存与显示** | 在设置 Modal 中输入并保存 API Key | 页面显示 "✅ 已配置 sk-ab…xxxx"，刷新后仍存在 |
| **修改密码** | 在设置 Modal 中填写旧密码+新密码 | 修改成功，用新密码可登录，旧密码失效 |
| **管理员面板** | 以 admin 登录，点击"管理"按钮 | 显示邀请码管理+用户管理两个标签页 |
| **邀请码生成与使用** | 生成邀请码 → 用于注册 → 查看列表 | 邀请码状态变为"已使用"，注册用户 role=vip |
| **禁用用户后登录被拒** | 禁用某用户 → 用该账号登录 | 登录返回 401，界面提示账号已禁用 |
| **题目可见性选择器** | 添加题目时选择"团队共享" | 保存后该题目团队成员可见，其他人不可见 |
| **AI 按钮权限拦截** | 以 user（非 vip）身份点击 AI 出题按钮 | 弹出升级提示，而非直接调用接口 |

---

### 7.2 文件导入/导出（需要真实文件）

| 测试项 | 测试步骤 | 注意事项 |
|---|---|---|
| **Excel 题目导入** | 下载模板 → 填写题目 → 上传导入 | 验证多种题型（单选/多选/判断/简答）均能正确解析 |
| **Word 题目导入** | 准备含题目的 .docx → 上传导入 | 验证格式解析是否正确，特别是含公式/图片的题目 |
| **题目导出为 Excel** | 选择题目 → 导出 Excel | 打开 Excel 验证格式、内容、选项是否正确 |
| **题目导出为 Word** | 选择题目 → 导出 Word | 打开 Word 验证排版，特别是多选题选项对齐 |
| **试卷导出为 Word** | 确认试卷后导出 | 验证题头信息（课程名/学期/分数）、题型分组、答案页 |
| **图片题目导入导出** | 导入含图片的题目，再导出 Word | 图片应在 Word 中正确嵌入，而非显示占位符 |
| **知识点 Excel 导入导出** | 从 RAG 模块导出知识点 → 修改 → 重新导入 | 验证导入后知识点更新正确 |
| **面试套题导出 Word** | 创建面试套题 → 导出 Word | 验证多套题的布局，每套题间分页 |

---

### 7.3 AI 功能（需要有效 DeepSeek API Key）

| 测试项 | 测试步骤 | 注意事项 |
|---|---|---|
| **个人 API Key 优先级** | 设置个人 Key，触发 AI 出题 | 确认使用的是个人 Key，而非服务器 fallback Key（查看计费） |
| **知识点异步提取** | 上传文档 → 触发提取 → 轮询进度 | 进度条正确更新，完成后知识点列表有数据 |
| **暂停/恢复提取任务** | 提取过程中点击暂停 | 任务停止，已提取的知识点保留 |
| **异步出题** | 选择知识点 → 触发出题 → 等待结果 | 题目正确生成并自动入库，owner_id 正确 |
| **AI 批量分类** | 选择多道题 → 批量分类 | 知识点/难度自动填入，格式正确 |
| **多用户 AI 并发** | 两个 vip 账户同时触发 AI 出题 | 两个任务均完成，不互相干扰（验证线程安全） |
| **无 Key 情况下的错误提示** | 用户未设置 Key，服务器无 fallback Key | 前端显示友好错误信息，而非 500 |

---

### 7.4 多用户并发与隔离（需要多账号）

| 测试项 | 测试步骤 | 预期结果 |
|---|---|---|
| **题库不互通** | 用户 A 和用户 B 各自创建私有题目，互相登录查看 | 双方看不到对方的 private 题目 |
| **团队共享生效** | A 和 B 在同一团队，A 发布 team 题目 | B 能看到，C（不在团队）看不到 |
| **并发创建题目** | 多用户同时创建题目 | 各自题目 owner_id 正确，数据不混淆 |
| **Session 独立** | 同一浏览器不同标签页登录不同账户 | 两个 Session 互不干扰（实际会共用 cookie，建议用隐身窗口） |
| **admin 可见全部** | admin 账号查看题库 | 能看到所有用户的所有题目 |

---

### 7.5 RAG 文档隔离（需手动验证）

| 测试项 | 预期行为 | 验证要点 |
|---|---|---|
| 用户 A 上传的文档，用户 B 登录后能否看到 | 不应看到 | `list_ds_docs` 过滤 `owner_id=user.id OR owner_id IS NULL` |
| 用户 A 的知识图谱数据，用户 B 能否看到 | 不应看到 | `ds_graph` 同样过滤 |
| 用户 A 出题后，题目 owner_id 是否正确 | 应为 A 的 user_id | 查看 `questions` 表 |
| 旧文档（`owner_id IS NULL`）所有人可见 | 应可见 | 兼容旧数据的降级逻辑 |

---

### 7.6 面试题库隔离（需手动验证）

| 测试项 | 预期行为 | 验证要点 |
|---|---|---|
| 用户 A 的题库池，用户 B 能否看到 | 不应看到 | `_check_pool_access` 验证 `owner_id` |
| 用户 B 尝试向用户 A 的池导入题目 | 403 | `import_pool_xlsx` 调用 `_check_pool_access` |
| Excel 导入创建的题目归属 | 归属当前用户（`private`） | 查看 `questions.owner_id` |
| 题目 `interview_pool/set/used` 标志 | 仅反映当前用户自己的池/场次状态 | `_sync_question_interview_status` 加 `owner_id` 过滤 |
| 用户 A 的场次/套题，用户 B 不可访问 | 403 | `_check_session_access` / `_check_set_access` |

---

### 7.7 生产环境配置验证

| 测试项 | 验证方法 |
|---|---|
| FERNET_KEY 正确加载 | 保存 API Key → 重启服务 → 解密仍能成功 |
| Session 7天持久化 | 登录后不操作，7天内刷新仍有效 |
| Gunicorn workers 间 Session 共享 | 负载均衡后多次请求，Session 不丢失（注意：SQLite 不支持跨进程 in-memory） |
| Nginx 静态文件直出 | 访问 `/static/` 路径，检查 Nginx access log |
| 上传文件大小限制（16MB） | 上传超过 16MB 文件 → 413 错误 |
| admin 默认密码修改 | 首次部署后立即修改 admin123 |
| FERNET_KEY 不可更改警告 | 设置好后不要修改，否则已存储的 API Key 全部失效 |

---

### 7.8 边界与异常情况

| 测试项 | 预期结果 |
|---|---|
| 邀请码完全不填时注册（用户名+密码） | 注册成功，role=user（不是 vip） |
| 无效邀请码注册 | 400，友好提示 |
| 修改密码时旧密码错误 | 400，修改失败 |
| 删除他人账号图片 | 403 |
| 试卷已确认后再修改题目 | 验证是否有保护逻辑 |
| 知识点提取任务超时 | 后台线程超时处理，不永久 pending |
| 文档解析 docx 含特殊格式（表格、公式） | 优雅降级，不崩溃 |
| SQLite 并发写冲突 | 不出现 "database is locked" 错误（已修复一次） |

---

## 8. 已知遗留问题

| 问题 | 影响范围 | 优先级 | 说明 |
|---|---|---|---|
| AI 出题 worker 占用风险 | 生产环境 5 workers | P3（高） | 长时 AI 请求可能占满所有 worker；已有异步框架，但需在生产环境验证 |
| 剪贴板 AI 模式未实现 | 无 API Key 用户的 AI 出题 | 新方向 | 详见 `plans/plan_clipboard_ai_mode.md` |

> RAG 文档库用户隔离（P2）和面试题库用户隔离均已完成，不再是遗留问题。

---

## 9. 生产部署检查清单

### 首次部署

- [ ] `cp .env.example .env` 并填写所有必填变量
- [ ] `SECRET_KEY` 设置为随机值：`python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `FERNET_KEY` 设置为独立值：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- [ ] `ADMIN_PASSWORD` 修改为强密码（非 `admin123`）
- [ ] `FLASK_ENV=production`
- [ ] 注册 systemd 服务并设置开机自启
- [ ] 配置 Nginx 反向代理（`proxy_read_timeout=180s`，AI 请求需要较长时间）
- [ ] 建立日志目录 `/var/log/exam-system-online/`
- [ ] 验证服务启动无 `database is locked` 错误

### 上线后立即做

- [ ] 修改 admin 初始密码
- [ ] 生成邀请码，测试注册流程
- [ ] 预置游客示例题库（给几道题设置 `visibility='guest_preview'`）
- [ ] 验证 API Key 保存后服务重启仍可解密

### 安全注意事项

- **FERNET_KEY 一旦设置不可更改**，否则所有用户已存储的 API Key 全部失效
- `.env` 文件不能提交到 git（已在 `.gitignore` 中排除）
- SQLite 数据库文件应定期备份
- `uploads/` 目录需配置适当的磁盘配额

---

*文档由代码自动分析生成，如有出入以代码实现为准。*
