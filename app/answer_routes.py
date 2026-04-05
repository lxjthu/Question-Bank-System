"""
app/answer_routes.py
答题与批改 Blueprint
前缀 /api/answers/

接口列表（学生端）：
  POST /api/answers/start                      开始答题（创建 student_exams，生成乱序）
  GET  /api/answers/<student_exam_id>/paper    获取试卷（按乱序，不含答案）
  POST /api/answers/<student_exam_id>/save     保存单题答案
  POST /api/answers/<student_exam_id>/submit   交卷（自动评分客观题）
  GET  /api/answers/<student_exam_id>/result   获取成绩

接口列表（教师端）：
  GET  /api/answers/grade/<student_exam_id>    获取某学生答卷（含答案对比）
  POST /api/answers/grade/<student_exam_id>    提交主观题分数
"""
import json
import random
import datetime

from flask import Blueprint, request, jsonify, g
from sqlalchemy import text

from app.db_models import db, User
from app.mp_auth_routes import mp_jwt_required, mp_teacher_required

answer_bp = Blueprint('answers', __name__)

# 主观题类型（需要人工批改）
SUBJECTIVE_TYPES = {'简答', '简答>计算', '简答>论述', '简答>材料分析', '计算', '论述', '材料分析'}
# 客观题类型（自动评分）
OBJECTIVE_TYPES = {'单选', '多选', '是非', '填空'}


def _now() -> str:
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


# ── 学生端 ────────────────────────────────────────────────────────────────────

@answer_bp.route('/api/answers/start', methods=['POST'])
@mp_jwt_required
def start_exam():
    """开始答题：创建 student_exams 记录，生成乱序题目列表。"""
    data = request.get_json(force=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': '缺少 session_id'}), 400

    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.status != 'active':
        return jsonify({'error': '考试未开始或已结束'}), 400

    wx_user_id = g.mp_wx_user_id

    # 若不允许重做，返回已有记录
    existing = db.session.execute(text('''
        SELECT id, question_order, status FROM student_exams
        WHERE session_id=:sid AND wx_user_id=:wuid
    '''), {'sid': session_id, 'wuid': wx_user_id}).fetchone()

    if existing:
        if not sess.allow_retake:
            return jsonify({
                'student_exam_id': existing.id,
                'question_order': json.loads(existing.question_order or '[]'),
                'resumed': True,
            })

    # 获取试卷所有题目
    q_rows = db.session.execute(text('''
        SELECT question_id FROM exam_questions WHERE exam_id=:eid ORDER BY position
    '''), {'eid': sess.exam_id}).fetchall()
    question_ids = [r.question_id for r in q_rows]

    if sess.shuffle_questions:
        random.shuffle(question_ids)

    order_json = json.dumps(question_ids)
    now = _now()

    db.session.execute(text('''
        INSERT INTO student_exams (session_id, wx_user_id, question_order, status, started_at)
        VALUES (:sid, :wuid, :order, 'in_progress', :now)
    '''), {'sid': session_id, 'wuid': wx_user_id, 'order': order_json, 'now': now})
    db.session.commit()

    new_row = db.session.execute(text('''
        SELECT id FROM student_exams WHERE session_id=:sid AND wx_user_id=:wuid
        ORDER BY started_at DESC LIMIT 1
    '''), {'sid': session_id, 'wuid': wx_user_id}).fetchone()

    return jsonify({
        'student_exam_id': new_row.id,
        'question_order': question_ids,
        'resumed': False,
    })


@answer_bp.route('/api/answers/<int:student_exam_id>/paper', methods=['GET'])
@mp_jwt_required
def get_paper(student_exam_id):
    """获取试卷内容（按乱序，不含正确答案）。"""
    se = db.session.execute(
        text('SELECT * FROM student_exams WHERE id=:id'), {'id': student_exam_id}
    ).fetchone()
    if not se or se.wx_user_id != g.mp_wx_user_id:
        return jsonify({'error': '无权限'}), 403
    if se.status in ('submitted', 'graded'):
        return jsonify({'error': '已交卷'}), 400

    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:sid'), {'id': se.session_id}
    ).fetchone()

    question_ids = json.loads(se.question_order or '[]')
    if not question_ids:
        return jsonify({'error': '试卷无题目'}), 400

    from app.db_models import QuestionModel
    q_map = {q.question_id: q for q in QuestionModel.query.filter(
        QuestionModel.question_id.in_(question_ids)
    ).all()}

    # 获取已保存的答案
    saved_answers = {}
    ans_rows = db.session.execute(text('''
        SELECT question_id, answer_text FROM student_answers WHERE student_exam_id=:id
    '''), {'id': student_exam_id}).fetchall()
    for r in ans_rows:
        saved_answers[r.question_id] = r.answer_text

    questions_out = []
    for pos, qid in enumerate(question_ids, 1):
        q = q_map.get(qid)
        if not q:
            continue
        d = q.to_dict()
        # 不返回答案字段
        d.pop('answer', None)
        d.pop('reference_answer', None)
        d.pop('explanation', None)
        d['position'] = pos
        d['saved_answer'] = saved_answers.get(qid, '')
        questions_out.append(d)

    # 计算剩余时间
    remain_seconds = None
    if sess and sess.duration_minutes and sess.duration_minutes > 0 and se.started_at:
        try:
            start = datetime.datetime.strptime(str(se.started_at), '%Y-%m-%d %H:%M:%S')
            elapsed = (datetime.datetime.utcnow() - start).total_seconds()
            remain_seconds = max(0, int(sess.duration_minutes * 60 - elapsed))
        except Exception:
            pass

    return jsonify({
        'questions': questions_out,
        'duration_minutes': sess.duration_minutes if sess else 0,
        'remain_seconds': remain_seconds,
        'started_at': str(se.started_at) if se.started_at else None,
    })


