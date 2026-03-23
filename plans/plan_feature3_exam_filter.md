# 功能规划文档 3：一键出题增加详细筛选条件

**版本**：v1.0
**日期**：2026-03-23
**涉及功能**：组卷管理 Tab → 一键自动组卷 → 增加难度/知识点/标签等多维度筛选

---

## 1. 需求背景

当前"一键自动组卷"（`POST /api/exams/generate`）只支持：
- 科目（`subject`）
- 题型 + 每种题型的数量和分值

**不支持**：
- 难度筛选（easy/medium/hard）
- 知识点关键词筛选
- 标签筛选（重点/难点/考点 等用户自定义标签）

导致组卷时无法精确控制题目质量，例如：
- 无法只组一套"全难题"的测验
- 无法只取"考点"标签的题目出最后一套复习题
- 无法按知识点精确出题

**目标**：在一键组卷的配置区域增加多维度筛选条件，支持灵活组合筛选。

---

## 2. 现有架构分析

### 2.1 题库字段（QuestionModel）— 可用于筛选的字段

| 字段名 | 类型 | 当前值域 |
|---|---|---|
| `difficulty` | String(32) | `easy` / `medium` / `hard` / `''`（空） |
| `knowledge_point` | String(256) | 自由文本，如"马克思主义政治经济学" |
| `tags` | String(512) | 逗号分隔标签，如"重点,考点"或"重点" |
| `subject` | String(128) | 学科名 |
| `is_used` | Boolean | 是否已使用 |

### 2.2 当前组卷逻辑（routes.py:942）

```python
q_query = QuestionModel.query.filter(
    db.func.trim(QuestionModel.question_type) == question_type.strip(),
    QuestionModel.is_used == False
)
if subject_filter:
    q_query = q_query.filter(QuestionModel.subject == subject_filter)
available = q_query.order_by(db.func.random()).limit(count).all()
```

只有一层 `subject` 过滤，其余全随机。

### 2.3 难度值的中文映射

前端展示时需将英文映射为中文：
```javascript
const DIFFICULTY_LABELS = { '': '不限', 'easy': '简单', 'medium': '中等', 'hard': '困难' };
```

---

## 3. 后端变更

### 3.1 `POST /api/exams/generate` 接口扩展

**位置**：`app/routes.py` → `generate_exam()` 函数

**新增请求体参数**：
```json
{
  "name": "试卷名称",
  "config": {
    "单选题": { "count": 10, "score": 2 },
    "简答题": { "count": 3, "score": 10 }
  },
  "subject": "数据结构",

  // === 新增筛选参数 ===
  "difficulty": "medium",          // 可选：''(不限)|'easy'|'medium'|'hard'
  "knowledge_point": "排序算法",    // 可选：知识点关键词（模糊匹配）
  "tags": ["重点", "考点"],          // 可选：标签列表，满足其中任意一个即入选
  "is_used_filter": "unused"        // 可选：'unused'(未用)|'used'(已用)|''(全部，默认unused)
}
```

**后端处理逻辑（扩展部分）**：
```python
@bp.route('/api/exams/generate', methods=['POST'])
def generate_exam():
    data = request.json
    subject_filter = data.get('subject') or None
    difficulty_filter = data.get('difficulty', '').strip()       # 新增
    kp_filter = data.get('knowledge_point', '').strip()          # 新增
    tags_filter = data.get('tags', [])                           # 新增：list
    is_used_filter = data.get('is_used_filter', 'unused')        # 新增，默认只用未用题

    # ... 创建 ExamModel 代码不变 ...

    for question_type, settings in config.items():
        count = settings.get('count', 0)

        q_query = QuestionModel.query.filter(
            db.func.trim(QuestionModel.question_type) == question_type.strip(),
        )

        # 是否已使用 筛选
        if is_used_filter == 'unused':
            q_query = q_query.filter(QuestionModel.is_used == False)
        elif is_used_filter == 'used':
            q_query = q_query.filter(QuestionModel.is_used == True)
        # is_used_filter == '' → 不筛选

        # 科目筛选
        if subject_filter:
            q_query = q_query.filter(QuestionModel.subject == subject_filter)

        # 难度筛选（新增）
        if difficulty_filter:
            q_query = q_query.filter(QuestionModel.difficulty == difficulty_filter)

        # 知识点关键词筛选（新增，模糊匹配）
        if kp_filter:
            q_query = q_query.filter(
                QuestionModel.knowledge_point.ilike(f'%{kp_filter}%')
            )

        # 标签筛选（新增，OR 关系：含任意一个标签即入选）
        if tags_filter:
            tag_conditions = [
                QuestionModel.tags.ilike(f'%{tag}%')
                for tag in tags_filter if tag.strip()
            ]
            if tag_conditions:
                q_query = q_query.filter(db.or_(*tag_conditions))

        available = q_query.order_by(db.func.random()).limit(count).all()
        # ... 添加到试卷代码不变 ...
```

