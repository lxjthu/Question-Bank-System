"""
app/session_routes.py
考试场次管理 Blueprint
前缀 /api/sessions/

接口列表（教师端）：
  POST   /api/sessions/              创建场次
  GET    /api/sessions/              我的场次列表
  GET    /api/sessions/<id>          场次详情（含学生列表）
  POST   /api/sessions/<id>/start    开始考试
  POST   /api/sessions/<id>/end      结束考试
  GET    /api/sessions/<id>/qrcode   获取二维码（PNG 图片）
  GET    /api/sessions/<id>/scores   成绩汇总

接口列表（学生端）：
  GET    /api/sessions/join/<qr_key>     扫码验证场次
  POST   /api/sessions/join-by-code      输入考试码加入
  GET    /api/sessions/my                我参加的场次列表
"""
import json
import uuid
import secrets
import string
import datetime
import io

from flask import Blueprint, request, jsonify, send_file
from sqlalchemy import text

from app.db_models import db, User
from app.mp_auth_routes import mp_jwt_required, mp_teacher_required

session_bp = Blueprint('exam_session', __name__)

CODE_CHARS = string.ascii_uppercase + string.digits


def _now() -> str:
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _gen_code() -> str:
    """生成唯一 6 位加入码。"""
    for _ in range(30):
        code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
        if not db.session.execute(
            text('SELECT 1 FROM exam_sessions WHERE code=:c'), {'c': code}
        ).fetchone():
            return code
    raise RuntimeError('无法生成唯一考试码')


def _session_dict(row) -> dict:
    return dict(row._mapping)


# ── 教师端 ────────────────────────────────────────────────────────────────────

@session_bp.route('/api/sessions/', methods=['POST'])
@mp_teacher_required
def create_session():
    """创建考试场次。"""
    from flask import g
    data = request.get_json(force=True) or {}
    exam_id = (data.get('exam_id') or '').strip()
    title = (data.get('title') or '').strip()

    if not exam_id or not title:
        return jsonify({'error': '缺少 exam_id 或 title'}), 400

    from app.db_models import ExamModel
    exam = ExamModel.query.filter_by(exam_id=exam_id).first()
    if not exam:
        return jsonify({'error': '试卷不存在'}), 404
    if exam.owner_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权使用该试卷'}), 403

    code = _gen_code()
    qr_key = str(uuid.uuid4()).replace('-', '')

    db.session.execute(text('''
        INSERT INTO exam_sessions
            (exam_id, teacher_id, title, code, qr_key, status,
             duration_minutes, allow_retake, shuffle_questions, show_answer, created_at)
        VALUES (:exam_id, :teacher_id, :title, :code, :qr_key, 'draft',
                :duration, :retake, :shuffle, :show_answer, :now)
    '''), {
        'exam_id': exam_id,
        'teacher_id': g.mp_user_id,
        'title': title,
        'code': code,
        'qr_key': qr_key,
        'duration': int(data.get('duration_minutes', 0)),
        'retake': 1 if data.get('allow_retake') else 0,
        'shuffle': 0 if data.get('shuffle_questions') is False else 1,
        'show_answer': 0 if data.get('show_answer') is False else 1,
        'now': _now(),
    })
    db.session.commit()

    row = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE qr_key=:k'), {'k': qr_key}
    ).fetchone()
    return jsonify({
        'session': _session_dict(row),
        'qrcode_url': f'/api/sessions/{row.id}/qrcode',
    }), 201


@session_bp.route('/api/sessions/', methods=['GET'])
@mp_teacher_required
def list_sessions():
    """教师查看自己的场次列表。"""
    from flask import g
    status = request.args.get('status')
    sql = 'SELECT * FROM exam_sessions WHERE teacher_id=:tid'
    params = {'tid': g.mp_user_id}
    if status:
        sql += ' AND status=:status'
        params['status'] = status
    rows = db.session.execute(
        text(sql + ' ORDER BY created_at DESC LIMIT 50'), params
    ).fetchall()
    return jsonify({'sessions': [_session_dict(r) for r in rows]})


