# 简化版面试套题模板导入 - 实施规划

> 分析日期：2026-03-29  
> 更新日期：2026-03-29（添加导出简化模板功能）  
> 目标文件：`C:\Users\langx\Desktop\面试套题模板_简化.xlsx`

---

## 一、模板分析

### 1.1 文件结构

| 工作表 | 存在性 | 说明 |
|--------|--------|------|
| 套题列表 | ✅ | 有，单表结构 |
| 题目详情 | ❌ | 无 |

### 1.2 表头结构

```
[0] set_code
[1] 槽位1-简答
[2] 槽位2-简答>论述
[3] 槽位3-简答
```

**特点**：
- 列标题格式：`槽位N-题型名`
- 每道题的内容直接填在单元格中（不是题目ID）
- 题型名从列标题提取

### 1.3 数据示例

| set_code | 槽位1-简答 | 槽位2-简答>论述 | 槽位3-简答 |
|----------|-----------|----------------|-----------|
| SET-001 | 农产品的成本构成... | 试分析"粮食生产能力... | What do you think... |
| SET-002 | 什么是价格弹性... | 在价格同时变动情况下... | How would you evaluate... |

---

## 二、导出模板功能（已修改）

### 2.1 界面变更

在题型设置面板的配置卡片上，原来的「导出模板」按钮已改为两个按钮：

```html
<button onclick="ivExportTemplate(poolId, configId, true)">
    <i class="fas fa-file-alt"></i> 导出简化模板
</button>
<button onclick="ivExportTemplate(poolId, configId, false)">
    <i class="fas fa-file-excel"></i> 导出通用模板
</button>
```

| 按钮 | 功能 | 导出内容 |
|------|------|----------|
| 导出简化模板 | `simplified=1` | 只有「套题列表」，题目内容直接填单元格（列宽60） |
| 导出通用模板 | `simplified=0` | 「套题列表」+「题目详情」两个表（原有格式） |

### 2.2 API 变更

**文件**: `app/interview_routes.py`

```python
GET /api/interview/pools/<int:pool_id>/config/<int:config_id>/export-template?simplified=0|1
```

**新增参数**: `simplified`
- `simplified=0` (默认): 通用模板，包含两个工作表
- `simplified=1`: 简化模板，只有套题列表，列宽60方便填写

---

## 三、导入功能规划

### 3.1 模板类型检测策略

通过以下特征判断是否为简化版模板：

```python
def detect_template_type(wb):
    """
    返回: 'simplified' | 'full' | 'unknown'
    """
    # 1. 检查工作表数量
    if len(wb.sheetnames) == 1 and wb.sheetnames[0] == '套题列表':
        ws = wb['套题列表']
        headers = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
        
        # 2. 检查表头是否包含"槽位N-题型"格式
        slot_pattern = re.compile(r'槽位\d+-.+')
        slot_cols = [h for h in headers[1:] if h and slot_pattern.match(str(h))]
        
        if slot_cols:
            return 'simplified'
    
    # 3. 完整版模板特征：有"题目详情"表或set_code列内容是ID
    if '题目详情' in wb.sheetnames:
        return 'full'
    
    return 'unknown'
```

### 3.2 导入流程设计

```
1. 检测模板类型 → 'simplified'
2. 解析套题列表表头 → 提取槽位配置 [{col: 1, type: '简答'}, ...]
3. 创建/获取题库池（如未指定）
4. 遍历每行（每套题）:
   a. 读取set_code
   b. 遍历每个槽位:
      i.   读取单元格内容
      ii.  匹配/创建题型
      iii. 创建新题目（内容直接存为简答题）
      iv.  题目加入题库池
      v.   收集question_id
   c. 创建套题记录
5. 返回导入结果
```

### 3.3 数据映射

| Excel 列 | 题目字段 | 处理方式 |
|----------|----------|----------|
| 单元格内容 | content | 直接存储 |
| 题型名 | question_type | 匹配/创建题型 |
| set_code | set_code | 生成套题编号 |
| - | subject | 默认"面试题库"或用户指定 |
| - | difficulty | 默认"medium" |
| - | options | 空数组（简答题） |
| - | answer | 空字符串 |
| - | reference_answer | 空字符串 |

---

## 四、API 设计

### 4.1 自动检测导入（推荐）

修改现有导入接口，自动检测模板类型：

```python
@interview_bp.route('/api/interview/sessions/import-xlsx', methods=['POST'])
@login_required
def import_sets_xlsx():
    """
    导入套题（自动检测模板类型）
    - 完整版：原有逻辑
    - 简化版：新逻辑
    """
```

