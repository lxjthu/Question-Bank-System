# 课程组功能规划

> 状态：规划中（已整合题库 + 面试池双权限体系）
> 日期：2026-03-26

---

## 一、需求梳理

| 需求 | 说明 |
|------|------|
| 任意注册用户可建组 | `user`/`vip`/`admin` 均可创建 |
| 邀请码加入 | 创建后生成唯一邀请码，分享即可加入 |
| 题库默认全开放 | 组内成员默认可增删改导入导出所有课程组题目 |
| 题库权限可调 | 管理者可对个别成员降权（只读/无权限） |
| 面试池独立权限 | 默认关闭，管理者逐人开放（viewer/manager） |
| 管理者制度 | owner 可指定多个 manager；manager 可调成员权限、可转让管理权 |
| 转让管理权 | owner 可转让 owner 身份；manager 可将自己的 manager 角色转给他人 |
| 共享试卷 | 组成员可查看、导出所有人生成的课程组试卷 |

与现有**团队（Team）**的区别：

| | 团队 | 课程组 |
|--|------|--------|
| 加入方式 | 管理员按用户名拉人 | 分享邀请码自助加入 |
| 题目权限 | 只读 (`visibility='team'`) | 默认全读写，可细调 |
| 面试池 | 无区分 | 独立三级权限 |
| 管理层级 | 无 | owner / manager / member |

---

## 二、成员角色与权限体系

### 2.1 三级角色（`role` 字段）

| 角色 | 产生方式 | 说明 |
|------|---------|------|
| `owner` | 创建者自动获得；或由 owner 转让 | 唯一；可修改任何人的任何权限；可解散课程组 |
| `manager` | owner 手动指定；或 manager 转让给他人 | 可修改普通成员的 `qbank_role` / `interview_role`；不可修改其他 manager 或 owner 的权限 |
| `member` | 通过邀请码加入后默认角色 | 按 `qbank_role` / `interview_role` 字段决定实际权限 |

> owner 和 manager 本身不受 `qbank_role` / `interview_role` 字段约束，永远拥有对应资源的完整权限（见下文）。

### 2.2 题库权限（`qbank_role` 字段，仅对 `member` 角色生效）

| 值 | 含义 | 默认 |
|----|------|------|
| `editor` | 全读写：可增删改导入导出课程组题目 | ✅ 新成员默认值 |
| `viewer` | 只读：可查看/导出，不可增删改 | — |
| `none`   | 无权限：看不到课程组题目 | — |

- `owner` 和 `manager` 角色：无条件拥有 `editor` 级别权限，`qbank_role` 字段对其无效
- 谁可以修改 `qbank_role`：`owner` 可改所有人；`manager` 可改 `member`

### 2.3 面试池权限（`interview_role` 字段）

| 值 | 含义 | 默认 |
|----|------|------|
| `none`    | 无权限：看不到该课程组的任何面试池 | ✅ 所有成员默认值 |
| `viewer`  | 只读：查看题库池、套题列表、可抽题 | — |
| `manager` | 管理：创建/配置/生成/删除套题 | — |

- `owner`：自动拥有所有课程组面试池的 `manager` 级别，字段无效
- `manager` 角色：`interview_role` 字段有效，默认 `none`，需 owner 显式授权
- 谁可以修改 `interview_role`：仅 `owner`（面试池权限比题库敏感，不下放给 manager）

### 2.4 权限矩阵速查

| 操作 | owner | manager | member (editor) | member (viewer) | member (none) |
|------|-------|---------|-----------------|-----------------|---------------|
| 查看课程组题目 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 增删改题目 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 查看/导出试卷 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 修改成员 qbank_role | ✅ | ✅(仅member) | ❌ | ❌ | ❌ |
| 修改成员 interview_role | ✅ | ❌ | ❌ | ❌ | ❌ |
| 指定/撤销 manager | ✅ | ❌ | ❌ | ❌ | ❌ |
| 转让 owner | ✅ | ❌ | ❌ | ❌ | ❌ |
| manager 自主转让 manager 角色 | — | ✅(转给member) | ❌ | ❌ | ❌ |
| 面试池（对应 interview_role） | manager | 按字段 | 按字段 | 按字段 | 按字段 |
| 解散课程组 | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 三、数据库设计

### 3.1 新增表

#### `course_groups`（课程组）