@answer_bp.route('/api/answers/<int:student_exam_id>/save', methods=['POST'])
@mp_jwt_required
def save_answer(student_exam_id):
    """保存单题答案（随时保存，防断线丢失）。"""
    se = db.session.execute(
        text('SELECT wx_user_id, status FROM student_exams WHERE id=:id'),
        {'id': student_exam_id}
    ).fetchone()
    if not se or se.wx_user_id != g.mp_wx_user_id:
        return jsonify({'error': '无权限'}), 403
    if se.status in ('submitted', 'graded'):
        return jsonify({'error': '已交卷，不能修改'}), 400

    data = request.get_json(force=True) or {}
    question_id = (data.get('question_id') or '').strip()
    answer_text = data.get('answer_text', '')
    if not question_id:
        return jsonify({'error': '缺少 question_id'}), 400

    _upsert_answer(student_exam_id, question_id, answer_text)
    return jsonify({'ok': True})


@answer_bp.route('/api/answers/<int:student_exam_id>/submit', methods=['POST'])
@mp_jwt_required
def submit_exam(student_exam_id):
    """交卷：自动评分客观题，汇总分数。"""
    se = db.session.execute(
        text('SELECT * FROM student_exams WHERE id=:id'), {'id': student_exam_id}
    ).fetchone()
    if not se or se.wx_user_id != g.mp_wx_user_id:
        return jsonify({'error': '无权限'}), 403
    if se.status in ('submitted', 'graded'):
        return jsonify({
            'already_submitted': True,
            'obj_score': se.obj_score,
            'total_score': se.total_score,
            'status': se.status,
        })

    # 更新状态为 submitted
    db.session.execute(text('''
        UPDATE student_exams SET status='submitted', submitted_at=:now WHERE id=:id
    '''), {'now': _now(), 'id': student_exam_id})
    db.session.commit()

    # 执行自动评分
    result = _auto_grade(student_exam_id, se.session_id)
    return jsonify(result)


@answer_bp.route('/api/answers/<int:student_exam_id>/result', methods=['GET'])
@mp_jwt_required
def get_result(student_exam_id):
    """获取成绩（客观题立即，主观题批完再公布）。"""
    se = db.session.execute(
        text('SELECT * FROM student_exams WHERE id=:id'), {'id': student_exam_id}
    ).fetchone()
    if not se or se.wx_user_id != g.mp_wx_user_id:
        return jsonify({'error': '无权限'}), 403

    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:sid'), {'id': se.session_id}
    ).fetchone()

    result = {
        'student_exam_id': student_exam_id,
        'session_title': sess.title if sess else '',
        'status': se.status,
        'obj_score': se.obj_score,
        'total_score': se.total_score,
        'submitted_at': str(se.submitted_at) if se.submitted_at else None,
    }

    # 若场次设置了 show_answer 且已有成绩，返回答题详情
    if sess and sess.show_answer and se.status in ('submitted', 'graded'):
        from app.db_models import QuestionModel
        ans_rows = db.session.execute(text('''
            SELECT * FROM student_answers WHERE student_exam_id=:id
        '''), {'id': student_exam_id}).fetchall()

        details = []
        for ans in ans_rows:
            q = QuestionModel.query.filter_by(question_id=ans.question_id).first()
            if not q:
                continue
            qd = q.to_dict()
            detail = {
                'question_id': ans.question_id,
                'question_type': q.question_type,
                'content': qd.get('content', ''),
                'answer_text': ans.answer_text,
                'is_correct': ans.is_correct,
                'auto_score': ans.auto_score,
                'manual_score': ans.manual_score,
            }
            # 主观题：只有 graded 状态才公布参考答案
            if se.status == 'graded' or q.question_type not in SUBJECTIVE_TYPES:
                detail['correct_answer'] = q.answer
                detail['explanation'] = qd.get('explanation', '')
            details.append(detail)
        result['details'] = details

    return jsonify(result)