### 3.2 `GET /api/questions/tags` — 新增：获取所有已用标签列表

为前端标签筛选器提供自动补全数据源。

```python
@bp.route('/api/questions/tags', methods=['GET'])
def get_all_tags():
    """获取题库中所有唯一标签"""
    rows = db.session.execute(
        db.select(QuestionModel.tags).filter(QuestionModel.tags != '')
    ).scalars().all()

    tag_set = set()
    for tags_str in rows:
        if tags_str:
            for t in tags_str.split(','):
                t = t.strip()
                if t:
                    tag_set.add(t)

    return jsonify(sorted(tag_set))
```

---

## 4. 前端变更（app/templates/index.html）

### 4.1 UI 布局设计

在现有"组卷科目"选择框下方，增加"高级筛选"展开区域（默认收起，点击展开，节省空间）：

```
┌─────────────────────────────────────────┐
│ 组卷科目：[全部科目 ▼]                    │
│ ▶ 高级筛选条件（点击展开）                 │
│   ┌─────────────────────────────────┐   │
│   │ 难度要求：[不限 ▼]               │   │
│   │ 知识点：[___________________]   │   │
│   │ 标签筛选：[重点×][考点×][___]   │   │
│   │ 题目状态：(●未用题) ( 已用) (全部) │   │
│   └─────────────────────────────────┘   │
├─────────────────────────────────────────┤
│ [题型配置区域]                             │
│ [+ 添加题型]                              │
│ 试卷总分: 0 分                            │
│ [一键生成试卷]                            │
└─────────────────────────────────────────┘
```

### 4.2 HTML 新增（在 `exam-subject-filter` div 之后，`exam-type-configs` 之前）

```html
<!-- 高级筛选展开区 -->
<div style="margin-bottom:12px;">
    <button id="exam-advanced-toggle" class="btn btn-outline btn-sm"
            onclick="toggleExamAdvanced()" style="font-size:0.85rem;">
        <i class="fas fa-sliders-h"></i> 高级筛选条件
        <i class="fas fa-chevron-down" id="exam-advanced-icon" style="margin-left:4px;"></i>
    </button>
</div>

<div id="exam-advanced-panel" style="display:none; background:#f8f9fa; border:1px solid #e0e0e0;
     border-radius:8px; padding:14px; margin-bottom:15px;">

    <!-- 难度筛选 -->
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap;">
        <label style="font-weight:500; min-width:70px;">
            <i class="fas fa-tachometer-alt"></i> 难度要求：
        </label>
        <select id="exam-difficulty-filter"
                style="padding:6px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.9rem;">
            <option value="">不限难度</option>
            <option value="easy">简单</option>
            <option value="medium">中等</option>
            <option value="hard">困难</option>
        </select>
    </div>

    <!-- 知识点关键词 -->
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap;">
        <label style="font-weight:500; min-width:70px;">
            <i class="fas fa-brain"></i> 知识点：
        </label>
        <input type="text" id="exam-kp-filter" placeholder="输入知识点关键词（模糊匹配）"
               style="flex:1; min-width:200px; padding:6px 12px; border:1px solid #ddd;
                      border-radius:6px; font-size:0.9rem;">
    </div>

    <!-- 标签筛选（多选，chip 样式） -->
    <div style="display:flex; align-items:flex-start; gap:10px; margin-bottom:10px; flex-wrap:wrap;">
        <label style="font-weight:500; min-width:70px; padding-top:4px;">
            <i class="fas fa-tags"></i> 标签筛选：
        </label>
        <div id="exam-tags-container" style="flex:1;">
            <!-- 预设常用标签 -->
            <div id="exam-tags-preset" style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px;">
                <button class="exam-tag-chip" data-tag="重点" onclick="toggleExamTag(this)">重点</button>
                <button class="exam-tag-chip" data-tag="难点" onclick="toggleExamTag(this)">难点</button>
                <button class="exam-tag-chip" data-tag="考点" onclick="toggleExamTag(this)">考点</button>
            </div>
            <!-- 已选标签展示 + 自定义输入 -->
            <div id="exam-tags-selected" style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                <input type="text" id="exam-tag-input" placeholder="输入自定义标签，回车添加"
                       style="padding:4px 8px; border:1px solid #ccc; border-radius:4px; font-size:0.85rem; width:180px;"
                       onkeydown="onExamTagInputKeydown(event)">
            </div>
            <div style="font-size:0.78rem; color:#888; margin-top:4px;">
                多个标签为 OR 关系（满足任意一个标签即入选）
            </div>
        </div>
    </div>

    <!-- 题目状态（未使用/已使用/全部） -->
    <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
        <label style="font-weight:500; min-width:70px;">
            <i class="fas fa-check-circle"></i> 题目状态：
        </label>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
            <input type="radio" name="exam-is-used" value="unused" checked> 仅未使用题目
        </label>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
            <input type="radio" name="exam-is-used" value="used"> 仅已使用题目
        </label>
        <label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
            <input type="radio" name="exam-is-used" value=""> 全部题目
        </label>
    </div>

    <!-- 可用题目数量实时预估 -->
    <div id="exam-available-count" style="margin-top:10px; font-size:0.85rem; color:#555;">
        <!-- JS 动态填充：当前条件下可用题目约 N 道 -->
    </div>
</div>
```

