# 试卷生成-online 开发进度文档

> 基于 `试卷生成-simple` 改造的线上多用户版本
> 工作目录：`D:\code\试卷\试卷生成-online`
> 最后更新：2026-03-26

---

## 一、项目背景与目标

将单用户桌面版改造为支持 200 人左右的线上多用户系统。

### 核心需求
1. **邀请制注册** + 游客预览账号（只读，预置示例题库）
2. **用户隔离**：每人独立题库；团队/课程可共享
3. **API Key 加密存储**：Fernet 对称加密，每用户独立
4. **Gunicorn 生产模式**：5 workers + Nginx 反向代理
5. 未来：AI 出题改异步（防止 worker 被长请求占满）

### 服务器建议
- 2核4G 起步，Gunicorn workers=5
- SQLite 够用（200人，写操作稀疏）
- AI 出题必须异步（见待完成 P3）

---

## 二、项目文件结构

```
试卷生成-online/
├── app/
│   ├── __init__.py
│   ├── auth_routes.py          ← 新增 ✅
│   ├── team_routes.py          ← 新增 ✅
│   ├── db_models.py            ← 改造 ✅
│   ├── factory.py              ← 改造 ✅
│   ├── routes.py               ← 待改 ⏳ (P1)
│   ├── rag_routes.py           ← 待改 ⏳ (P2/P3)
│   ├── interview_routes.py     ← 待改 ⏳ (P1)
│   ├── kg_routes.py            ← 原样，暂不改
│   ├── utils.py                ← 原样
│   ├── docx_importer.py        ← 原样
│   ├── models.py               ← 原样
│   └── templates/
│       ├── index.html          ← 待改 ⏳ (P4)
│       └── kg.html             ← 原样
├── config.py                   ← 改造 ✅
├── requirements.txt            ← 改造 ✅
├── server.py                   ← 原样（开发用）
├── wsgi.py                     ← 新增 ✅
├── .env.example                ← 新增 ✅
├── .gitignore                  ← 新增 ✅
├── nginx.conf                  ← 新增 ✅
├── deploy.sh                   ← 新增 ✅
└── exam-system-online.service  ← 新增 ✅
```

---

## 三、已完成部分 ✅

### 3.1 数据库模型（app/db_models.py）

#### 新增表

| 表名 | 用途 |
|------|------|
| `users` | 用户账号（含角色、加密 API Key） |
| `invite_codes` | 邀请码（有效期、使用次数） |
| `teams` | 团队 |
| `team_members` | 团队成员（admin/member 角色） |

#### 修改原有表
`questions` 和 `exams` 新增三个字段：
```sql
owner_id   INTEGER           -- 创建者 user.id
visibility VARCHAR(16)       -- 'private' / 'team' / 'guest_preview'
team_id    INTEGER           -- 所属团队（可空）
```

#### Fernet 加密工具函数
```python
# db_models.py
encrypt_api_key(plaintext: str) -> str
decrypt_api_key(ciphertext: str) -> str

# User 模型方法
user.set_api_key(plaintext)
user.get_api_key() -> str | None
```

加密密钥来源（优先级）：
1. 环境变量 `FERNET_KEY`（推荐生产使用）
2. 从 `SECRET_KEY` SHA256 派生（开发备用）

---

### 3.2 认证 Blueprint（app/auth_routes.py）

**Blueprint 前缀**：无（挂在根路径）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户名+密码登录 |
| POST | `/api/auth/logout` | 登出 |
| POST | `/api/auth/guest` | 游客一键登录（无密码） |
| POST | `/api/auth/register` | 邀请码注册 |
| GET  | `/api/auth/me` | 当前用户信息 |
| GET  | `/api/auth/apikey` | API Key 状态（不返回明文，返回 preview） |
| POST | `/api/auth/apikey` | 保存/更新 API Key |
| GET  | `/api/admin/invites` | 管理员：邀请码列表 |
| POST | `/api/admin/invites` | 管理员：批量生成邀请码 |
| DELETE | `/api/admin/invites/<id>` | 管理员：删除邀请码 |
| GET  | `/api/admin/users` | 管理员：用户列表 |
| POST | `/api/admin/users/<id>/toggle` | 管理员：启用/禁用用户 |

