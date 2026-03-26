# 面试抽题模块用户隔离规划

> 规划日期：2026-03-26

---

## 一、现状分析

### 已完成隔离的部分

`interview_pools`（题库池）已**基本完成**隔离：

| 函数 | 隔离状态 |
|------|---------|
| `list_pools` | ✅ 非 admin 只看自己的 `WHERE owner_id=uid` |
| `create_pool` | ✅ 写入 `owner_id=user.id` |
| `_check_pool_access` | ✅ 写操作检查 owner |
| `update_pool` / `delete_pool` | ✅ 通过 `_check_pool_access` 保护 |

`interview_pools` 表的 `owner_id` 列已在 `factory._migrate_db` 中通过 `ALTER TABLE` 添加。

### 尚未隔离的部分

`interview_sessions`（面试场次）和 `interview_sets`（套题）**完全没有隔离**：

| 函数 | 问题 |
|------|------|
| `list_sessions` (line 584) | `SELECT * FROM interview_sessions` 无过滤，所有用户看到全部场次 |
| `create_session` (line 602) | INSERT 不写 `owner_id`，`interview_sessions` 表也没有该列 |
| `delete_session` (line 1087) | 无 owner 检查，任何人可删他人场次 |
| `draw` / `release` / `release-all` | 无 owner 检查 |
| `quality-check` (line 864/940) | 无 owner 检查 |
| `export-xlsx` (line 1506) | 无 owner 检查 |
| `sessions/import-xlsx` (line 1742) | 不写 owner_id |

`interview_sets` 通过 `session_id` 关联到场次，本身不需要独立的 `owner_id`，隔离 session 即可间接隔离 set。

---

## 二、改动方案

### 2.1 数据库迁移

在 `factory._migrate_db` 的 `new_cols` 列表中追加：

```python
('interview_sessions', 'owner_id', 'INTEGER'),
```

这是幂等操作，已有数据的 `owner_id` 为 NULL，由下面的逻辑处理。

### 2.2 新增访问检查辅助函数

仿照已有的 `_check_pool_access`，添加：

```python
def _check_session_access(session_id, user, write=False):
    """返回 (session_dict, None) 或 (None, (msg, code))。"""
    sess = _fetch_one("SELECT * FROM interview_sessions WHERE id=:id", id=session_id)
    if not sess:
        return None, ('场次不存在', 404)
    if write and user.role != 'admin' and sess.get('owner_id') != user.id:
        return None, ('无权操作他人场次', 403)
    return sess, None
```

### 2.3 需要修改的函数

#### `list_sessions` — 加 owner 过滤

```python
@interview_bp.route('/api/interview/sessions', methods=['GET'])
@login_required
def list_sessions():
    user = get_current_user()
    if user.role == 'admin':
        rows = _fetch("SELECT * FROM interview_sessions ORDER BY id DESC")
    else:
        rows = _fetch(
            "SELECT * FROM interview_sessions WHERE owner_id=:uid ORDER BY id DESC",
            uid=user.id
        )
    # 后续附加 total_sets / used_sets / pool_name 逻辑不变
```

#### `create_session` — 写入 owner_id

```python
# INSERT 语句加 owner_id 字段：
_run(
    "INSERT INTO interview_sessions (..., owner_id) VALUES (..., :uid)",
    ..., uid=user.id
)
```

#### 其余 session 写操作 — 加 `_check_session_access`

以下函数开头加两行：
```python
user = get_current_user()
sess, err = _check_session_access(session_id, user, write=True)
if err: return jsonify({'error': err[0]}), err[1]
```

涉及函数：
- `delete_session` (line 1087)
- `release_all` (line 836)
- `quality_check` (line 864)
- `quality_check_stream` (line 940)
- `session_export_xlsx` (line 1506)
- `session_import_xlsx` (line 1742)

#### 只读 session 操作 — 加可见性检查（write=False）

以下函数加 `_check_session_access(session_id, user, write=False)`：
- `list_session_sets` (line 731)
- `draw_set` (line 759) ← 实际是写操作，应用 write=True
- `session_import_xlsx_prepare` (line 1704)

---

## 三、遗留历史数据处理

已存在的 `interview_sessions`（`owner_id` 为 NULL）有两种处理方式：

**方案 A（推荐）**：归给 admin，与 questions/exams 保持一致

在 `factory._seed_system_users` 中，admin 创建后追加：
```python
db.session.execute(text(
    f"UPDATE interview_sessions SET owner_id={admin.id} WHERE owner_id IS NULL"
))
```

**方案 B**：保持 NULL，在过滤函数中加 `OR owner_id IS NULL` 让所有人可见

推荐方案 A，行为更可预期。

---

## 四、改动量估计

| 文件 | 改动类型 | 估计行数 |
|------|---------|---------|
| `app/factory.py` | `new_cols` 加一行 + `_seed_system_users` 加一条 UPDATE | +3 |
| `app/interview_routes.py` | 新增 `_check_session_access` + 修改约 10 个函数各加 2~4 行 | +60 |

总体改动量小，风险低，可独立完成，不影响其他模块。

---

## 五、实施顺序

1. `factory.py` 加迁移列 + 历史数据 UPDATE
2. `interview_routes.py` 添加 `_check_session_access` 辅助函数
3. 修改 `list_sessions` + `create_session`
4. 逐一给其余 session 接口加访问检查
5. 跑现有测试（`tests/test_teams.py` 等）确认不回归
6. 手动测试：两个普通账号互相不可见场次