### 4.3 CSS 新增（style 块中添加）

```css
.exam-tag-chip {
    padding: 3px 10px; border-radius: 12px; border: 1px solid #aaa;
    background: #fff; cursor: pointer; font-size: 0.82rem; transition: all 0.15s;
}
.exam-tag-chip.active {
    background: var(--primary-color); color: #fff; border-color: var(--primary-color);
}
.exam-tag-selected-item {
    display: inline-flex; align-items: center; gap: 3px; padding: 3px 8px;
    background: #e3f0ff; border: 1px solid #99c1f1; border-radius: 12px;
    font-size: 0.82rem; color: #1a73e8;
}
.exam-tag-selected-item .remove-tag {
    cursor: pointer; color: #888; font-size: 0.8rem; margin-left: 2px;
}
.exam-tag-selected-item .remove-tag:hover { color: #e00; }
```

### 4.4 JS 新增函数

```javascript
// === 高级筛选面板控制 ===
let examAdvancedOpen = false;
function toggleExamAdvanced() {
    examAdvancedOpen = !examAdvancedOpen;
    document.getElementById('exam-advanced-panel').style.display = examAdvancedOpen ? 'block' : 'none';
    document.getElementById('exam-advanced-icon').className =
        examAdvancedOpen ? 'fas fa-chevron-up' : 'fas fa-chevron-down';
}

// === 标签管理 ===
const examSelectedTags = new Set();

function toggleExamTag(btn) {
    const tag = btn.dataset.tag;
    if (examSelectedTags.has(tag)) {
        examSelectedTags.delete(tag);
        btn.classList.remove('active');
    } else {
        examSelectedTags.add(tag);
        btn.classList.add('active');
    }
    renderSelectedTags();
    updateExamAvailableCount();
}

function onExamTagInputKeydown(e) {
    if (e.key === 'Enter') {
        const val = e.target.value.trim();
        if (val) {
            examSelectedTags.add(val);
            e.target.value = '';
            renderSelectedTags();
            updateExamAvailableCount();
        }
    }
}

function renderSelectedTags() {
    const container = document.getElementById('exam-tags-selected');
    // 保留 input 元素
    const input = document.getElementById('exam-tag-input');
    container.innerHTML = '';
    examSelectedTags.forEach(tag => {
        // 如果不是预设标签才显示在 selected 区（预设标签已经有 chip 样式）
        if (!['重点', '难点', '考点'].includes(tag)) {
            const item = document.createElement('span');
            item.className = 'exam-tag-selected-item';
            item.innerHTML = `${tag}<span class="remove-tag" onclick="removeExamTag('${tag}')">×</span>`;
            container.appendChild(item);
        }
    });
    container.appendChild(input);
}

function removeExamTag(tag) {
    examSelectedTags.delete(tag);
    renderSelectedTags();
    updateExamAvailableCount();
}

// === 实时预估可用题目数量 ===
let availableCountTimer = null;
function updateExamAvailableCount() {
    clearTimeout(availableCountTimer);
    availableCountTimer = setTimeout(async () => {
        const params = new URLSearchParams({
            subject: document.getElementById('exam-subject-filter').value || '',
            difficulty: document.getElementById('exam-difficulty-filter').value || '',
            knowledge_point: document.getElementById('exam-kp-filter').value || '',
            is_used: document.querySelector('input[name="exam-is-used"]:checked').value === 'unused' ? '0' : '',
        });
        if (examSelectedTags.size > 0) {
            params.set('tags', [...examSelectedTags].join(','));
        }
        try {
            const res = await fetch('/api/questions/count?' + params);
            const data = await res.json();
            document.getElementById('exam-available-count').textContent =
                `当前筛选条件下题库中共有 ${data.count} 道可用题目`;
        } catch {
            document.getElementById('exam-available-count').textContent = '';
        }
    }, 500);
}

// 绑定筛选控件变化事件（在 DOM 就绪后）
['exam-subject-filter', 'exam-difficulty-filter', 'exam-kp-filter'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updateExamAvailableCount);
    if (el) el.addEventListener('input', updateExamAvailableCount);
});
document.querySelectorAll('input[name="exam-is-used"]').forEach(r => {
    r.addEventListener('change', updateExamAvailableCount);
});
```

