# 功能规划文档 1：知识图谱标签页 — 章节名称与知识点名称可内联编辑

**版本**：v1.1（2026-03-23 更新，基于实际代码结构）
**涉及功能**：知识图谱 Tab（`id="ai-generation"`）→ 章节筛选列表（`#rag-chapter-list`）→ 内联编辑章节名/知识点名

---

## 1. 需求背景

"知识图谱"标签页（`data-tab="ai-generation"`）包含两个核心功能区：
1. **左侧/上方**：文档上传、知识点提取进度
2. **右侧/中部**：选择参考文档 → 在"章节筛选"列表勾选章节 → 在"知识点"列表勾选知识点 → 配置提示词 → 一键出题

用户希望直接在"章节筛选"（`#rag-chapter-list`）和"知识点"（`#rag-section-list`）这两个列表中点击编辑按钮，修改章节名/知识点名并保存。这是最直观的位置，无需跳转弹窗。

**注意**：代码中还存在一个独立的 `ds-kg-modal`（知识图谱 D3 可视化 Modal），本功能不涉及该 Modal，仅针对出题配置区域的两个筛选列表。

---

## 2. 现有代码结构梳理

### 2.1 章节列表渲染函数（`renderRagChapterList`，约 6042 行）

```javascript
function renderRagChapterList(items) {
    el.innerHTML = items.map(c => {
        const val = c.name + '|||' + (c.section_name || '');
        const display = c.section_name
            ? `${c.name} › ${c.section_name}`
            : c.name;
        return `<label ...>
            <input type="checkbox" class="rag-chapter-cb" value="${val}">
            <span>${display}</span>
        </label>`;
    }).join('');
}
```

每个 chapter 对象结构（来自 `/api/rag/ds-docs/<doc_id>/kps` 响应）：
```javascript
{ name: "第一章 绪论", section_name: "", num: 1 }
// 或带节名：
{ name: "第一章 绪论", section_name: "第一节 基本概念", num: 1 }
```

**问题**：当前 chapter 对象**没有 `doc_id` 字段**，导致编辑时无法确定该章节属于哪个文档。

### 2.2 知识点列表渲染函数（`renderRagSectionList`，约 6074 行）

每个 section（实为知识点）对象：
```javascript
{
    num: kp.id,           // ds_kps.id（知识点主键）
    name: kp.name,        // kp_name
    chapter_name, chapter_num, section_name,
    display_name, teaching_focus, knowledge_type, cognitive_dimension
}
```

知识点已有 `num`（即 `kp_id`），可直接用于 `PUT /api/rag/ds-kps/<kp_id>`。

### 2.3 已有的知识点更新端点（`PUT /api/rag/ds-kps/<kp_id>`，第 1724 行）

```python
# 已支持字段：name, content, relations, teaching_focus, knowledge_type, cognitive_dimension
# kp_name 通过 data.get('name') 传入
```

**结论**：知识点名称的后端接口**已存在且已支持**，无需新增后端端点。

---

## 3. 方案设计

### 3.1 整体思路

| 编辑对象 | 标识符 | 后端动作 |
|---|---|---|
| 章节名 (`c.name`) | `doc_id` + `chapter_num` | 新增 `PUT /api/rag/ds-chapters` |
| 知识点名 (`kp_name`) | `kp_id` (`s.num`) | 使用现有 `PUT /api/rag/ds-kps/<kp_id>`（已支持） |

**编辑入口**：在每个列表项右侧显示一个 ✎ 小图标按钮，hover 时可见，点击后当前文字变为 `<input>` 框，Enter 确认，Esc 取消。

---

## 4. 后端变更

### 4.1 `/api/rag/ds-docs/<doc_id>/kps` — 新增 `doc_id` 字段到 chapter 对象

**位置**：`app/rag_routes.py` → `ds_doc_kps()` 函数（第 2307 行）

**改动**：在 `chapters_list` 的每个条目中加入 `doc_id`：