@session_bp.route('/api/sessions/<int:session_id>', methods=['GET'])
@mp_teacher_required
def get_session(session_id):
    """场次详情（含参与学生列表）。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403

    students = db.session.execute(text('''
        SELECT se.id AS student_exam_id, se.status, se.obj_score, se.total_score,
               se.submitted_at, wx.nickname, wx.avatar_url, u.username
        FROM student_exams se
        JOIN wx_users wx ON se.wx_user_id = wx.id
        JOIN users u ON wx.user_id = u.id
        WHERE se.session_id = :sid
        ORDER BY se.submitted_at DESC
    '''), {'sid': session_id}).fetchall()

    return jsonify({
        'session': _session_dict(sess),
        'students': [dict(r._mapping) for r in students],
    })


@session_bp.route('/api/sessions/<int:session_id>/start', methods=['POST'])
@mp_teacher_required
def start_session(session_id):
    """开始考试（draft → active）。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403
    if sess.status != 'draft':
        return jsonify({'error': f'当前状态 {sess.status}，无法开始'}), 400

    db.session.execute(text('''
        UPDATE exam_sessions SET status='active', started_at=:now WHERE id=:id
    '''), {'now': _now(), 'id': session_id})
    db.session.commit()
    return jsonify({'ok': True, 'status': 'active'})


@session_bp.route('/api/sessions/<int:session_id>/end', methods=['POST'])
@mp_teacher_required
def end_session(session_id):
    """结束考试（active → ended）。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403
    if sess.status != 'active':
        return jsonify({'error': f'当前状态 {sess.status}，无法结束'}), 400

    db.session.execute(text('''
        UPDATE exam_sessions SET status='ended', ended_at=:now WHERE id=:id
    '''), {'now': _now(), 'id': session_id})
    db.session.commit()
    return jsonify({'ok': True, 'status': 'ended'})


@session_bp.route('/api/sessions/<int:session_id>/qrcode', methods=['GET'])
@mp_teacher_required
def get_qrcode(session_id):
    """生成并返回二维码 PNG 图片。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403

    try:
        import qrcode
        # 二维码内容：小程序 scene 参数（不含 URL，由小程序解析）
        qr_content = sess.qr_key
        img = qrcode.make(qr_content)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png',
                         download_name=f'qrcode_{session_id}.png')
    except ImportError:
        return jsonify({'error': 'qrcode 库未安装，请运行 pip install qrcode[pil]'}), 500