```sql
CREATE TABLE IF NOT EXISTS course_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(128) NOT NULL,
    description TEXT DEFAULT '',
    subject     VARCHAR(128) DEFAULT '',
    owner_id    INTEGER NOT NULL,           -- 当前 owner 的 user.id（随转让更新）
    invite_code VARCHAR(32) UNIQUE NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `course_group_members`（成员关系）

```sql
CREATE TABLE IF NOT EXISTS course_group_members (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       INTEGER NOT NULL,
    user_id        INTEGER NOT NULL,
    role           VARCHAR(16) DEFAULT 'member',    -- owner / manager / member
    qbank_role     VARCHAR(16) DEFAULT 'editor',    -- editor / viewer / none（仅对 member 角色生效）
    interview_role VARCHAR(16) DEFAULT 'none',      -- none / viewer / manager
    joined_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, user_id)
);
```

### 3.2 现有表新增字段（`_migrate_db` 幂等 ALTER TABLE）

| 表 | 字段 | 类型 | 说明 |
|----|------|------|------|
| `questions` | `course_group_id` | `INTEGER` | 所属课程组（NULL=个人题） |
| `exams` | `course_group_id` | `INTEGER` | 所属课程组 |
| `interview_pools` | `course_group_id` | `INTEGER` | 所属课程组（NULL=个人池，创建后锁定） |

`visibility` 新增值 `course_group`（现有 `private`/`team`/`guest_preview` 不变）。

### 3.3 ORM 模型（`db_models.py`）

```python
class CourseGroup(db.Model):
    __tablename__ = 'course_groups'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, default='')
    subject     = db.Column(db.String(128), default='')
    owner_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    invite_code = db.Column(db.String(32), unique=True, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.now)
    members     = db.relationship('CourseGroupMember', backref='group', lazy='dynamic')


class CourseGroupMember(db.Model):
    __tablename__ = 'course_group_members'
    id             = db.Column(db.Integer, primary_key=True)
    group_id       = db.Column(db.Integer, db.ForeignKey('course_groups.id'), nullable=False)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role           = db.Column(db.String(16), default='member')     # owner/manager/member
    qbank_role     = db.Column(db.String(16), default='editor')     # editor/viewer/none
    interview_role = db.Column(db.String(16), default='none')       # none/viewer/manager
    joined_at      = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('group_id', 'user_id'),)
```

`QuestionModel` / `ExamModel` 新增字段声明：
```python
course_group_id = db.Column(db.Integer, db.ForeignKey('course_groups.id'), nullable=True, index=True)
```

---

## 四、后端 API

### 4.1 新建 Blueprint：`app/course_group_routes.py`，前缀 `/api/course-groups`

| Method | 路径 | 最低权限 | 说明 |
|--------|------|---------|------|
| GET    | `/` | 登录 | 我参与的课程组列表（含我的角色） |
| POST   | `/` | 登录 | 创建课程组，自动生成邀请码，创建者成为 owner |
| GET    | `/<id>` | 组成员 | 课程组详情（含成员列表及各人权限） |
| PUT    | `/<id>` | owner | 修改名称/描述/科目 |
| DELETE | `/<id>` | owner | 解散课程组 |
| POST   | `/join` | 登录 | `{invite_code}` 加入课程组 |
| POST   | `/<id>/leave` | 组成员 | 退出（owner 须先转让；manager 直接退降为 member 记录删除） |
| POST   | `/<id>/invite/regenerate` | owner | 重新生成邀请码 |
| GET    | `/<id>/members` | 组成员 | 成员列表 |
| PUT    | `/<id>/members/<uid>` | owner 或 manager（受限） | 修改成员权限（见下文）|
| DELETE | `/<id>/members/<uid>` | owner | 移除成员（manager 也可移除普通成员） |
| POST   | `/<id>/transfer-owner` | owner | 转让 owner 给指定成员 |
| POST   | `/<id>/members/<uid>/transfer-manager` | manager | manager 将自己的管理权转让给某 member |

#### `PUT /<id>/members/<uid>` 字段修改权限细则

| 字段 | owner 可改范围 | manager 可改范围 |
|------|--------------|----------------|
| `role` (`manager`↔`member`) | 所有人 | ❌ 不可改 |
| `qbank_role` | 所有人 | 仅 member 角色的成员 |
| `interview_role` | 所有人 | ❌ 不可改 |

### 4.2 注册到 `factory.py`

```python
from app.course_group_routes import course_group_bp
app.register_blueprint(course_group_bp, url_prefix='/api/course-groups')
```

---

## 五、权限逻辑修改

### 5.1 辅助函数（可放在 `course_group_routes.py` 中 import 复用）

```python
def _get_member(group_id, user_id):
    """返回 CourseGroupMember 或 None。"""
    return CourseGroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()