### 4.2 新增独立接口（备选）

```python
@interview_bp.route('/api/interview/sessions/import-simplified-xlsx', methods=['POST'])
@login_required
def import_simplified_sets_xlsx():
    """
    导入简化版套题模板
    
    参数:
        - session_name: 场次名称（必填）
        - pool_id: 题库池ID（可选，默认新建）
        - file: Excel文件
    
    返回:
        {
            "ok": true,
            "session_id": 123,
            "session_name": "2024春面试",
            "pool_id": 5,
            "pool_name": "农业经济学面试池",
            "sets_imported": 7,
            "questions_created": 21,
            "questions_added_to_pool": 21,
            "types_created": ["简答>论述"],
            "slots": ["简答", "简答>论述", "简答"]
        }
    """
```

---

## 五、实施步骤

### 已完成 ✅

| 步骤 | 任务 | 文件 |
|------|------|------|
| ✅ | 修改导出模板API，添加simplified参数 | `app/interview_routes.py` |
| ✅ | 修改前端，两个导出按钮 | `app/templates/index.html` |
| ✅ | 更新导出模板函数 | `app/templates/index.html` |

### 待实施 📋

| 优先级 | 任务 | 预计时间 |
|--------|------|----------|
| P0 | 模板类型检测函数 | 30分钟 |
| P0 | 槽位解析函数 | 30分钟 |
| P0 | 简化版导入核心逻辑 | 2小时 |
| P1 | 修改现有导入接口 | 30分钟 |
| P1 | 前端界面调整 | 30分钟 |
| P2 | 单元测试 | 1小时 |
| P2 | 集成测试 | 30分钟 |

**总计**: 约 5-6 小时

---

## 六、关键代码实现

### 6.1 槽位解析

```python
def _parse_simplified_slots(headers):
    """
    从简化版表头解析槽位配置
    
    输入: ['set_code', '槽位1-简答', '槽位2-简答>论述', ...]
    输出: [
        {'col': 1, 'slot_num': 1, 'question_type': '简答'},
        {'col': 2, 'slot_num': 2, 'question_type': '简答>论述'},
        ...
    ]
    """
    import re
    slots = []
    pattern = re.compile(r'槽位(\d+)-(.+)')
    
    for i, h in enumerate(headers):
        if not h:
            continue
        match = pattern.match(str(h).strip())
        if match:
            slots.append({
                'col': i,
                'slot_num': int(match.group(1)),
                'question_type': match.group(2).strip()
            })
    
    return slots
```

### 6.2 题目创建

```python
def _create_question_from_cell(content, qtype, user, subject='面试题库'):
    """
    从单元格内容创建题目
    """
    from app.routes import _match_question_type, _ensure_question_type, _detect_language
    
    # 匹配/创建题型
    known_types = {...}
    matched_type, _, needs_create = _match_question_type(qtype, known_types)
    
    if needs_create:
        matched_type, _ = _ensure_question_type(qtype, user)
    
    # 创建题目
    question = QuestionModel(
        question_id=f'iv_q_{datetime.now().strftime("%Y%m%d%H%M%S%f")}',
        question_type=matched_type,
        content=str(content).strip(),
        options=json.dumps([], ensure_ascii=False),
        subject=subject,
        difficulty='medium',
        language=_detect_language(str(content), None),
        owner_id=user.id,
        ...
    )
    
    return question
```

---

## 七、测试计划

### 7.1 导出测试

1. 在题型设置面板选择一个配置
2. 点击「导出简化模板」
   - ✅ 下载的文件名包含「简化」
   - ✅ 只有「套题列表」一个工作表
   - ✅ 列宽为60，方便填写
3. 点击「导出通用模板」
   - ✅ 下载的文件名包含「通用」
   - ✅ 包含两个工作表

### 7.2 导入测试

1. 导出简化模板
2. 在模板中填写题目内容
3. 通过导入功能导入
4. 验证：
   - ✅ 正确识别槽位
   - ✅ 创建题目
   - ✅ 题目加入题库池
   - ✅ 套题记录正确生成

---

## 八、注意事项

1. **题型处理**: 简化版模板的题型从列标题提取，需要确保 `_match_question_type` 能正确处理
2. **内容清洗**: 单元格内容可能包含换行符，需要 `strip()` 处理
3. **去重机制**: 建议根据内容哈希进行去重，避免重复创建相同题目
4. **事务处理**: 使用数据库事务确保套题导入的原子性
