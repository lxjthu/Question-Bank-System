"""
app/grading.py
自动评分逻辑：纯函数，无数据库副作用。
由 answer_routes.py 在交卷时调用。
"""

import re


# ── 公开 API ──────────────────────────────────────────────────────────

def auto_grade_question(question, student_answer: str, full_score: float) -> dict:
    """
    对单道题评分。

    Args:
        question:       QuestionModel 实例
        student_answer: 学生作答字符串
        full_score:     该题满分

    Returns:
        {
            'score':      float,
            'is_correct': bool | None,  客观题 True/False；主观题 None
            'method':     str           'exact'/'set'/'partial'/'normalized'/'manual'
        }
    """
    q_type = (question.question_type or '').strip()
    correct = (question.answer or '').strip()
    student = (student_answer or '').strip()

    if q_type in ('单选', '是非'):
        return _grade_single(correct, student, full_score)

    if q_type == '多选':
        return _grade_multi(correct, student, full_score)

    if q_type == '填空':
        return _grade_fill(correct, student, full_score)

    # 简答、论述、计算、材料分析等主观题 → 标记人工批改
    return {'score': 0.0, 'is_correct': None, 'method': 'manual'}


# ── 私有评分函数 ──────────────────────────────────────────────────────

def _grade_single(correct: str, student: str, full_score: float) -> dict:
    c = _norm_single(correct)
    s = _norm_single(student)
    ok = bool(c) and (c == s)
    return {'score': full_score if ok else 0.0, 'is_correct': ok, 'method': 'exact'}


def _grade_multi(correct: str, student: str, full_score: float) -> dict:
    c_set = _parse_choice_set(correct)
    s_set = _parse_choice_set(student)

    if not c_set:
        return {'score': 0.0, 'is_correct': None, 'method': 'manual'}
    if not s_set:
        return {'score': 0.0, 'is_correct': False, 'method': 'set'}
    if c_set == s_set:
        return {'score': full_score, 'is_correct': True, 'method': 'set'}
    # 漏选（真子集）→ 半分
    if s_set.issubset(c_set):
        return {'score': round(full_score * 0.5, 2), 'is_correct': False, 'method': 'partial'}
    # 多选或错选 → 0 分
    return {'score': 0.0, 'is_correct': False, 'method': 'set'}


def _grade_fill(correct: str, student: str, full_score: float) -> dict:
    c = re.sub(r'\s+', '', correct).upper()
    s = re.sub(r'\s+', '', student).upper()
    ok = bool(c) and (c == s)
    return {'score': full_score if ok else 0.0, 'is_correct': ok, 'method': 'normalized'}


# ── 辅助工具 ──────────────────────────────────────────────────────────

def _norm_single(s: str) -> str:
    s = s.strip().upper()
    mapping = {
        '正确': 'T', 'TRUE': 'T', '对': 'T', '√': 'T', '是': 'T',
        '错误': 'F', 'FALSE': 'F', '错': 'F', '×': 'F', '否': 'F',
    }
    return mapping.get(s, s)


def _parse_choice_set(s: str) -> set:
    """'A,B,C' / 'ABC' / 'A B C' → {'A','B','C'}"""
    s = s.upper().replace('，', ',').replace(' ', ',')
    parts = s.split(',') if ',' in s else list(s)
    return {p.strip() for p in parts if re.match(r'^[A-Z]$', p.strip())}