def _get_qbank_role(group_id, user) -> str:
    """返回用户对课程组题库的有效角色：editor / viewer / none。"""
    if user.role == 'admin':
        return 'editor'
    grp = CourseGroup.query.get(group_id)
    if not grp:
        return 'none'
    if grp.owner_id == user.id:
        return 'editor'
    m = _get_member(group_id, user.id)
    if not m:
        return 'none'
    if m.role in ('owner', 'manager'):
        return 'editor'          # owner/manager 不受 qbank_role 字段限制
    return m.qbank_role or 'none'

def _get_interview_role(group_id, user) -> str:
    """返回用户对课程组面试池的有效角色：manager / viewer / none。"""
    if user.role == 'admin':
        return 'manager'
    grp = CourseGroup.query.get(group_id)
    if not grp:
        return 'none'
    if grp.owner_id == user.id:
        return 'manager'
    m = _get_member(group_id, user.id)
    if not m:
        return 'none'
    return m.interview_role or 'none'

def _can_manage_members(group_id, user) -> bool:
    """是否有修改成员权限的资格（owner 或 manager）。"""
    if user.role == 'admin':
        return True
    grp = CourseGroup.query.get(group_id)
    if grp and grp.owner_id == user.id:
        return True
    m = _get_member(group_id, user.id)
    return m is not None and m.role == 'manager'
```

### 5.2 `routes.py` — 题目/试卷可见性

`_visible_q_filter(user)` 新增 course_group 分支：

```python
from app.db_models import CourseGroup, CourseGroupMember

# 有任意题库访问权的课程组（qbank_role != none，或 owner/manager）
accessible_group_ids = []
for m in CourseGroupMember.query.filter_by(user_id=user.id).all():
    grp = CourseGroup.query.get(m.group_id)
    if not grp:
        continue
    if grp.owner_id == user.id or m.role == 'manager' or m.qbank_role in ('editor', 'viewer'):
        accessible_group_ids.append(m.group_id)

if accessible_group_ids:
    conds.append(db.and_(
        QuestionModel.visibility == 'course_group',
        QuestionModel.course_group_id.in_(accessible_group_ids)
    ))
```

`_visible_e_filter(user)` 同理（试卷：有 editor 或 viewer 权限的成员可见）。

### 5.3 `routes.py` — 题目/试卷写权限

```python
def _can_write_question(question, user) -> bool:
    if user.role == 'admin' or question.owner_id == user.id:
        return True
    if question.course_group_id:
        return _get_qbank_role(question.course_group_id, user) == 'editor'
    return False

def _can_write_exam(exam, user) -> bool:
    if user.role == 'admin' or exam.owner_id == user.id:
        return True
    if exam.course_group_id:
        return _get_qbank_role(exam.course_group_id, user) == 'editor'
    return False
```

### 5.4 `interview_routes.py` — 面试池权限

```python
def _get_pool_interview_role(pool, user) -> str:
    if user.role == 'admin':
        return 'manager'
    group_id = pool.get('course_group_id')
    if group_id:
        return _get_interview_role(group_id, user)
    # 个人面试池
    return 'manager' if pool.get('owner_id') == user.id else 'none'

