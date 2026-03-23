# 题库 xlsx 导入功能规划

> 版本目标: v1.13.0
> 分支: ds-text-only
> 日期: 2026-03-22

---

## 背景

现有导入仅支持 `.docx` 和 `.txt`。题库导出已支持 xlsx（muban_zh.xlsx 模板），需补全逆向的 xlsx 导入功能。

测试文件：`我的题库_管理研究方法_图谱题库_2026-03-21.xlsx`（72题，单选/多选/判断三类，无标签无解析）

---

## 文件结构兼容两种格式

| 格式 | 标题行位置 | 数据起始行 | 说明 |
|------|-----------|-----------|------|
| 本系统导出（muban_zh.xlsx）| Row 3 | Row 4 | 前2行为说明文字 |
| 外部题库（如测试文件） | Row 1 | Row 2 | 直接从标题行开始 |

检测方式：从第1行到第5行，找包含 `"题干"` 字样的行，该行即为标题行。

---

## 列映射（25列）

| 列号 | 字段 | 导入处理 |
|------|------|---------|
| 2 | 题型 | 反向 `_XLSX_TYPE_REVERSE` 映射 |
| 4 | 难度 | 1-2→easy, 3→medium, 4-5→hard |
| 6 | 标签 | `#tag1#tag2` → `knowledge_point=tag1, tags=tag2,...` |
| 8 | 题干 | → `content` |
| 9 | 正确答案 | 按题型规范化（见下表） |
| 10 | 答案解析 | → `explanation` |
| 11-25 | 选项A-O | 非空的 → `options[]` (JSON array) |

### 答案规范化

| 题型 | xlsx中格式 | 导入后格式 | 字段 |
|------|-----------|-----------|------|
| 单选 | `D` | `D`（大写） | `answer` |
| 多选 | `A,B` / `A;B` / `AB` | `AB`（无分隔符） | `answer` |
| 判断 | `正确`/`错误`/`true`/`false` | `正确`/`错误` | `answer` |
| 简答 | 文本 | 文本 | `reference_answer` |

---

## 实现方案

### 1. routes.py 新增

**① 反向映射常量**（放在现有 `_XLSX_TYPE_MAP` 附近）：
```python
_XLSX_TYPE_REVERSE = {
    "单选题": "单选", "多选题": "多选", "判断题": "是非",
    "简答题": "简答", "计算题": "简答>计算",
    "论述题": "简答>论述", "材料分析题": "简答>材料分析",
}
```

**② 辅助函数**：
```python
def _xlsx_diff_from_num(n)  # 数字难度 → 字符串
def _xlsx_parse_tags(tag_str)  # '#tag1#tag2' → (kp, tags)
def _xlsx_normalize_answer(q_type, raw)  # → (answer, reference_answer)
def _parse_xlsx_questions(file_path)  # → (questions_list, errors_list)
```

**③ 在 `import_questions()` 中增加 xlsx 分支**（在 `.txt` 分支之后）：
```python
elif file.filename.lower().endswith('.xlsx'):
    questions_data, parse_errors = _parse_xlsx_questions(file_path)
    # 同 docx 分支的去重 + model 构建逻辑
    # failed = len(parse_errors)
```

**④ `allowed_file()` 添加 `.xlsx`**

### 2. index.html 修改

**① 题库tab的"导入"按钮** — 修改 `accept` 属性：
```html
accept=".docx,.txt,.xlsx"
```

**② 导入成功提示** — 已有逻辑，无需改动（通用 `imported/skipped` 显示）

---

## 去重机制

与现有 docx/txt 导入保持一致：
- 对比 `content.strip()` 是否已存在于数据库
- 同批次内也去重（防止文件内重复）
- 跳过的计入 `skipped` 计数

---

## 错误处理

- 未知题型 → 跳过该行，计入 `failed`
- 题干为空 → 跳过该行
- 未找到标题行 → 抛出异常，返回 500
- openpyxl 未安装 → 返回友好错误

---

## 测试验证

测试文件：`我的题库_管理研究方法_图谱题库_2026-03-21.xlsx`
- 期望结果：imported=72, skipped=0, failed=0
- 验证：单选答案 `D`，多选答案 `AB`，判断答案 `正确`/`错误`

测试脚本：`test_xlsx_import.py`（已验证通过）

---

## 涉及文件

| 文件 | 修改内容 |
|------|---------|
| `app/routes.py` | 添加常量、4个辅助函数、xlsx分支、allowed_file扩展 |
| `app/templates/index.html` | 导入input的accept属性加 `.xlsx` |