```python
chapters_list = sorted(
    [{'name': ch, 'section_name': sec, 'num': num, 'doc_id': doc_id}   # ← 新增 doc_id
     for (ch, sec), num in seen_ch.items()],
    key=lambda x: (x['num'], x['section_name'])
)
```

这样前端拿到章节数据时就知道它属于哪个文档，即可在编辑时传给后端。

### 4.2 新增 `PUT /api/rag/ds-chapters` — 修改章节名（含级联更新）

**位置**：`app/rag_routes.py`，注册到 `rag_bp`

**请求体**：
```json
{
  "doc_id": "abc123",
  "chapter_num": 1,
  "new_name": "第一章 新名称"
}
```

**处理逻辑**：

```python
@rag_bp.route('/api/rag/ds-chapters', methods=['PUT'])
def update_ds_chapter():
    """修改章节名称，级联更新所有相关记录。"""
    _init_ds_db()
    data = request.json or {}
    doc_id      = data.get('doc_id', '').strip()
    chapter_num = data.get('chapter_num')
    new_name    = data.get('new_name', '').strip()

    if not doc_id or chapter_num is None or not new_name:
        return jsonify({'error': '缺少必要参数'}), 400

    with _ds_db_conn() as conn:
        # 查出当前章节信息（特别是 parent_chapter_num，用于判断是否为 L1 章）
        row = conn.execute(
            "SELECT chapter_name, parent_chapter_num FROM ds_chapters "
            "WHERE doc_id=? AND chapter_num=?",
            (doc_id, chapter_num)
        ).fetchone()

        if not row:
            return jsonify({'error': '章节不存在'}), 404

        old_name = row['chapter_name']

        # 1. 更新 ds_chapters 主记录
        conn.execute(
            "UPDATE ds_chapters SET chapter_name=? WHERE doc_id=? AND chapter_num=?",
            (new_name, doc_id, chapter_num)
        )

        # 2. 如果是 L1 章（parent_chapter_num == 0），
        #    同步更新所有以此为父章的 L2 子章节的 parent_chapter_name
        if row['parent_chapter_num'] == 0:
            conn.execute(
                "UPDATE ds_chapters SET parent_chapter_name=? "
                "WHERE doc_id=? AND parent_chapter_num=?",
                (new_name, doc_id, chapter_num)
            )

        # 3. 同步更新 ds_kps 中所有该章节的 chapter_name
        conn.execute(
            "UPDATE ds_kps SET chapter_name=? WHERE doc_id=? AND chapter_num=?",
            (new_name, doc_id, chapter_num)
        )

        conn.commit()

    return jsonify({'success': True, 'new_name': new_name})
```

**级联更新说明**：

| 场景 | 更新位置 |
|---|---|
| L1 章节名修改 | `ds_chapters`（主记录）+ `ds_chapters`（子章的 `parent_chapter_name`）+ `ds_kps`（所有该章知识点的 `chapter_name`） |
| L2 子章节名修改 | `ds_chapters`（主记录）+ `ds_kps`（所有该章知识点的 `chapter_name`） |
| `ds_doc_refs` 中无章节名引用 | 无需处理 |

---

## 5. 前端变更（`app/templates/index.html`）

### 5.1 JS：`_ragAllChapters` 数据结构扩展

在加载章节数据时（约第 5822 行），将 `doc_id` 存入 chapter 对象：

```javascript
// 现有代码（第 5826-5833 行附近）：
for (const docId of checked) {
    const resp = await fetch(`/api/rag/ds-docs/${encodeURIComponent(docId)}/kps`);
    const meta = await resp.json();
    for (const ch of (meta.chapters || [])) {
        const key = ch.name + '|||' + (ch.section_name || '');
        allChapters.set(key, ch);  // ch 现在包含 doc_id（来自后端响应）
    }
}
```

由于后端已在 chapter 对象中返回 `doc_id`，前端无需额外处理，`ch.doc_id` 即可直接使用。

### 5.2 修改 `renderRagChapterList` — 添加编辑按钮

