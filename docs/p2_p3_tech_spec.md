# P2 / P3 技术规格文档

> 文件：`app/rag_routes.py`（3333 行）
> 最后更新：2026-03-25

---

## P2 — 用户 API Key + ds_docs/ds_kps 数据隔离

### 2.1 当前问题

1. `_get_deepseek_key()` 只从 `.env` / 环境变量读取，所有用户共享同一个 Key
2. `ds_docs` / `ds_kps` 表没有 `owner_id`，所有用户看到所有人的知识点文档

### 2.2 数据库迁移

`_init_ds_db()`（约第 134 行）现有建表语句需补充 `owner_id` 字段，
同时在已有 ALTER TABLE 列表中加迁移语句：

```sql
-- ds_docs 加 owner_id
ALTER TABLE ds_docs ADD COLUMN owner_id INTEGER;

-- ds_kps 加 owner_id（可从 doc_id 反查 ds_docs.owner_id，也可冗余存储）
-- 选择冗余存储，避免每次 JOIN，查询更简单
ALTER TABLE ds_kps ADD COLUMN owner_id INTEGER;
```

建表语句（`_init_ds_db` 里 CREATE TABLE IF NOT EXISTS）也要加上 `owner_id INTEGER` 列，
确保新库直接建出来就有该字段。

### 2.3 新增 `_get_user_api_key()` 函数

替换 `_get_deepseek_key()` 的调用位置（共 **4 处**，见下表）。

```python
def _get_user_api_key() -> str:
    """
    优先取当前登录用户的 API Key（Fernet 解密），
    没有则 fallback 到服务器环境变量 / .env 文件。
    """
    try:
        from flask import has_request_context
        from app.auth_routes import get_current_user
        if has_request_context():
            user = get_current_user()
            if user:
                key = user.get_api_key()
                if key:
                    return key
    except Exception:
        pass
    return _get_deepseek_key()   # fallback
```

**调用 `_get_deepseek_key()` 的位置（需替换为 `_get_user_api_key()`）：**

| 行号 | 函数 | 说明 |
|------|------|------|
| ~1475 | `ds_extract` 背景线程 | 提取知识点时调用 DeepSeek |
| ~2136 | `ds_batch_classify` 背景线程 | 批量分类时调用 DeepSeek |
| ~3046 | `ds_generate` | 直出出题时调用 DeepSeek |
| ~1164 | `rag_get_config` GET 接口 | 返回 Key 配置状态（改为返回用户 Key 状态） |

> **注意**：背景线程（`threading.Thread`）运行时没有 Flask request context，
> `has_request_context()` 会返回 False，自动 fallback 到 `_get_deepseek_key()`。
> 解决方案：线程启动前在主线程取好 `api_key`，作为参数传入线程函数。

### 2.4 背景线程传 Key 的模式

```python
# 主线程（有 request context）
api_key = _get_user_api_key()

# 启动线程时把 key 传进去
def _extract_thread(doc_id, api_key, ...):
    # 直接用 api_key，不再调用 _get_user_api_key()
    ...

t = threading.Thread(target=_extract_thread, args=(doc_id, api_key, ...))
t.start()
```

涉及函数：`ds_extract`（约 1373 行）、`ds_batch_classify`（约 2082 行）。

### 2.5 ds_docs / ds_kps 查询隔离

所有涉及 `ds_docs` / `ds_kps` 的查询加 `owner_id` 过滤。

**规则：**
- `admin` 角色：可见所有文档（不加 `owner_id` 过滤）
- 普通用户：只能看 `owner_id = current_user.id` 的文档
- `guest`：只能看预置示范文档（`owner_id` 等于 guest 账号 id，或专门的 `visibility` 标记）

**需要修改的接口（约 12 个）：**

| 接口 | 函数名 | 行号 | 改动 |
|------|--------|------|------|
| GET /api/rag/ds-docs | `list_ds_docs` | ~1191 | 加 `WHERE owner_id=?` |
| DELETE /api/rag/ds-docs/<id> | `ds_delete_doc` | ~1226 | 加归属检查 |
| POST /api/rag/ds-upload | `ds_upload` | ~1238 | 写入 `owner_id` |
| POST /api/rag/ds-extract/<id> | `ds_extract` | ~1374 | 加归属检查 |
| GET /api/rag/ds-kps/<id> | `ds_kp_get` | ~1707 | 加归属检查（via doc） |
| PUT /api/rag/ds-kps/<id> | `ds_kp_update` | ~1738 | 加归属检查 |
| PUT /api/rag/ds-chapters | `update_ds_chapter` | ~1779 | 加归属检查 |
| POST /api/rag/ds-match-focus | `ds_match_focus` | ~2021 | 加归属过滤 |
| POST /api/rag/ds-batch-classify | `ds_batch_classify` | ~2083 | 加归属过滤 |
| GET /api/rag/ds-export-xlsx | `ds_export_xlsx` | ~2217 | 加归属过滤 |
| POST /api/rag/ds-import-xlsx | `ds_import_xlsx` | ~2500 | 写入 `owner_id` |
| GET /api/rag/ds-docs/<id>/kps | `ds_doc_kps` | ~2795 | 加归属检查 |
| GET /api/rag/ds-graph | `ds_graph` | ~2855 | 加归属过滤 |
| POST /api/rag/ds-generate | `ds_generate` | ~2952 | 加归属过滤 |

**通用辅助函数（在文件顶部添加）：**