def _check_pool_access(pool_id, user, require_write=False):
    pool = _fetch_one("SELECT * FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return None, ('题库池不存在', 404)
    role = _get_pool_interview_role(pool, user)
    if role == 'none':
        return None, ('无权访问此面试池', 403)
    if require_write and role != 'manager':
        return None, ('需要管理者权限', 403)
    return pool, None
```

调用约定：
- **只读路由**（`list_pool_questions`、`pool_stats`、`list_sets`、`get_set_detail`、`export_word` 等）：`require_write=False`
- **写操作路由**（`create_pool`、`update_pool`、`delete_pool`、`save_config`、`create_session`、`delete_session` 等）：`require_write=True`

---

## 六、前端 UI 规划（`index.html`）

### 6.1 导航栏新增课程组入口

```
[题库] [试卷] [AI出题] [知识图谱] [面试]  |  [课程组 ▼]  [团队 ▼]  [⚙ 设置]  [用户名 ▼]
```

### 6.2 课程组管理 Modal（三 Tab）

**Tab「我的课程组」**：卡片列表
- 组名、科目、人数、我的角色标签（owner / 管理者 / 成员）
- 邀请码 + 复制按钮（所有成员可见）
- 「成员权限」按钮（owner 和 manager 可见）
- 「退出」按钮

**Tab「创建课程组」**：名称、描述、科目 → 提交后自动生成邀请码

**Tab「加入课程组」**：输入邀请码 → 加入

### 6.3 成员权限面板（侧滑或子 Modal）

表格列：**用户名 | 角色 | 题库权限 | 面试权限 | 操作**

| 列 | owner 看到 | manager 看到 |
|----|-----------|-------------|
| 角色 | 下拉：manager ↔ member（owner 行锁定） | 只读展示 |
| 题库权限 | 下拉（所有人可改） | 下拉（仅 member 行可改） |
| 面试权限 | 下拉（所有人可改） | 只读展示（灰色） |
| 操作 | 移除按钮（非 owner 行） | 移除 member 按钮 |

额外按钮（owner 专属）：
- 「转让所有权」→ 选择目标成员确认
- 「转让管理权」提示：manager 本人可在自己行操作

manager 本人可见的按钮：
- 「将管理权转让给…」→ 从 member 列表选人

### 6.4 题目/试卷归属

添加/编辑弹窗新增下拉「归属」：
- 个人（默认，`private`）
- [课程组名] （需有 `editor` 权限）

### 6.5 题库筛选栏

新增筛选「课程组」：全部 / 个人 / [各组名]（仅列出有 viewer 及以上权限的组）

### 6.6 面试池课程组支持

- 创建面试池新增可选「课程组」（仅列出自己有 interview `manager` 权限的组）
- 池卡片显示 🏫 课程组标签
- 按 `interview_role` 动态隐藏增删改按钮

---

## 七、边界情况处理

| 情况 | 处理方式 |
|------|---------|
| owner 退出 | 必须先「转让所有权」，才能退出；不可直接退 |
| manager 退出 | 退出后角色记录删除，其题库/面试权限随之消失；其创建的题目留在课程组 |
| 成员被移除 | 其课程组题目留在组内，由剩余成员继续管理 |
| 解散课程组 | 所有题目 `visibility→private`，`course_group_id→NULL`，保留 `owner_id` |
| manager 转让 | 原 manager 降为 member（`role='member'`），目标成员升为 manager；`qbank_role` 不变，需 owner 另行设置 interview_role |
| owner 转让 | `course_groups.owner_id` 更新为目标成员；原 owner 的成员记录 `role` 改为 `manager` |
| 邀请码重新生成 | 旧码立即失效，仅 owner 可操作 |
| 面试池归属 | 创建后 `course_group_id` 锁定不可更改 |
| `qbank_role=none` 的成员 | `_visible_q_filter` 不含其课程组，完全看不到课程组题目 |

---

## 八、实施顺序

### Phase 1：数据模型
1. `db_models.py`：添加 `CourseGroup`、`CourseGroupMember` 模型；`QuestionModel`/`ExamModel` 加 `course_group_id` 字段
2. `factory.py`：`new_tables` + `new_cols`

### Phase 2：课程组 CRUD API
新建 `course_group_routes.py`，实现全部路由（含辅助函数 `_get_qbank_role`、`_get_interview_role`、`_can_manage_members`）。

### Phase 3：权限逻辑接入
1. `routes.py`：`_visible_q/e_filter`、`_can_write_question/exam`
2. `interview_routes.py`：`_get_pool_interview_role`、`_check_pool_access(require_write=)`、`create_pool` 支持 `course_group_id`

### Phase 4：前端
1. 课程组管理 Modal（含成员权限面板）
2. 题目归属字段 + 筛选栏
3. 面试池课程组字段 + 按权限动态显示按钮

---

## 九、不在本次范围内

- 课程组层级（子组）
- 课程组公告/消息
- 课程组统计看板
- 题目在课程组间移动（当前只能删除再重建）