**当前**（约第 6048 行）：
```javascript
el.innerHTML = items.map(c => {
    ...
    return `<label style="display:flex;align-items:flex-start;gap:6px;padding:2px 0;cursor:pointer;">
        <input type="checkbox" class="rag-chapter-cb" value="${escapeHtml(val)}" ...>
        <span style="font-size:0.82rem;...">${display}</span>
    </label>`;
}).join('');
```

**修改后**：

```javascript
el.innerHTML = items.map(c => {
    const secName = c.section_name || '';
    const val = c.name + '|||' + secName;
    const display = secName
        ? `${escapeHtml(c.name)} <span style="color:#aaa">›</span> <span style="color:#555">${escapeHtml(secName)}</span>`
        : escapeHtml(c.name);
    return `
    <div class="rag-chapter-item"
         data-doc-id="${escapeHtml(c.doc_id || '')}"
         data-chapter-num="${c.num}"
         data-chapter-name="${escapeHtml(c.name)}">
        <label style="display:flex;align-items:flex-start;gap:6px;flex:1;min-width:0;cursor:pointer;padding:2px 0;">
            <input type="checkbox" class="rag-chapter-cb" value="${escapeHtml(val)}"
                   style="margin-top:2px;" onchange="filterRagSections()">
            <span class="rag-chapter-label" style="font-size:0.82rem;${secName ? 'padding-left:4px;' : ''}">${display}</span>
        </label>
        <button class="rag-edit-btn" title="编辑章节名"
                onclick="startChapterEdit(this)"
                style="flex-shrink:0;">✎</button>
    </div>`;
}).join('');
```

### 5.3 修改 `renderRagSectionList` — 添加编辑按钮

**当前**（约第 6080 行）：
```javascript
el.innerHTML = items.map(s => {
    const badges = _kpAttrBadges(s);
    return `
    <div style="display:flex;align-items:flex-start;gap:4px;padding:2px 0;">
        <label style="display:flex;align-items:flex-start;gap:6px;flex:1;min-width:0;cursor:pointer;">
            <input type="checkbox" class="rag-section-cb" value="${escapeHtml(s.name)}" ...>
            <span ...>${escapeHtml(s.display_name || s.name)}</span>
            ...
        </label>
    </div>`;
}).join('');
```

**修改后（在 label 后追加编辑按钮）**：

```javascript
el.innerHTML = items.map(s => {
    const badges = _kpAttrBadges(s);
    return `
    <div style="display:flex;align-items:flex-start;gap:4px;padding:2px 0;">
        <label style="display:flex;align-items:flex-start;gap:6px;flex:1;min-width:0;cursor:pointer;">
            <input type="checkbox" class="rag-section-cb" value="${escapeHtml(s.name)}"
                   style="margin-top:2px;" onchange="updateRagGenerateInfo()">
            <span style="font-size:0.82rem;word-break:break-all;">${escapeHtml(s.display_name || s.name)}</span>
            <span style="display:inline-flex;gap:2px;flex-shrink:0;">${badges}</span>
        </label>
        <button class="rag-edit-btn" title="编辑知识点名"
                data-kp-id="${s.num}"
                data-kp-name="${escapeHtml(s.name)}"
                onclick="startKpEdit(this)"
                style="flex-shrink:0;">✎</button>
    </div>`;
}).join('');
```

### 5.4 新增 JS 函数：章节名内联编辑