**装饰器**（可直接 import 用于其他 Blueprint）：
```python
from app.auth_routes import login_required, admin_required, guest_readonly, get_current_user
```

---

### 3.3 团队 Blueprint（app/team_routes.py）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/teams` | 我的团队列表 |
| POST | `/api/teams` | 创建团队 |
| GET  | `/api/teams/<id>` | 团队详情（含成员） |
| PUT  | `/api/teams/<id>` | 修改团队信息 |
| DELETE | `/api/teams/<id>` | 解散团队（仅创建者） |
| GET  | `/api/teams/<id>/members` | 成员列表 |
| POST | `/api/teams/<id>/members` | 加人（用用户名） |
| DELETE | `/api/teams/<id>/members/<uid>` | 移出成员 |
| PUT  | `/api/teams/<id>/members/<uid>/role` | 修改角色 |
| POST | `/api/teams/<id>/leave` | 主动退出团队 |

---

### 3.4 应用工厂（app/factory.py）

改动点：
1. 注册 `auth_bp`、`team_bp`
2. 启动时调用 `_seed_system_users()`：
   - 自动创建 `admin` 账号（密码读 `ADMIN_PASSWORD` 环境变量，默认 `admin123`）
   - 自动创建 `guest` 账号（role=guest，无密码）
   - 把无 owner 的旧题目/试卷归给 admin（`visibility=private`）
3. `_migrate_db()` 新增 6 个字段的 ALTER TABLE

---

### 3.5 配置与部署文件

| 文件 | 说明 |
|------|------|
| `config.py` | 加 `PERMANENT_SESSION_LIFETIME=7天` |
| `requirements.txt` | 加 `cryptography`、`gunicorn` |
| `wsgi.py` | Gunicorn 入口：`from app.factory import create_app; app = create_app('production')` |
| `.env.example` | 环境变量模板（SECRET_KEY / ADMIN_PASSWORD / FERNET_KEY / FLASK_ENV） |
| `.gitignore` | 排除 .env / *.db / venv / uploads 等 |
| `nginx.conf` | 反向代理配置，静态文件直出，proxy_read_timeout=180s |
| `deploy.sh` | 服务器更新脚本（git pull → pip install → systemctl restart） |
| `exam-system-online.service` | systemd 服务文件，workers=5，bind 127.0.0.1:5000 |

---

## 四、待完成部分 ⏳

### P1 — 数据隔离过滤（routes.py + interview_routes.py）✅ 已完成

**文件**：`app/routes.py`（~1000行）、`app/interview_routes.py`（~600行）

**改动原则**：所有查询加权限过滤，所有创建写入 `owner_id`。

#### 核心过滤函数（在 routes.py 顶部添加）

```python
def _visible_q_filter(user):
    """返回当前用户可见的题目过滤条件。"""
    from app.db_models import TeamMember
    my_team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()]
    conditions = [
        QuestionModel.owner_id == user.id,                        # 自己的
        QuestionModel.visibility == 'guest_preview',              # 游客预览
    ]
    if my_team_ids:
        conditions.append(
            db.and_(
                QuestionModel.visibility == 'team',
                QuestionModel.team_id.in_(my_team_ids)
            )
        )
    return db.or_(*conditions)
```

#### 需要改动的接口（routes.py）

| 接口 | 改动 |
|------|------|
| `GET /api/questions` | 加 `filter(_visible_q_filter(user))` |
| `GET /api/questions/<id>` | 加可见性检查 |
| `POST /api/questions` | 写入 `owner_id=user.id, visibility='private'` |
| `PUT /api/questions/<id>` | 检查 owner |
| `DELETE /api/questions/<id>` | 检查 owner |
| `GET /api/exams` | 同上，用 exam 的过滤 |
| `POST /api/exams` | 写入 owner_id |
| `POST /api/questions/import` | 写入 owner_id |
| `POST /api/questions/batch-delete` | 只能删自己的 |

#### 改 routes.py 的统一模式

在需要登录的接口开头加：
```python
from app.auth_routes import login_required, get_current_user

@bp.route('/api/questions', methods=['GET'])
@login_required
def get_questions():
    user = get_current_user()
    questions = QuestionModel.query.filter(_visible_q_filter(user)).all()
    ...
```

#### interview_routes.py 改动

