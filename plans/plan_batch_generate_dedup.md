# 分批出题查重与拼接优化

## 背景

分批出题时，每批随机采样知识点，不同批可能采样到相同知识点，导致最终结果中出现重复或相似题目。需要在拼接各批结果时做查重处理。

## 当前分批出题流程（已实现）

```
用户设置：分几批（batch_count，默认3）
    ↓
每批：按该批题目数随机采样知识点（_sample_kps_with_relations）
    ↓
每批独立构造 prompt → 并行发给 DeepSeek → 得到各批原始文本
    ↓
直接拼接，输出到结果框（无查重）
```

## 目标

在拼接各批结果之前，对生成的题目做查重，去掉重复或高度相似的题目，再拼接成最终结果。

---

## 实施方案

### 1. 题目解析（后端）

各批返回的是 Markdown 格式文本，需要先把各批文本解析成独立题目列表，再查重。

解析规则（参考现有 `ragSaveEdit` 前端解析逻辑，迁移到后端）：
- 以空行+序号（`1.`、`一、`、`（1）`等）或 `---` 为题目分隔符
- 每道题保留原始文本块

### 2. 查重策略

**简单查重（优先实现）**：
- 提取每道题的题干（去除选项、答案、解析部分）
- 计算题干的字符集相似度（Jaccard 相似度，基于字符 n-gram）
- 相似度 > 0.7 则认为重复，保留先出现的那道

**可选增强**：
- 用 `difflib.SequenceMatcher` 替代 Jaccard，对短文本更准确
- 阈值做成参数（默认 0.7）

### 3. 拼接结果

去重后的题目重新编号，按批次标注来源（可选），输出完整 Markdown。

---

## 代码改动点

### 后端 `rag_routes.py`

**新增辅助函数**（在 `_run()` 外部或内部均可）：

```python
def _parse_questions(text):
    """将一批 Markdown 出题结果拆分为题目列表（每项为原始文本块）。"""
    ...

def _jaccard_sim(a, b, n=3):
    """字符 n-gram Jaccard 相似度。"""
    set_a = {a[i:i+n] for i in range(len(a)-n+1)}
    set_b = {b[i:i+n] for i in range(len(b)-n+1)}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)

def _dedup_questions(all_questions, threshold=0.7):
    """对题目列表去重，返回去重后列表。"""
    seen = []
    result = []
    for q in all_questions:
        stem = _extract_stem(q)  # 只取题干部分
        if all(_jaccard_sim(stem, s) < threshold for s in seen):
            seen.append(stem)
            result.append(q)
    return result
```

**修改 `_run()` 中的拼接逻辑**：

在 `merged_parts` 拼接之前，先调用解析+去重：

```python
# 收集所有批次的题目
all_questions = []
for idx in range(batch_count):
    content, chars, ok, err = results.get(idx, (None, 0, False, '未收到结果'))
    if ok:
        all_questions.extend(_parse_questions(content))

# 查重
deduped = _dedup_questions(all_questions)

# 重新编号后拼接
merged = _renumber_questions(deduped)
```

stats 中新增 `dedup_removed` 字段，记录去掉了多少道重复题。

### 前端 `index.html`

- 完成提示文字加上去重信息：`生成完成！共 N 批，去重后保留 X 道题（移除 Y 道重复）。`
- 无需 UI 改动，查重默认开启

---

## 实施顺序

1. 实现 `_extract_stem()`（去掉选项/答案行，只保留题干）
2. 实现 `_parse_questions()`（按分隔符拆题）
3. 实现 `_jaccard_sim()` + `_dedup_questions()`
4. 修改 `_run()` 拼接逻辑（普通分批 + 稀疏模式两处）
5. 更新前端完成提示，加入去重统计
6. 测试：用同一批内容重复两次模拟重复，验证去重效果

---

## 注意事项

- `_parse_questions()` 是最难的部分，因为 DeepSeek 输出格式不完全统一，需要做多种分隔符的兜底处理
- 去重阈值 0.7 是初始值，实测后可能需要调整
- 非分批模式不需要查重（只有一次 API 调用，不存在跨批重复）
- 稀疏模式（sparse_mode）和普通分批模式都需要加查重