```python
def _get_doc_owner_filter(user) -> str:
    """返回 ds_docs SQL WHERE 片段（不含 WHERE 关键字）。"""
    if user and user.role == 'admin':
        return "1=1"   # admin 无限制
    uid = user.id if user else -1
    return f"owner_id={uid}"
```

---

## P3 — ds_generate 改异步

### 3.1 当前问题

`ds_generate` 是同步接口，DeepSeek API 调用耗时 **20~60 秒**。
分批模式下多批串行，可能超过 **2 分钟**。

Gunicorn 5 workers，若同时有 5 个出题请求，所有 worker 被占满，
其他用户的所有请求（包括简单的题目列表查询）全部卡死等待。

### 3.2 改造目标

```
POST /api/rag/ds-generate
  → 立即返回 {"task_id": "gen_xxxxxx", "status": "pending"}

GET /api/rag/ds-generate-tasks/<task_id>
  → {"status": "pending|running|done|error", "content": "...", "stats": {...}, "error": "..."}
```

前端轮询间隔：2 秒。

### 3.3 实现方案

复用 `_classify_tasks` 的模式（第 1956 行），新增 `_generate_tasks` 字典：

```python
_generate_tasks: dict = {}
# 结构：
# {
#   "gen_xxxxxx": {
#     "status": "pending|running|done|error",
#     "content": "",          # 完成后填入
#     "stats": {},            # 完成后填入
#     "error": "",            # 失败时填入
#     "created_at": datetime
#   }
# }
```

**改造 `ds_generate`：**

```python
@rag_bp.route('/api/rag/ds-generate', methods=['POST'])
@login_required
@guest_readonly
def ds_generate():
    # 1. 参数解析（与现在一样）
    ...

    # 2. 提前取 api_key（有 request context）
    api_key = _get_user_api_key()
    if not api_key:
        return jsonify({'error': '未设置 API Key'}), 400

    # 3. 生成 task_id，写入 _generate_tasks
    task_id = f"gen_{uuid.uuid4().hex[:8]}"
    _generate_tasks[task_id] = {
        'status': 'pending',
        'content': '',
        'stats': {},
        'error': '',
        'created_at': datetime.now(),
    }

    # 4. 启动后台线程，把 api_key 和所有参数传入
    t = threading.Thread(
        target=_run_ds_generate,
        args=(task_id, kps_data, batch_mode, batch_size, sparse_mode,
              prompt_template, question_list, ql_counts, ql_parts, total_q,
              api_key),
        daemon=True,
    )
    t.start()

    # 5. 立即返回 task_id
    return jsonify({'task_id': task_id, 'status': 'pending'})
```

**新增后台函数 `_run_ds_generate`：**

```python
def _run_ds_generate(task_id, kps_data, batch_mode, batch_size, sparse_mode,
                     prompt_template, question_list, ql_counts, ql_parts, total_q,
                     api_key):
    """后台线程：执行 ds_generate 的全部逻辑，结果写入 _generate_tasks。"""
    _generate_tasks[task_id]['status'] = 'running'
    try:
        # 把现有 ds_generate 函数体（从分批/非分批逻辑开始）整体搬入此处
        # api_key 作为参数使用，不再调用 _get_user_api_key()
        ...
        _generate_tasks[task_id].update({
            'status': 'done',
            'content': final_content,
            'stats': stats,
        })
    except Exception as e:
        _generate_tasks[task_id].update({
            'status': 'error',
            'error': str(e),
        })
```

**新增轮询接口：**

```python
@rag_bp.route('/api/rag/ds-generate-tasks/<task_id>', methods=['GET'])
@login_required
def ds_generate_task_status(task_id):
    task = _generate_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'task not found'}), 404
    return jsonify({
        'status':  task['status'],
        'content': task.get('content', ''),
        'stats':   task.get('stats', {}),
        'error':   task.get('error', ''),
    })
```

### 3.4 前端改造要点（index.html）

`dsGenerate()` 函数（AI 出题 Tab）：

```javascript
async function dsGenerate() {
    // 1. POST /api/rag/ds-generate → 拿 task_id
    const res = await fetch('/api/rag/ds-generate', { method: 'POST', ... });
    const { task_id } = await res.json();

    // 2. 显示 loading 状态
    showGenerating();

    // 3. 轮询
    const poll = setInterval(async () => {
        const r = await fetch(`/api/rag/ds-generate-tasks/${task_id}`);
        const d = await r.json();
        if (d.status === 'done') {
            clearInterval(poll);
            hideGenerating();
            fillResult(d.content);
        } else if (d.status === 'error') {
            clearInterval(poll);
            hideGenerating();
            showError(d.error);
        }
        // pending/running → 继续等
    }, 2000);
}
```

---

## 注意事项

1. **`_generate_tasks` 内存泄漏**：任务完成后不自动清理。
   建议加简单的定时清理：任务完成超过 1 小时则删除。
   可在 `_run_ds_generate` 末尾延迟清理，或用 `threading.Timer`。

2. **并发限制**：多用户同时出题会启多个线程，每个线程独立调用 DeepSeek。
   DeepSeek API 有并发限制（付费账号通常 10~50 并发），超出会报 429。
   短期内不处理，后续可加线程池限制最大并发数。

3. **`rag_get_config` 接口**（GET `/api/rag/config`）：
   该接口现在返回服务器 Key 的配置状态。
   改造后应返回**当前用户**的 Key 状态（已配置/未配置 + preview），
   读取方式改为 `user.get_api_key()`。