interview 相关表（interview_pools 等）也需要加 `owner_id` 字段，改动模式同上。
可暂时用 `owner_id = session.get('user_id')` 直接取。

---

### P2 — rag_routes.py 改用用户 API Key

**文件**：`app/rag_routes.py`（~2500行）

在 `rag_routes.py` 顶部加：

```python
def _get_user_api_key():
    """优先用当前用户的 API Key，没有则 fallback 到环境变量。"""
    from app.auth_routes import get_current_user
    user = get_current_user()
    if user:
        key = user.get_api_key()
        if key:
            return key
    return os.getenv('DEEPSEEK_API_KEY', '')
```

然后全局替换：
```python
# 原来
os.getenv('DEEPSEEK_API_KEY')
# 改为
_get_user_api_key()
```

同时 ds_docs / ds_kps 也需要加 `owner_id` 过滤（ds_knowledge.db 是 raw sqlite3）：
- `ds_docs` 表加 `owner_id INTEGER` 字段
- 所有查询加 `WHERE owner_id = ?` 条件

---

### P3 — AI 出题改异步（rag_routes.py）

**背景**：5 个 Gunicorn worker 同时被 AI 请求占用 → 其他用户全卡死。

**改动位置**：`rag_routes.py` 的 `ds_generate` 函数（约在第 1800 行附近）。

**方案**：复用现有的 `_bg_tasks` 字典 + 线程池（OCR 已有此模式）。

```python
# 现有模式（OCR 用的）
_bg_tasks: dict[str, dict] = {}   # task_id → {status, result, error}

# ds_generate 改造步骤：
# 1. 接收请求 → 生成 task_id → 启动后台线程 → 立即返回 task_id
# 2. 前端改为轮询 GET /api/rag/tasks/<task_id>
# 3. 后台线程完成后把结果写入 _bg_tasks[task_id]
```

前端 `index.html` 中 `dsGenerate()` 函数对应修改：
- 提交后显示 loading
- 每 2 秒轮询一次 task 状态
- 完成后填入结果框

---

### P4 — index.html 加用户 UI ✅ 已完成

**文件**：`app/templates/index.html`（~5000行）

需要新增/修改的 UI 部分：

#### 1. 登录页（未登录时显示，替换主界面）

```html
<!-- 登录/注册/游客 三个入口 -->
<div id="login-page">
  <form id="login-form">用户名+密码</form>
  <form id="register-form">用户名+密码+邀请码</form>
  <button id="guest-btn">游客体验</button>
</div>
```

#### 2. 顶部导航栏改造（现有 navbar）

```
[系统名称]  [题库] [试卷] [AI出题] ...  |  [团队: xxx ▼]  [⚙ 设置]  [用户名 ▼登出]
```

#### 3. 设置 Modal

- API Key 输入框（password 类型）+ 保存按钮
- 显示状态：✅ 已配置 `sk-ab…xyz` / ❌ 未配置

#### 4. 管理员面板（role=admin 才显示）

- 邀请码管理（生成、查看、删除）
- 用户列表（启用/禁用）

#### 5. 题目可见性控制

- 保存/编辑题目时可选：仅自己 / 团队共享（选择哪个团队）

#### 前端初始化逻辑

```javascript
// 页面加载时
async function init() {
  const res = await fetch('/api/auth/me');
  if (res.status === 401) {
    showLoginPage();
  } else {
    const user = await res.json();
    showMainApp(user);
    if (!user.has_api_key) showApiKeyReminder();
  }
}
```

---

## 五、服务器部署步骤（首次）

```bash
# 1. 上传代码
git clone <repo> /root/exam-system-online
cd /root/exam-system-online

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 SECRET_KEY、ADMIN_PASSWORD、FERNET_KEY

# 4. 生成 FERNET_KEY（如需独立密钥）
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 5. 建日志目录
mkdir -p /var/log/exam-system-online

# 6. 注册 systemd 服务
cp exam-system-online.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable exam-system-online
systemctl start exam-system-online

# 7. 配置 Nginx
cp nginx.conf /etc/nginx/sites-available/exam-system-online
ln -s /etc/nginx/sites-available/exam-system-online /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 8. 首次启动后立即修改 admin 密码
# 登录后台 → 用户管理 → 修改密码（P4 完成后通过 UI 修改）
```