### 4.5 修改 generateExam 函数（传递新参数）

```javascript
document.getElementById('generate-exam-btn').addEventListener('click', async () => {
    const config = getExamConfig();
    const examSubject = document.getElementById('exam-subject-filter').value;
    // 新增筛选参数
    const difficulty = document.getElementById('exam-difficulty-filter').value;
    const knowledgePoint = document.getElementById('exam-kp-filter').value.trim();
    const tags = [...examSelectedTags];
    const isUsedFilter = document.querySelector('input[name="exam-is-used"]:checked').value;

    const subjectSuffix = examSubject ? `_${examSubject}` : '';
    const examData = {
        name: `自动组卷${subjectSuffix}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}`,
        config: config,
        subject: examSubject || null,
        // 新增
        difficulty: difficulty || '',
        knowledge_point: knowledgePoint || '',
        tags: tags,
        is_used_filter: isUsedFilter,
    };

    // ... 其余不变 ...
});
```

---

## 5. 新增 API：题目数量预估

**新端点**：`GET /api/questions/count`
**位置**：`app/routes.py`
**作用**：供前端实时预估当前筛选条件下可用题目数量（不返回题目内容，只返回 count）

```python
@bp.route('/api/questions/count', methods=['GET'])
def count_questions():
    subject = request.args.get('subject', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    kp = request.args.get('knowledge_point', '').strip()
    tags_str = request.args.get('tags', '').strip()
    is_used = request.args.get('is_used', '')

    q = QuestionModel.query
    if subject:
        q = q.filter(QuestionModel.subject == subject)
    if difficulty:
        q = q.filter(QuestionModel.difficulty == difficulty)
    if kp:
        q = q.filter(QuestionModel.knowledge_point.ilike(f'%{kp}%'))
    if tags_str:
        tags_list = [t.strip() for t in tags_str.split(',') if t.strip()]
        if tags_list:
            q = q.filter(db.or_(*[QuestionModel.tags.ilike(f'%{t}%') for t in tags_list]))
    if is_used == '0':
        q = q.filter(QuestionModel.is_used == False)
    elif is_used == '1':
        q = q.filter(QuestionModel.is_used == True)

    return jsonify({'count': q.count()})
```

---

## 6. 筛选规则说明

| 筛选项 | 匹配方式 | 说明 |
|---|---|---|
| 科目 | 精确匹配 | `subject == 'XXX'`，空则不限 |
| 难度 | 精确匹配 | `difficulty == 'easy/medium/hard'`，空则不限 |
| 知识点 | 模糊匹配 | `knowledge_point ILIKE '%keyword%'`，空则不限 |
| 标签 | 模糊 OR | `tags LIKE '%重点%' OR tags LIKE '%考点%'`，空则不限 |
| 题目状态 | 精确匹配 | `is_used == True/False`，默认只取未使用 |
| 多个条件 | AND 组合 | 所有非空筛选条件以 AND 联合（标签内部是 OR） |

---

## 7. 涉及文件

| 文件 | 修改内容 |
|---|---|
| `app/routes.py` | 扩展 `generate_exam()` 函数，新增 `count_questions()` 和 `get_all_tags()` |
| `app/templates/index.html` | 高级筛选 HTML 面板 + 标签 chip JS + generateExam 传参修改 + CSS |

**预计工作量**：后端约 50 行，前端约 150 行。

---

## 8. 功能演示场景

**场景 1：生成一套专攻"重点"知识的中等难度单选题**
1. 科目：数据结构
2. 展开高级筛选 → 难度：中等 → 点击"重点" chip
3. 配置：单选题 × 20道
4. 点击生成

**场景 2：针对某章节知识点专项练习**
1. 知识点关键词：`排序算法`
2. 题目状态：全部
3. 配置：简答题 × 5道
4. 生成前可见预估："当前筛选条件下共有 12 道可用题目"