```javascript
// 章节名编辑入口
function startChapterEdit(btn) {
    const item = btn.closest('.rag-chapter-item');
    const docId = item.dataset.docId;
    const chapterNum = parseInt(item.dataset.chapterNum);
    const oldName = item.dataset.chapterName;
    const labelSpan = item.querySelector('.rag-chapter-label');

    // 替换为 input
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'rag-name-input';
    labelSpan.replaceWith(input);
    btn.style.display = 'none';
    input.focus();
    input.select();

    const confirm = async () => {
        const newName = input.value.trim();
        if (!newName || newName === oldName) { cancel(); return; }
        try {
            const r = await fetch('/api/rag/ds-chapters', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ doc_id: docId, chapter_num: chapterNum, new_name: newName })
            });
            const d = await r.json();
            if (d.success) {
                // 更新内存数据
                item.dataset.chapterName = newName;
                _ragAllChapters.forEach(c => {
                    if (c.doc_id === docId && c.num === chapterNum) c.name = newName;
                });
                _ragAllSections.forEach(s => {
                    if (s.chapter_num === chapterNum) s.chapter_name = newName;
                });
                // 重新渲染
                filterRagChapters();
                filterRagSections();
                showRagToast('章节名已更新');
            } else {
                alert('更新失败：' + (d.error || '未知错误'));
                cancel();
            }
        } catch (e) {
            alert('请求出错：' + e.message);
            cancel();
        }
    };
    const cancel = () => {
        const span = document.createElement('span');
        span.className = 'rag-chapter-label';
        span.style.fontSize = '0.82rem';
        span.textContent = oldName;
        input.replaceWith(span);
        btn.style.display = '';
    };

    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); confirm(); }
        if (e.key === 'Escape') cancel();
    });
    input.addEventListener('blur', confirm);
}

// 知识点名编辑入口
function startKpEdit(btn) {
    const kpId = parseInt(btn.dataset.kpId);
    const oldName = btn.dataset.kpName;
    const label = btn.previousElementSibling;
    const nameSpan = label.querySelectorAll('span')[0];  // 第一个 span 是名字

    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'rag-name-input';
    nameSpan.replaceWith(input);
    btn.style.display = 'none';
    input.focus();
    input.select();

    const confirm = async () => {
        const newName = input.value.trim();
        if (!newName || newName === oldName) { cancel(); return; }
        try {
            const r = await fetch(`/api/rag/ds-kps/${kpId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })  // 后端用 data.get('name')
            });
            const d = await r.json();
            if (d.success) {
                // 更新内存
                btn.dataset.kpName = newName;
                _ragAllSections.forEach(s => { if (s.num === kpId) { s.name = newName; s.display_name = newName; }});
                _ragAllKps.forEach(k => { if (k.id === kpId) k.name = newName; });
                filterRagSections();
                showRagToast('知识点名已更新');
            } else {
                alert('更新失败：' + (d.error || '未知错误'));
                cancel();
            }
        } catch (e) {
            alert('请求出错：' + e.message);
            cancel();
        }
    };
    const cancel = () => {
        const span = document.createElement('span');
        span.style.fontSize = '0.82rem';
        span.style.wordBreak = 'break-all';
        span.textContent = oldName;
        input.replaceWith(span);
        btn.style.display = '';
    };

    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); confirm(); }
        if (e.key === 'Escape') cancel();
    });
    input.addEventListener('blur', confirm);
}

// 轻提示（若全局已有 showToast 可复用，否则使用此简版）
function showRagToast(msg) {
    let t = document.getElementById('rag-toast');
    if (!t) {
        t = document.createElement('div');
        t.id = 'rag-toast';
        t.style.cssText = 'position:fixed;bottom:30px;left:50%;transform:translateX(-50%);'
            + 'background:#333;color:#fff;padding:8px 18px;border-radius:20px;font-size:0.85rem;'
            + 'z-index:9999;opacity:0;transition:opacity 0.2s;pointer-events:none;';
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = '1';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => { t.style.opacity = '0'; }, 2000);
}
```

**注意**：`startKpEdit` 中调用 `PUT /api/rag/ds-kps/<kp_id>` 时，只传 `{name: newName}` 即可（后端其他字段不传时保持原值，因为 UPDATE 语句会把空值写入）。

**修正**：现有后端端点要求 `name` 不能为空但其他字段会被覆盖为空字符串。因此 `startKpEdit` 应先获取当前知识点的完整数据再更新，或者修改后端允许部分更新。

**推荐方案**：修改 `PUT /api/rag/ds-kps/<kp_id>` 的逻辑，对于未传入的字段保持原值（使用 `data.get('xxx')` 并判断是否为 None）：

```python
# rag_routes.py ds_kp_update 函数改动：
with _ds_db_conn() as conn:
    old = conn.execute("SELECT * FROM ds_kps WHERE id=?", (kp_id,)).fetchone()
    if not old:
        return jsonify({'error': f'知识点 {kp_id} 不存在'}), 404

    # 仅在前端显式传入时才更新（允许部分更新）
    name               = data['name'].strip()   if 'name'               in data else old['kp_name']
    content            = data['content'].strip() if 'content'            in data else old['kp_content']
    teaching_focus     = data['teaching_focus'].strip() if 'teaching_focus' in data else (old['teaching_focus'] or '')
    knowledge_type     = data['knowledge_type'].strip() if 'knowledge_type' in data else (old['knowledge_type'] or '')
    cognitive_dimension= data['cognitive_dimension'].strip() if 'cognitive_dimension' in data else (old['cognitive_dimension'] or '')
    relations          = data['relations']       if 'relations'          in data else _json_mod.loads(old['relations_json'] or '[]')
    # ... 其余不变 ...