@session_bp.route('/api/sessions/<int:session_id>/scores', methods=['GET'])
@mp_teacher_required
def session_scores(session_id):
    """成绩汇总。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE id=:id'), {'id': session_id}
    ).fetchone()
    if not sess:
        return jsonify({'error': '场次不存在'}), 404
    if sess.teacher_id != g.mp_user_id and g.mp_role != 'admin':
        return jsonify({'error': '无权限'}), 403

    rows = db.session.execute(text('''
        SELECT wx.nickname, u.username, se.obj_score, se.total_score,
               se.status, se.submitted_at, se.id AS student_exam_id
        FROM student_exams se
        JOIN wx_users wx ON se.wx_user_id = wx.id
        JOIN users u ON wx.user_id = u.id
        WHERE se.session_id = :sid
        ORDER BY se.total_score DESC NULLS LAST
    '''), {'sid': session_id}).fetchall()

    students = [dict(r._mapping) for r in rows]
    submitted_scores = [
        r.total_score for r in rows
        if r.status in ('submitted', 'graded') and r.total_score is not None
    ]
    summary = {}
    if submitted_scores:
        summary = {
            'count': len(submitted_scores),
            'avg': round(sum(submitted_scores) / len(submitted_scores), 2),
            'max': max(submitted_scores),
            'min': min(submitted_scores),
        }

    return jsonify({'summary': summary, 'students': students})


# ── 学生端 ────────────────────────────────────────────────────────────────────

@session_bp.route('/api/sessions/join/<qr_key>', methods=['GET'])
@mp_jwt_required
def join_by_qrcode(qr_key):
    """学生扫码后验证场次信息（不实际加入，仅返回信息让学生确认）。"""
    from flask import g
    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE qr_key=:k'), {'k': qr_key}
    ).fetchone()
    if not sess:
        return jsonify({'error': '二维码无效'}), 404

    if sess.status == 'draft':
        return jsonify({'error': '考试尚未开始，请等待老师发布'}), 400
    if sess.status == 'ended':
        return jsonify({'error': '考试已结束'}), 400

    teacher = User.query.get(sess.teacher_id)
    q_count = db.session.execute(text('''
        SELECT COUNT(*) AS cnt FROM exam_questions WHERE exam_id=:eid
    '''), {'eid': sess.exam_id}).fetchone()

    # 若 allow_retake=false，检查该学生是否已参加过
    already_joined = False
    if not sess.allow_retake:
        existing = db.session.execute(text('''
            SELECT id FROM student_exams WHERE session_id=:sid AND wx_user_id=:wuid
        '''), {'sid': sess.id, 'wuid': g.mp_wx_user_id}).fetchone()
        already_joined = bool(existing)

    return jsonify({
        'session': {
            'id': sess.id,
            'title': sess.title,
            'teacher_name': teacher.username if teacher else '',
            'status': sess.status,
            'duration_minutes': sess.duration_minutes,
            'code': sess.code,
        },
        'question_count': q_count.cnt if q_count else 0,
        'already_joined': already_joined,
    })


@session_bp.route('/api/sessions/join-by-code', methods=['POST'])
@mp_jwt_required
def join_by_code():
    """学生输入考试码加入，返回场次信息。"""
    from flask import g
    data = request.get_json(force=True) or {}
    code = (data.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': '请输入考试码'}), 400

    sess = db.session.execute(
        text('SELECT * FROM exam_sessions WHERE code=:c'), {'c': code}
    ).fetchone()
    if not sess:
        return jsonify({'error': '考试码无效'}), 404

    if sess.status == 'draft':
        return jsonify({'error': '考试尚未开始，请等待老师发布'}), 400
    if sess.status == 'ended':
        return jsonify({'error': '考试已结束'}), 400

    teacher = User.query.get(sess.teacher_id)
    q_count = db.session.execute(text('''
        SELECT COUNT(*) AS cnt FROM exam_questions WHERE exam_id=:eid
    '''), {'eid': sess.exam_id}).fetchone()

    already_joined = False
    if not sess.allow_retake:
        existing = db.session.execute(text('''
            SELECT id FROM student_exams WHERE session_id=:sid AND wx_user_id=:wuid
        '''), {'sid': sess.id, 'wuid': g.mp_wx_user_id}).fetchone()
        already_joined = bool(existing)

    return jsonify({
        'session': {
            'id': sess.id,
            'title': sess.title,
            'teacher_name': teacher.username if teacher else '',
            'status': sess.status,
            'duration_minutes': sess.duration_minutes,
        },
        'question_count': q_count.cnt if q_count else 0,
        'already_joined': already_joined,
    })


@session_bp.route('/api/sessions/my', methods=['GET'])
@mp_jwt_required
def my_sessions():
    """学生查看自己参加过的场次。"""
    from flask import g
    rows = db.session.execute(text('''
        SELECT es.id AS session_id, es.title, es.status AS session_status,
               se.id AS student_exam_id, se.status AS exam_status,
               se.obj_score, se.total_score, se.submitted_at
        FROM student_exams se
        JOIN exam_sessions es ON se.session_id = es.id
        WHERE se.wx_user_id = :wuid
        ORDER BY se.started_at DESC
        LIMIT 30
    '''), {'wuid': g.mp_wx_user_id}).fetchall()
    return jsonify({'sessions': [dict(r._mapping) for r in rows]})
