"""
测试脚本：从题库随机挑选题目，导出为 muban_zh.xlsx 格式
用法: python test_export_xlsx.py
"""
import sqlite3, json, re, shutil, os
from datetime import datetime
from openpyxl import load_workbook

DB_PATH = "exam_system.db"
TEMPLATE = "muban_zh.xlsx"
OUTPUT = f"test_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

# 各题型默认分值
SCORE_CONFIG = {
    "单选": 1.5,
    "多选": 2,
    "是非": 1,
    "简答": 5,
    "简答>计算": 5,
    "简答>论述": 5,
    "简答>材料分析": 5,
}

SHARE_SCOPE = "仅自己"

# ── 转换函数 ──────────────────────────────────────────

TYPE_MAP = {
    "单选": "单选题",
    "多选": "多选题",
    "是非": "判断题",
    "简答": "简答题",
    "简答>计算": "简答题",
    "简答>论述": "简答题",
    "简答>材料分析": "简答题",
}

DIFFICULTY_MAP = {
    "easy": 2,
    "medium": 3,
    "hard": 4,
}

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text.strip()

def convert_answer(q_type, answer, reference_answer):
    """将本系统答案格式转为模板格式"""
    if q_type == "是非":
        if answer == "正确":
            return "true"
        elif answer == "错误":
            return "false"
        return answer or ""
    if q_type == "多选":
        # 'ABD' → 'A;B;D'
        if answer:
            return ";".join(list(answer.strip()))
        return ""
    if q_type in ("简答", "简答>计算", "简答>论述", "简答>材料分析"):
        return strip_html(reference_answer or answer or "")
    # 单选：直接返回
    return answer or ""

def convert_tags(tags, knowledge_point):
    parts = []
    if knowledge_point:
        parts.append(knowledge_point.strip())
    if tags:
        for t in tags.split(","):
            t = t.strip()
            if t and t not in parts:
                parts.append(t)
    if not parts:
        return ""
    return "".join(f"#{p}" for p in parts[:3])

def convert_difficulty(difficulty):
    return DIFFICULTY_MAP.get(difficulty, 3)

# ── 读取题目 ──────────────────────────────────────────

def fetch_questions(limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # 每种题型各取几道，尽量覆盖
    rows = []
    for qtype in ["单选", "多选", "是非", "简答", "简答>论述"]:
        cur.execute(
            "SELECT * FROM questions WHERE question_type=? LIMIT ?",
            (qtype, max(2, limit // 5))
        )
        rows.extend(cur.fetchall())
    conn.close()
    return rows[:limit]

# ── 生成 Excel ────────────────────────────────────────

def export(questions):
    # 复制模板（保留第1-3行格式）
    shutil.copy(TEMPLATE, OUTPUT)
    wb = load_workbook(OUTPUT)
    ws = wb.active

    # 清空第4行及以后的数据（模板里的示例行）
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
        for cell in row:
            cell.value = None

    row_idx = 4
    for seq, q in enumerate(questions, start=1):
        q_type = q["question_type"]
        options = json.loads(q["options"]) if q["options"] else []
        answer = convert_answer(q_type, q["answer"], q["reference_answer"])
        tags = convert_tags(q["tags"], q["knowledge_point"])
        difficulty = convert_difficulty(q["difficulty"])
        score = SCORE_CONFIG.get(q_type, 2)
        type_label = TYPE_MAP.get(q_type, "简答题")
        stem = strip_html(q["content"])
        explanation = strip_html(q["explanation"] or "")

        def cap(v):
            return v[:500] if isinstance(v, str) else v

        ws.cell(row=row_idx, column=1).value = str(seq)        # 序号
        ws.cell(row=row_idx, column=2).value = type_label      # 题型
        ws.cell(row=row_idx, column=3).value = score           # 分值
        ws.cell(row=row_idx, column=4).value = difficulty      # 难度
        ws.cell(row=row_idx, column=5).value = SHARE_SCOPE     # 共享范围
        ws.cell(row=row_idx, column=6).value = cap(tags)       # 标签
        # G列（综合题材料）留空
        ws.cell(row=row_idx, column=8).value = cap(stem)       # 题干
        answer_clean = answer.replace('\n', ' ').replace('\r', '')
        ws.cell(row=row_idx, column=9).value = cap(answer_clean)  # 正确答案
        ws.cell(row=row_idx, column=10).value = cap(explanation)  # 答案解析

        # 选项 A-O → 列 11-25
        for i, opt in enumerate(options[:15]):
            ws.cell(row=row_idx, column=11 + i).value = cap(strip_html(opt))

        row_idx += 1

    wb.save(OUTPUT)
    return row_idx - 4  # 实际写入行数

# ── 主程序 ───────────────────────────────────────────

if __name__ == "__main__":
    questions = fetch_questions(limit=20)
    count = export(questions)
    print(f"导出完成：{count} 道题 → {OUTPUT}")

    # 打印摘要
    from collections import Counter
    type_counter = Counter(q["question_type"] for q in questions)
    for t, n in type_counter.items():
        print(f"  {t}: {n} 道")