```

### 5.5 新增 CSS（style 块中添加）

```css
/* 章节/知识点列表编辑按钮 */
.rag-chapter-item {
    display: flex;
    align-items: flex-start;
    gap: 4px;
}
.rag-edit-btn {
    visibility: hidden;
    background: none;
    border: none;
    cursor: pointer;
    color: #aaa;
    font-size: 11px;
    padding: 2px 4px;
    border-radius: 3px;
    line-height: 1;
    margin-top: 3px;
    flex-shrink: 0;
    transition: color 0.15s;
}
.rag-chapter-item:hover .rag-edit-btn,
.rag-section-item:hover .rag-edit-btn { visibility: visible; }
.rag-edit-btn:hover { color: #4a90d9; background: #e8f0fe; }
.rag-name-input {
    font-size: 0.82rem;
    padding: 1px 5px;
    border: 1px solid #4a90d9;
    border-radius: 3px;
    width: 100%;
    min-width: 80px;
}
```

---

## 6. 知识点 `PUT` 接口的部分更新问题

**问题**：当前 `PUT /api/rag/ds-kps/<kp_id>` 要求传入所有字段（`name`/`content`/`relations`/...），若只传 `name`，其他字段会被设为空。

**解决方案**：修改后端逻辑支持"部分更新"（见 §5.4 代码片段）。改动约 10 行，不影响现有调用。

---

## 7. 实施步骤清单

1. **后端**：`rag_routes.py` → `ds_doc_kps()` 在 `chapters_list` 中新增 `'doc_id': doc_id`（约 1 行）
2. **后端**：`rag_routes.py` → 新增 `update_ds_chapter()` 路由函数（约 30 行）
3. **后端**：`rag_routes.py` → `ds_kp_update()` 改为支持部分更新（约 10 行）
4. **前端 JS**：修改 `renderRagChapterList`，将 `<label>` 包裹到 `<div class="rag-chapter-item">` 并添加编辑按钮（约 15 行改动）
5. **前端 JS**：修改 `renderRagSectionList`，在每条知识点后添加编辑按钮（约 5 行改动）
6. **前端 JS**：新增 `startChapterEdit()` 函数（约 50 行）
7. **前端 JS**：新增 `startKpEdit()` 函数（约 50 行）
8. **前端 JS**：新增 `showRagToast()` 工具函数（约 10 行，或复用全局 toast）
9. **前端 CSS**：添加 `.rag-chapter-item`、`.rag-edit-btn`、`.rag-name-input` 样式（约 25 行）
10. **测试**：修改章节名 → 验证 `ds_kps.chapter_name` 同步更新 → 重新加载章节列表确认持久化

---

## 8. 涉及文件

| 文件 | 修改内容 |
|---|---|
| `app/rag_routes.py` | 新增 `PUT /api/rag/ds-chapters` 路由；`ds_doc_kps` 响应新增 `doc_id`；`ds_kp_update` 改为部分更新 |
| `app/templates/index.html` | `renderRagChapterList` + `renderRagSectionList` 改动；新增 `startChapterEdit` / `startKpEdit` / `showRagToast` JS 函数；新增 CSS |

**预计工作量**：后端约 45 行，前端约 150 行。