# ── 教师端批改 ────────────────────────────────────────────────────────────────

@answer_bp.route('/api/answers/grade/<int:student_exam_id>', methods=['GET'])
@mp_teacher_required
def get_student_paper(student_exam_id):
    """教师获取某学生答卷（含答案对比）。"""
    # 验证该场次属于当前教师
    sess_row = db.session.execute(text('''
        SELECT es.teacher_id, es.id AS session_id
        FROM exam_sessions es
        JOIN student_exams se ON se.session_id = es.id
        WHERE se.id = :id
    '''), {'id': student_exam_id}).fetchone()
    if not sess_row:
        return jsonify({'error': '记录不存在'}), 404
    if sess_row.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403

    se = db.session.execute(
        text('SELECT * FROM student_exams WHERE id=:id'), {'id': student_exam_id}
    ).fetchone()
    wx = db.session.execute(
        text('SELECT nickname, avatar_url FROM wx_users WHERE id=:id'),
        {'id': se.wx_user_id}
    ).fetchone()

    from app.db_models import QuestionModel
    ans_rows = db.session.execute(text('''
        SELECT * FROM student_answers WHERE student_exam_id=:id
    '''), {'id': student_exam_id}).fetchall()

    questions = []
    for ans in ans_rows:
        q = QuestionModel.query.filter_by(question_id=ans.question_id).first()
        if not q:
            continue
        qd = q.to_dict()
        questions.append({
            'question_id': ans.question_id,
            'question_type': q.question_type,
            'content': qd.get('content', ''),
            'options': qd.get('options'),
            'correct_answer': q.answer,
            'answer_text': ans.answer_text,
            'is_correct': ans.is_correct,
            'auto_score': ans.auto_score,
            'manual_score': ans.manual_score,
            'needs_grading': q.question_type in SUBJECTIVE_TYPES and ans.manual_score is None,
        })

    return jsonify({
        'student_exam': dict(se._mapping),
        'student': dict(wx._mapping) if wx else {},
        'questions': questions,
    })