---

## 六、环境变量说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `SECRET_KEY` | ✅ | Flask session 加密，生产必须改 |
| `ADMIN_PASSWORD` | ✅ | admin 账号初始密码，首次启动后改 |
| `FERNET_KEY` | 推荐 | API Key 加密密钥；不填则从 SECRET_KEY 派生 |
| `FLASK_ENV` | ✅ | 生产填 `production` |
| `DEEPSEEK_API_KEY` | 可选 | 服务器统一 Key（用户没配置时 fallback） |

---

## 七、数据隔离规则速查

| visibility 值 | 谁能看 |
|--------------|--------|
| `private` | 仅 owner 本人 |
| `team` | owner + 同 team_id 的团队成员 |
| `guest_preview` | 所有已登录用户（含 guest） |

> 管理员（role=admin）可见所有数据（在过滤函数中单独处理）。

---

## 八、继续开发时的注意事项

1. **P1 是最重要的**，没有过滤的 routes.py 上线后题库会完全混在一起。
2. 改 `routes.py` 时注意：原来没有 `@login_required`，需要对每个接口加装饰器。
3. `interview_routes.py` 用的是 raw sqlite3（不是 SQLAlchemy），加过滤时直接在 SQL 里加 `WHERE owner_id = ?`。
4. `ds_knowledge.db` 是独立数据库文件，ds_docs/ds_kps 过滤需要在 `rag_routes.py` 的 raw sqlite3 查询里加条件。
5. guest 账号预置数据：直接给几道题设置 `visibility='guest_preview'`（通过 admin 账号操作即可，无需代码改动）。

---

## 九、2026-03-26 完成内容

### P4 — 前端用户 UI（index.html）✅

| 功能 | 说明 |
|------|------|
| 登录页 Overlay | 全屏遮罩，含登录/注册双 Tab、游客一键进入、回车快捷提交 |
| 顶部用户栏 | 显示用户名+角色、设置按钮、登出按钮；admin 额外显示管理按钮 |
| 设置 Modal | API Key 查看/保存 + 修改密码 |
| 管理员面板 Modal | 邀请码生成/列表/删除，用户列表启用/禁用 |
| 题目可见性控制 | 添加/编辑题目时可选 private/team/guest_preview |
| 页面初始化 | DOMContentLoaded 先调 `/api/auth/me`，401 则显示登录页 |

**新增后端接口：**
- `POST /api/auth/change-password` — 修改密码（验证旧密码）

### 权限体系调整 ✅

三级角色重新设计：

| 角色 | 注册方式 | 功能范围 |
|------|---------|---------|
| `guest` | 一键体验，无需注册 | 只读浏览 |
| `user` | 自由注册，无需邀请码 | 除 AI 提取/出题外的全部功能 |
| `vip` | 注册时填邀请码，或注册后"开通AI"输入邀请码升级 | 全部功能 |
| `admin` | 系统初始化创建 | 全部功能 + 管理后台 |

**改动文件：**
- `app/auth_routes.py`：新增 `ai_required` 装饰器、注册改为邀请码可选（有码→vip）、新增 `POST /api/auth/upgrade` 升级接口
- `app/rag_routes.py`：7 个 AI 接口加 `@ai_required`（ds-extract、ds-tasks、ds-tasks/pause、ds-generate、ds-generate-tasks、ds-batch-classify、ds-match-focus）
- `app/templates/index.html`：注册表单邀请码改可选、AI 按钮权限拦截、新增"开通AI"升级 Modal

### Bug 修复 ✅

| Bug | 原因 | 修复 |
|-----|------|------|
| 服务启动报 `database is locked` | `_seed_system_users` 中 `db.session.flush()` 持有写锁，`db.engine.connect()` 再次写入冲突 | 改用 `db.session.execute()` 保持同一事务 |
| 顶部按钮点击区域极小 | `header::before` 装饰层无 `pointer-events:none`，覆盖了按钮 | `user-bar` 加 `z-index:3` |

---

## 十、待完成 / 下一步建议

### 遗留问题
- `ds_knowledge.db`（RAG 文档库）的 `ds_docs`/`ds_kps` 表尚无 `owner_id` 过滤，多用户之间文档数据互通（见 P2 原始计划）
- `interview_routes.py` 的面试题库池尚无用户隔离