@answer_bp.route('/api/answers/grade/<int:student_exam_id>', methods=['POST'])
@mp_teacher_required
def submit_grades(student_exam_id):
    """教师提交主观题分数。"""
    # 验证场次属于当前教师
    sess_row = db.session.execute(text('''
        SELECT es.teacher_id FROM exam_sessions es
        JOIN student_exams se ON se.session_id = es.id
        WHERE se.id = :id
    '''), {'id': student_exam_id}).fetchone()
    if not sess_row:
        return jsonify({'error': '记录不存在'}), 404
    if sess_row.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403

    data = request.get_json(force=True) or {}
    scores = data.get('scores', [])  # [{ question_id, manual_score }]

    for item in scores:
        qid = (item.get('question_id') or '').strip()
        manual_score = item.get('manual_score')
        if not qid or manual_score is None:
            continue
        db.session.execute(text('''
            UPDATE student_answers
            SET manual_score=:score
            WHERE student_exam_id=:sid AND question_id=:qid
        '''), {'score': float(manual_score), 'sid': student_exam_id, 'qid': qid})

    db.session.commit()

    # 重新汇总总分
    total_row = db.session.execute(text('''
        SELECT
            COALESCE(SUM(auto_score), 0) AS auto_total,
            COALESCE(SUM(manual_score), 0) AS manual_total,
            COUNT(CASE WHEN manual_score IS NULL AND question_id IN (
                SELECT question_id FROM questions WHERE question_type IN
                    ('简答','简答>计算','简答>论述','简答>材料分析')
            ) THEN 1 END) AS pending_count
        FROM student_answers WHERE student_exam_id=:id
    '''), {'id': student_exam_id}).fetchone()

    pending = db.session.execute(text('''
        SELECT COUNT(*) AS cnt FROM student_answers sa
        JOIN questions q ON sa.question_id = q.question_id
        WHERE sa.student_exam_id = :id
          AND q.question_type IN ('简答','简答>计算','简答>论述','简答>材料分析')
          AND sa.manual_score IS NULL
    '''), {'id': student_exam_id}).fetchone()

    total_score = round(
        (total_row.auto_total or 0) + (total_row.manual_total or 0), 2
    )
    new_status = 'submitted' if (pending.cnt or 0) > 0 else 'graded'

    db.session.execute(text('''
        UPDATE student_exams
        SET total_score=:score, status=:status, graded_at=:now, grader_id=:gid
        WHERE id=:id
    '''), {
        'score': total_score,
        'status': new_status,
        'now': _now(),
        'gid': g.mp_user_id,
        'id': student_exam_id,
    })
    db.session.commit()

    return jsonify({
        'total_score': total_score,
        'status': new_status,
    })


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _upsert_answer(student_exam_id: int, question_id: str, answer_text: str):
    """插入或更新学生答案。"""
    now = _now()
    existing = db.session.execute(text('''
        SELECT id FROM student_answers WHERE student_exam_id=:sid AND question_id=:qid
    '''), {'sid': student_exam_id, 'qid': question_id}).fetchone()

    if existing:
        db.session.execute(text('''
            UPDATE student_answers SET answer_text=:ans, answered_at=:now
            WHERE student_exam_id=:sid AND question_id=:qid
        '''), {'ans': answer_text, 'now': now, 'sid': student_exam_id, 'qid': question_id})
    else:
        db.session.execute(text('''
            INSERT INTO student_answers (student_exam_id, question_id, answer_text, answered_at)
            VALUES (:sid, :qid, :ans, :now)
        '''), {'sid': student_exam_id, 'qid': question_id, 'ans': answer_text, 'now': now})
    db.session.commit()


def _auto_grade(student_exam_id: int, session_id: int) -> dict:
    """交卷后自动评分客观题，汇总分数，更新 student_exams。"""
    from app.grading import auto_grade_question
    from app.db_models import QuestionModel

    # 获取试卷所有题目的满分配置（暂默认每题 1 分）
    q_rows = db.session.execute(text('''
        SELECT question_id FROM student_answers WHERE student_exam_id=:id
    '''), {'id': student_exam_id}).fetchall()

    obj_score = 0.0
    pending_count = 0
    now = _now()

    for row in q_rows:
        q = QuestionModel.query.filter_by(question_id=row.question_id).first()
        if not q:
            continue

        ans_row = db.session.execute(text('''
            SELECT answer_text FROM student_answers
            WHERE student_exam_id=:id AND question_id=:qid
        '''), {'id': student_exam_id, 'qid': row.question_id}).fetchone()
        answer_text = ans_row.answer_text if ans_row else ''

        full_score = 1.0  # 默认每题 1 分，后续可接入试卷分值配置
        result = auto_grade_question(q, answer_text, full_score)

        if result['method'] == 'manual':
            pending_count += 1
            db.session.execute(text('''
                UPDATE student_answers
                SET is_correct=NULL, auto_score=0, answered_at=:now
                WHERE student_exam_id=:id AND question_id=:qid
            '''), {'now': now, 'id': student_exam_id, 'qid': row.question_id})
        else:
            is_correct = 1 if result['is_correct'] is True else (
                0 if result['is_correct'] is False else None
            )
            db.session.execute(text('''
                UPDATE student_answers
                SET is_correct=:ic, auto_score=:score, answered_at=:now
                WHERE student_exam_id=:id AND question_id=:qid
            '''), {
                'ic': is_correct,
                'score': result['score'],
                'now': now,
                'id': student_exam_id,
                'qid': row.question_id,
            })
            obj_score += result['score']

    obj_score = round(obj_score, 2)
    # 若无主观题，直接标记 graded；否则 submitted 等待批改
    new_status = 'submitted' if pending_count > 0 else 'graded'
    total_score = obj_score if pending_count == 0 else None

    db.session.execute(text('''
        UPDATE student_exams
        SET obj_score=:obj, total_score=:total, status=:status
        WHERE id=:id
    '''), {
        'obj': obj_score,
        'total': total_score,
        'status': new_status,
        'id': student_exam_id,
    })
    db.session.commit()

    return {
        'obj_score': obj_score,
        'pending_count': pending_count,
        'status': new_status,
        'total_score': total_score,
    }