### 新方向：剪贴板 AI 模式
详见 `plans/plan_clipboard_ai_mode.md`。核心思路：去掉服务器端 DeepSeek 调用，改为生成提示词 → 用户复制到 AI 网页 → 粘贴结果回来 → 服务器解析入库。不需要 API Key，不需要服务器出网。

**需新增 4 个接口：**
- `GET /api/rag/ds-docs/<doc_id>/prompt` — 生成知识点提取 Prompt
- `POST /api/rag/ds-docs/<doc_id>/import-kps` — 解析粘贴内容批量入库
- `POST /api/rag/ds-generate-prompt` — 生成出题 Prompt
- `POST /api/rag/ds-import-questions` — 解析 AI 回答导入题库

### 生产部署前必做
1. `.env` 中设置随机 `SECRET_KEY`：`python -c "import secrets; print(secrets.token_hex(32))"`
2. `.env` 中设置独立 `FERNET_KEY`：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. **⚠️ FERNET_KEY 设好后不能再改**，否则已保存的用户 API Key 全部失效
4. 修改 `ADMIN_PASSWORD` 默认值 `admin123`
5. 配置 Nginx + systemd（见 `nginx.conf` / `exam-system-online.service`）

---

## 十一、2026-03-26 出题功能修复与分批逻辑重构

### Bug 修复：一键出题无响应 ✅

**现象**：AI 用户选中知识点后点击"一键出题"，按钮转圈后结果框为空，无任何错误提示。

**根因**：后端 `POST /api/rag/ds-generate` 已在此前改为异步接口（启动后台线程，立即返回 `{task_id}`），但前端 `dsGenerate()` 仍以同步方式处理，直接读取 `data.content`，拿到的是空字符串。

**修复**（`app/templates/index.html`）：
- 提交后从响应中取 `task_id`
- 每 2 秒轮询 `GET /api/rag/ds-generate-tasks/<task_id>`
- 状态 `done` → 填入结果框并显示统计（知识点数/字符数）
- 状态 `error` → 弹出错误提示
- 等待期间提示文字实时显示已等待秒数

### 分批出题逻辑重构 ✅

**变更前**：用户设置"每批知识点数"（默认20），系统按固定步长将所有知识点顺序切片成 N 批，每批覆盖连续知识点区间。

**变更后**：用户设置"分几批"（默认3，范围2-10），系统按批数均分题目，每批的知识点通过随机采样获得（与非分批模式逻辑完全一致），不同批覆盖的知识点可交叉。

**改动详情**：

| 位置 | 改动 |
|------|------|
| `index.html` UI | 控件 `id` 改为 `rag-batch-count`，标签"每批知识点数"→"分几批"，默认值 20→3，范围 5-50→2-10 |
| `index.html` `dsGenerate()` | 读取 `rag-batch-count`，请求体字段 `batch_size` → `batch_count` |
| `rag_routes.py` `ds_generate()` | 解析参数 `batch_count`（默认3，最小2），删除 `batch_size` |
| `rag_routes.py` `_run()` 普通分批 | 切片逻辑改为按批数循环，每批调 `_sample_kps_with_relations(kps_data, 该批题目数)` 随机采样 |
| `rag_routes.py` `_run()` 稀疏模式 | 批数直接用 `_batch_count`，不再从 `batch_size` 推导 |
| `rag_routes.py` `_run()` 自动降级 | `_batch_size = max(5, total_q//2)` 改为 `_batch_count = 2` |
| `rag_routes.py` stats 字典 | 删除 `batch_size` 字段，标题改为"随机采样 N 个知识点，共 M 题" |

**附带 Bug 修复**：`_run()` 内部赋值 `batch_count = _batch_count` 导致 Python 将 `batch_count` 识别为局部变量，使顶部的 `_batch_count = batch_count` 读取失败（`cannot access local variable`）。修复方式：在 `_run()` 开头加 `nonlocal batch_count`。

### 下一步：分批出题查重 🔲

详见 `plans/plan_batch_generate_dedup.md`。不同批随机采样可能采到同一知识点，导致生成重复题目，需在拼接前做去重（字符 n-gram Jaccard 相似度）。
