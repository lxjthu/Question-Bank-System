"""
面试抽题模块 — Blueprint: interview_bp
前缀: /api/interview

功能:
  - 多命名面试题库池管理
  - 套题配置（题型槽位）
  - 批量生成套题（Fisher-Yates 全局无重复分配）
  - 单次抽选（从已生成套题中随机取一套标记使用）
  - 标记使用 / 释放
  - Word 导出（含答案，富文本 HTML）
  - Excel 导入导出（支持跨机器迁移）
"""

import json
import random
import re
import io
from datetime import datetime
from html.parser import HTMLParser

from flask import Blueprint, request, jsonify, send_file, Response, stream_with_context

from app.db_models import db, QuestionModel
from app.auth_routes import login_required, guest_readonly, get_current_user

interview_bp = Blueprint('interview', __name__)

# ─────────────────────────────────────────────────────────────────────────────
# 内部 helpers — 直接走 raw sqlite (通过 db.engine)
# ─────────────────────────────────────────────────────────────────────────────

def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _exec(sql, params=()):
    """Execute a write statement."""
    with db.engine.begin() as conn:
        from sqlalchemy import text
        result = conn.execute(text(sql), params if isinstance(params, dict) else dict(enumerate(params, 1)))
        return result


def _query(sql, params=()):
    """Execute a read statement, return list of dicts."""
    from sqlalchemy import text
    with db.engine.connect() as conn:
        if params:
            rows = conn.execute(text(sql), params if isinstance(params, dict) else dict(enumerate(params, 1)))
        else:
            rows = conn.execute(text(sql))
        cols = rows.keys()
        return [dict(zip(cols, row)) for row in rows]


def _query_one(sql, params=()):
    rows = _query(sql, params)
    return rows[0] if rows else None


# SQLAlchemy text() helper for cleaner queries
def _run(sql, **kw):
    from sqlalchemy import text
    with db.engine.begin() as conn:
        result = conn.execute(text(sql), kw)
        return result


def _fetch(sql, **kw):
    from sqlalchemy import text
    with db.engine.connect() as conn:
        result = conn.execute(text(sql), kw)
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result]


def _fetch_one(sql, **kw):
    rows = _fetch(sql, **kw)
    return rows[0] if rows else None


def _strip_html(html):
    """Strip HTML tags, return plain text."""
    if not html:
        return ''

    class _Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
    p = _Strip()
    p.feed(html)
    return ' '.join(p.parts).strip()


def _sync_question_interview_status(qids, owner_id=None):
    """重新计算并更新指定题目的三个面试状态字段。

    - interview_pool : 当前在该用户的面试题库池中
    - interview_set  : 已被分配进该用户的套题
    - interview_used : 所在套题已被标记为已使用

    owner_id: 当前操作用户的 id，只基于该用户的池/场次计算状态。
    在任何会改变这三个状态的操作后调用：
    加入/移出池、生成套题、标记使用、释放套题、删除池。
    """
    qids = [q for q in (qids or []) if q]
    if not qids:
        return

    # 1. 哪些题目当前在池中（限当前用户的池）
    if owner_id is not None:
        pool_rows = _fetch(
            "SELECT DISTINCT ipq.question_id FROM interview_pool_questions ipq "
            "JOIN interview_pools ip ON ip.id = ipq.pool_id "
            "WHERE ip.owner_id=:uid",
            uid=owner_id,
        )
    else:
        pool_rows = _fetch("SELECT DISTINCT question_id FROM interview_pool_questions")
    pool_qids = {r['question_id'] for r in pool_rows}

    # 2. 哪些题目在套题中 / 在已使用套题中（限当前用户的场次）
    if owner_id is not None:
        all_sets = _fetch(
            "SELECT ist.question_ids_json, ist.is_used FROM interview_sets ist "
            "JOIN interview_sessions iss ON iss.id = ist.session_id "
            "WHERE iss.owner_id=:uid",
            uid=owner_id,
        )
    else:
        all_sets = _fetch("SELECT question_ids_json, is_used FROM interview_sets")
    set_qids = set()
    used_qids = set()
    for s in all_sets:
        try:
            ids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
            for qid in ids:
                if qid:
                    set_qids.add(qid)
                    if s['is_used']:
                        used_qids.add(qid)
        except Exception:
            pass

    from sqlalchemy import text
    with db.engine.begin() as conn:
        for qid in qids:
            conn.execute(text("""
                UPDATE questions
                SET interview_pool = :ip,
                    interview_set  = :is_,
                    interview_used = :iu
                WHERE question_id = :qid
            """), {
                'ip':  1 if qid in pool_qids  else 0,
                'is_': 1 if qid in set_qids   else 0,
                'iu':  1 if qid in used_qids  else 0,
                'qid': qid,
            })


# ─────────────────────────────────────────────────────────────────────────────
# 1. 题库池管理
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools', methods=['GET'])
@login_required
def list_pools():
    user = get_current_user()
    if user.role == 'admin':
        pools = _fetch("SELECT * FROM interview_pools ORDER BY id")
    else:
        pools = _fetch("SELECT * FROM interview_pools WHERE owner_id=:uid ORDER BY id", uid=user.id)
    for p in pools:
        row = _fetch_one(
            "SELECT COUNT(*) AS cnt FROM interview_pool_questions WHERE pool_id=:pid",
            pid=p['id']
        )
        p['question_count'] = row['cnt'] if row else 0
        row2 = _fetch_one(
            "SELECT COUNT(*) AS cnt FROM interview_pool_questions WHERE pool_id=:pid AND drawn=0",
            pid=p['id']
        )
        p['available_count'] = row2['cnt'] if row2 else 0
    return jsonify({'pools': pools})


@interview_bp.route('/api/interview/pools', methods=['POST'])
@login_required
@guest_readonly
def create_pool():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get('pool_name') or '').strip()
    if not name:
        return jsonify({'error': '池名称不能为空'}), 400
    desc = (data.get('description') or '').strip()
    _run(
        "INSERT INTO interview_pools (pool_name, description, created_at, owner_id) VALUES (:n, :d, :t, :uid)",
        n=name, d=desc, t=_now_str(), uid=user.id
    )
    pool = _fetch_one("SELECT * FROM interview_pools WHERE pool_name=:n AND owner_id=:uid ORDER BY id DESC LIMIT 1",
                      n=name, uid=user.id)
    return jsonify({'pool': pool}), 201


def _check_pool_access(pool_id, user):
    """返回 (pool dict, None) 或 (None, (error_msg, status_code))。admin 可访问所有池。"""
    pool = _fetch_one("SELECT * FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return None, ('题库池不存在', 404)
    if user.role != 'admin' and pool.get('owner_id') != user.id:
        return None, ('无权访问他人题库池', 403)
    return pool, None


def _check_session_access(session_id, user):
    """返回 (session dict, None) 或 (None, (error_msg, status_code))。admin 可访问所有场次。"""
    sess = _fetch_one("SELECT * FROM interview_sessions WHERE id=:sid", sid=session_id)
    if not sess:
        return None, ('场次不存在', 404)
    if user.role != 'admin' and sess.get('owner_id') != user.id:
        return None, ('无权访问他人场次', 403)
    return sess, None


def _check_set_access(set_id, user):
    """返回 (set dict, sess dict, None) 或 (None, None, (error_msg, status_code))。"""
    s = _fetch_one("SELECT * FROM interview_sets WHERE id=:id", id=set_id)
    if not s:
        return None, None, ('套题不存在', 404)
    sess, err = _check_session_access(s['session_id'], user)
    if err:
        return None, None, err
    return s, sess, None


@interview_bp.route('/api/interview/pools/<int:pool_id>', methods=['PUT'])
@login_required
@guest_readonly
def update_pool(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    data = request.get_json(silent=True) or {}
    name = (data.get('pool_name') or pool['pool_name']).strip()
    desc = (data.get('description') or pool['description'] or '').strip()
    _run("UPDATE interview_pools SET pool_name=:n, description=:d WHERE id=:id",
         n=name, d=desc, id=pool_id)
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/pools/<int:pool_id>', methods=['DELETE'])
@login_required
@guest_readonly
def delete_pool(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    # 删前先记录池中所有题目，以便删后同步状态
    in_pool = _fetch("SELECT question_id FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    qids_to_sync = [r['question_id'] for r in in_pool]
    _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    _run("DELETE FROM interview_configs WHERE pool_id=:pid", pid=pool_id)
    # 注意：不删除关联的 sessions/sets，它们保留历史记录
    _run("DELETE FROM interview_pools WHERE id=:id", id=pool_id)
    _sync_question_interview_status(qids_to_sync, owner_id=user.id)
    return jsonify({'ok': True})


# ─────────────────────────────────────────────────────────────────────────────
# 2. 池中题目管理
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/questions', methods=['GET'])
@login_required
def list_pool_questions(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, int(request.args.get('per_page', 20)))
    drawn_filter = request.args.get('drawn')  # '0'/'1'/None

    base = """
        SELECT ipq.id as pool_entry_id, ipq.drawn, ipq.drawn_at, ipq.added_at,
               q.question_id, q.question_type, q.subject, q.difficulty,
               q.language, q.knowledge_point, q.tags,
               q.content, q.answer, q.reference_answer
        FROM interview_pool_questions ipq
        JOIN questions q ON q.question_id = ipq.question_id
        WHERE ipq.pool_id = :pid
    """
    params = {'pid': pool_id}
    if drawn_filter == '0':
        base += ' AND ipq.drawn=0'
    elif drawn_filter == '1':
        base += ' AND ipq.drawn=1'

    total = len(_fetch(base, **params))
    rows = _fetch(base + f' ORDER BY ipq.added_at DESC LIMIT {per_page} OFFSET {(page-1)*per_page}', **params)
    return jsonify({'questions': rows, 'total': total, 'page': page, 'per_page': per_page})


@interview_bp.route('/api/interview/pools/<int:pool_id>/stats', methods=['GET'])
@login_required
def pool_stats(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    rows = _fetch("""
        SELECT q.question_type,
               COUNT(*) AS total,
               SUM(CASE WHEN ipq.drawn=0 THEN 1 ELSE 0 END) AS available
        FROM interview_pool_questions ipq
        JOIN questions q ON q.question_id = ipq.question_id
        WHERE ipq.pool_id = :pid
        GROUP BY q.question_type
    """, pid=pool_id)
    total_all = sum(r['total'] for r in rows)
    available_all = sum(r['available'] for r in rows)
    return jsonify({'stats': rows, 'total': total_all, 'available': available_all})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/preview', methods=['POST'])
@login_required
def preview_filter(pool_id):
    """预览筛选结果（不实际加入池），返回命中题目数量和摘要列表。"""
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    data = request.get_json(silent=True) or {}
    qs, params = _build_filter_query(data, pool_id, owner_id=user.id, exclude_pool=True)
    rows = _fetch(qs, **params)
    # 返回轻量摘要
    preview = [
        {
            'question_id': r['question_id'],
            'question_type': r['question_type'],
            'subject': r['subject'],
            'difficulty': r['difficulty'],
            'language': r['language'],
            'knowledge_point': r['knowledge_point'],
            'content_preview': _strip_html(r['content'])[:200],
        }
        for r in rows
    ]
    return jsonify({'count': len(preview), 'questions': preview})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/add', methods=['POST'])
@login_required
def add_to_pool(pool_id):
    """按筛选条件将题目批量加入池。"""
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    data = request.get_json(silent=True) or {}
    direct_ids = data.get('question_ids')  # 直接指定 ID 列表（来自预览勾选）
    if direct_ids:
        rows = [{'question_id': qid} for qid in direct_ids if qid]
    else:
        qs, params = _build_filter_query(data, pool_id, owner_id=user.id, exclude_pool=True)
        rows = _fetch(qs, **params)

    added = 0
    now = _now_str()
    added_qids = []
    for r in rows:
        try:
            _run(
                "INSERT OR IGNORE INTO interview_pool_questions (pool_id, question_id, added_at) VALUES (:pid, :qid, :t)",
                pid=pool_id, qid=r['question_id'], t=now
            )
            added_qids.append(r['question_id'])
            added += 1
        except Exception:
            pass
    _sync_question_interview_status(added_qids, owner_id=user.id)
    return jsonify({'ok': True, 'added': added})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/remove', methods=['POST'])
@login_required
def remove_from_pool(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    data = request.get_json(silent=True) or {}
    qids = data.get('question_ids', [])
    if not qids:
        return jsonify({'error': '未提供 question_ids'}), 400
    removed = 0
    for qid in qids:
        _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid AND question_id=:qid",
             pid=pool_id, qid=qid)
        removed += 1
    _sync_question_interview_status(qids, owner_id=user.id)
    return jsonify({'ok': True, 'removed': removed})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions', methods=['DELETE'])
@login_required
def clear_pool(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    in_pool = _fetch("SELECT question_id FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    qids_to_sync = [r['question_id'] for r in in_pool]
    _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    _sync_question_interview_status(qids_to_sync, owner_id=user.id)
    return jsonify({'ok': True})


def _build_filter_query(data, pool_id, owner_id=None, exclude_pool=False):
    """Build SELECT query from filter dict. Returns (sql, params_dict)."""
    conds = ['1=1']
    params = {}
    if owner_id is not None:
        conds.append('q.owner_id = :owner_id')
        params['owner_id'] = owner_id

    subjects = data.get('subjects') or []
    if subjects:
        placeholders = ','.join(f':s{i}' for i in range(len(subjects)))
        conds.append(f'q.subject IN ({placeholders})')
        for i, s in enumerate(subjects):
            params[f's{i}'] = s

    qtypes = data.get('question_types') or []
    if qtypes:
        placeholders = ','.join(f':qt{i}' for i in range(len(qtypes)))
        conds.append(f'q.question_type IN ({placeholders})')
        for i, t in enumerate(qtypes):
            params[f'qt{i}'] = t

    difficulties = data.get('difficulties') or []
    if difficulties:
        placeholders = ','.join(f':df{i}' for i in range(len(difficulties)))
        conds.append(f'q.difficulty IN ({placeholders})')
        for i, d in enumerate(difficulties):
            params[f'df{i}'] = d

    language = data.get('language')
    if language and language != 'all':
        conds.append('q.language = :lang')
        params['lang'] = language

    kp = (data.get('knowledge_point') or '').strip()
    if kp:
        conds.append('q.knowledge_point LIKE :kp')
        params['kp'] = f'%{kp}%'

    tags = (data.get('tags') or '').strip()
    if tags:
        conds.append('q.tags LIKE :tags')
        params['tags'] = f'%{tags}%'

    search = (data.get('search') or '').strip()
    if search:
        conds.append('q.content LIKE :search')
        params['search'] = f'%{search}%'

    if data.get('exclude_used', True):
        conds.append('(q.is_used = 0 OR q.is_used IS NULL)')

    if exclude_pool:
        conds.append(f"""q.question_id NOT IN (
            SELECT question_id FROM interview_pool_questions WHERE pool_id={pool_id}
        )""")

    where = ' AND '.join(conds)
    sql = f"""
        SELECT q.question_id, q.question_type, q.subject, q.difficulty,
               q.language, q.knowledge_point, q.tags, q.content,
               q.answer, q.reference_answer, q.explanation,
               q.content_en, q.options_en, q.options
        FROM questions q
        WHERE {where}
    """
    return sql, params


# ─────────────────────────────────────────────────────────────────────────────
# 3. 套题配置
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/config', methods=['GET'])
@login_required
def get_config(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    configs = _fetch(
        "SELECT * FROM interview_configs WHERE pool_id=:pid ORDER BY updated_at DESC",
        pid=pool_id
    )
    subjects_rows = _fetch("""
        SELECT DISTINCT q.subject FROM interview_pool_questions ipq
        JOIN questions q ON q.question_id=ipq.question_id
        WHERE ipq.pool_id=:pid AND q.subject IS NOT NULL AND q.subject != ''
    """, pid=pool_id)
    all_subjects = [r['subject'] for r in subjects_rows]
    result = []
    for cfg in configs:
        slots = json.loads(cfg['slots_json']) if cfg['slots_json'] else []
        type_counts = {}
        for s in slots:
            t = s.get('question_type', '?')
            type_counts[t] = type_counts.get(t, 0) + 1
        summary = ', '.join(f"{t}×{c}" for t, c in type_counts.items())
        cfg['slots'] = slots
        cfg['slot_summary'] = summary
        cfg['subjects'] = all_subjects
        result.append(cfg)
    return jsonify({'configs': result})


@interview_bp.route('/api/interview/pools/<int:pool_id>/config', methods=['PUT'])
@login_required
def save_config(pool_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    data = request.get_json(silent=True) or {}
    slots = data.get('slots', [])
    if not slots:
        return jsonify({'error': '套题配置至少需要一个槽位'}), 400

    for i, slot in enumerate(slots):
        if not slot.get('question_type'):
            return jsonify({'error': f'第 {i+1} 个槽位缺少题型'}), 400

    slots_json = json.dumps(slots, ensure_ascii=False)
    now = _now_str()
    cfg_name = (data.get('config_name') or 'default').strip()

    existing = _fetch_one(
        "SELECT id FROM interview_configs WHERE pool_id=:pid AND config_name=:cn",
        pid=pool_id, cn=cfg_name
    )
    if existing:
        _run(
            "UPDATE interview_configs SET slots_json=:sj, updated_at=:t WHERE id=:cid",
            sj=slots_json, t=now, cid=existing['id']
        )
        config_id = existing['id']
    else:
        _run(
            "INSERT INTO interview_configs (pool_id, config_name, slots_json, created_at, updated_at) VALUES (:pid, :cn, :sj, :t, :t)",
            pid=pool_id, cn=cfg_name, sj=slots_json, t=now
        )
        row = _fetch_one(
            "SELECT id FROM interview_configs WHERE pool_id=:pid AND config_name=:cn ORDER BY id DESC LIMIT 1",
            pid=pool_id, cn=cfg_name
        )
        config_id = row['id'] if row else None
    return jsonify({'ok': True, 'config_id': config_id, 'slots': slots})


@interview_bp.route('/api/interview/pools/<int:pool_id>/config/<int:config_id>', methods=['DELETE'])
@login_required
def delete_config(pool_id, config_id):
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    _run(
        "DELETE FROM interview_configs WHERE id=:cid AND pool_id=:pid",
        cid=config_id, pid=pool_id
    )
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/pools/<int:pool_id>/config/<int:config_id>/export-template', methods=['GET'])
@login_required
def export_config_template(pool_id, config_id):
    """
    导出套题模板
    
    参数:
        - simplified: 是否导出简化版（0=通用模板，1=简化模板）
        - set_count: 套题数量（默认5）
    
    简化版: 只有"套题列表"工作表，题目内容直接填在槽位列（列宽60，方便填写）
    通用版: 包含"套题列表"和"题目详情"两个工作表
    """
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    cfg = _fetch_one(
        "SELECT * FROM interview_configs WHERE id=:cid AND pool_id=:pid",
        cid=config_id, pid=pool_id
    )
    if not cfg:
        return jsonify({'error': '配置不存在'}), 404

    slots = json.loads(cfg['slots_json']) if cfg['slots_json'] else []
    set_count = request.args.get('set_count', 5, type=int)
    set_count = max(1, min(set_count, 50))
    simplified = request.args.get('simplified', '0') == '1'

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.Workbook()
    header_fill = PatternFill('solid', fgColor='366092')
    hdr_font = Font(bold=True, color='FFFFFF')

    # Sheet1: 套题列表
    ws1 = wb.active
    ws1.title = '套题列表'
    h1 = ['set_code'] + [f"槽位{i+1}-{s.get('question_type', '?')}" for i, s in enumerate(slots)]
    for col_idx, h in enumerate(h1, 1):
        cell = ws1.cell(row=1, column=col_idx, value=h)
        cell.font = hdr_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', wrap_text=True)
    for r in range(set_count):
        ws1.cell(row=r + 2, column=1, value=f"SET-{r+1:03d}")
    ws1.column_dimensions['A'].width = 14
    # 简化版列宽60（方便填写题目内容），通用版列宽25
    col_width = 60 if simplified else 25
    for c in range(2, len(h1) + 1):
        ws1.column_dimensions[openpyxl.utils.get_column_letter(c)].width = col_width

    # 通用版才有 Sheet2: 题目详情
    if not simplified:
        ws2 = wb.create_sheet('题目详情')
        h2 = ['set_code', 'slot_index', 'question_id', 'question_type', 'subject',
              'difficulty', 'language', 'content', 'answer', 'reference_answer', 'explanation']
        for col_idx, h in enumerate(h2, 1):
            cell = ws2.cell(row=1, column=col_idx, value=h)
            cell.font = hdr_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', wrap_text=True)
        for col_idx, w in enumerate([12, 8, 20, 12, 15, 10, 8, 60, 40, 60, 40], 1):
            ws2.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_name = re.sub(r'[^\w\-_\u4e00-\u9fff]', '_', cfg['config_name'])
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    template_type = '简化' if simplified else '通用'
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'面试套题模板_{template_type}_{safe_name}_{date_str}.xlsx',
    )


@interview_bp.route('/api/interview/templates/pool-xlsx', methods=['GET'])
@login_required
def download_pool_template():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '面试题库池'

    headers = [
        'question_id', 'question_type', 'subject', 'difficulty', 'language',
        'knowledge_point', 'tags', 'content', 'answer', 'reference_answer',
        'explanation', 'content_en', 'options', 'options_en', 'drawn', 'drawn_at', 'added_at'
    ]
    header_fill = PatternFill('solid', fgColor='366092')
    hdr_font = Font(bold=True, color='FFFFFF')
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = hdr_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', wrap_text=True)

    example = [
        '', '简答', '农业经济学', 'medium', 'zh',
        '第一章核心概念', '#知识点#标签1', '请简述农业现代化的特征。',
        'A', '农业现代化具有工业化、科学化、社会化等特征……',
        '考查对农业现代化基本概念的掌握', '', '', '', '可用', '', ''
    ]
    for col_idx, v in enumerate(example, 1):
        ws.cell(row=2, column=col_idx, value=v)

    col_widths = [20, 12, 15, 10, 8, 20, 20, 60, 40, 60, 40, 60, 30, 30, 8, 18, 18]
    for col_idx, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='面试题库池导入模板.xlsx',
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. 警告检查
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/check', methods=['POST'])
@login_required
def check_pool(pool_id):
    """校验池中可用题目是否满足生成 N 套题的需求。"""
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    data = request.get_json(silent=True) or {}
    total_sets = int(data.get('total_sets', 1))

    cfg = _fetch_one(
        "SELECT slots_json FROM interview_configs WHERE pool_id=:pid LIMIT 1",
        pid=pool_id
    )
    if not cfg:
        return jsonify({'ok': False, 'warnings': [{'type': 'no_config', 'message': '尚未配置套题结构，请先设置题型槽位'}]})

    slots = json.loads(cfg['slots_json'])
    warnings = []

    # 按槽位检查各题型可用数
    for i, slot in enumerate(slots):
        qtype = slot.get('question_type', '')
        lang = slot.get('language', '')
        difficulty = slot.get('difficulty', '')

        conds = ['ipq.pool_id=:pid', 'ipq.drawn=0', 'q.question_type=:qt']
        params = {'pid': pool_id, 'qt': qtype}
        if lang and lang not in ('all', '任意', ''):
            conds.append('q.language=:lang')
            params['lang'] = lang
        if difficulty and difficulty not in ('all', '任意', ''):
            conds.append('q.difficulty=:diff')
            params['diff'] = difficulty

        where = ' AND '.join(conds)
        from sqlalchemy import text
        with db.engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS cnt
                FROM interview_pool_questions ipq
                JOIN questions q ON q.question_id=ipq.question_id
                WHERE {where}
            """), params).fetchone()
        available = row[0] if row else 0

        if available == 0:
            warnings.append({
                'type': 'slot_empty',
                'slot_index': i + 1,
                'question_type': qtype,
                'message': f'槽位{i+1}（{qtype}）在面试池中没有可用题目，请先补充该题型',
                'available': 0,
                'required': total_sets,
            })
        elif available < total_sets:
            warnings.append({
                'type': 'slot_insufficient',
                'slot_index': i + 1,
                'question_type': qtype,
                'message': f'槽位{i+1}（{qtype}）可用题目仅 {available} 道，无法生成 {total_sets} 套不重复套题',
                'available': available,
                'required': total_sets,
            })

    return jsonify({'ok': len(warnings) == 0, 'warnings': warnings})


# ─────────────────────────────────────────────────────────────────────────────
# 5. 套题生成（批量）
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/sessions', methods=['GET'])
@login_required
def list_sessions():
    user = get_current_user()
    if user.role == 'admin':
        rows = _fetch("SELECT * FROM interview_sessions ORDER BY id DESC")
    else:
        rows = _fetch("SELECT * FROM interview_sessions WHERE owner_id=:uid ORDER BY id DESC", uid=user.id)
    for sess in rows:
        total = _fetch_one(
            "SELECT COUNT(*) AS cnt FROM interview_sets WHERE session_id=:sid",
            sid=sess['id']
        )
        used = _fetch_one(
            "SELECT COUNT(*) AS cnt FROM interview_sets WHERE session_id=:sid AND is_used=1",
            sid=sess['id']
        )
        sess['total_sets'] = total['cnt'] if total else 0
        sess['used_sets'] = used['cnt'] if used else 0
        # 附加池名
        pool = _fetch_one("SELECT pool_name FROM interview_pools WHERE id=:pid", pid=sess['pool_id'])
        sess['pool_name'] = pool['pool_name'] if pool else '(已删除)'
    return jsonify({'sessions': rows})


@interview_bp.route('/api/interview/sessions', methods=['POST'])
@login_required
def create_session():
    """创建面试场次并批量生成套题。"""
    data = request.get_json(silent=True) or {}
    pool_id = data.get('pool_id')
    session_name = (data.get('session_name') or '').strip()
    interview_count = int(data.get('interview_count', 1))
    sets_multiplier = int(data.get('sets_multiplier', 3))
    score_per_slot = data.get('score_per_slot', {})

    if not pool_id:
        return jsonify({'error': '缺少 pool_id'}), 400
    if not session_name:
        return jsonify({'error': '场次名称不能为空'}), 400
    if interview_count < 1:
        return jsonify({'error': '面试人数不能小于1'}), 400
    if sets_multiplier < 1:
        return jsonify({'error': '套题倍数不能小于1'}), 400

    total_sets = interview_count * sets_multiplier

    user = get_current_user()
    pool, perr = _check_pool_access(pool_id, user)
    if perr:
        return jsonify({'error': perr[0]}), perr[1]

    cfg = _fetch_one(
        "SELECT id, slots_json FROM interview_configs WHERE pool_id=:pid LIMIT 1",
        pid=pool_id
    )
    if not cfg:
        return jsonify({'error': '请先设置套题配置（题型槽位）'}), 400

    slots = json.loads(cfg['slots_json'])

    # ── 为每个槽位收集可用题目并打乱 ────────────────────────────────────────
    slot_pools = []
    warnings = []
    for i, slot in enumerate(slots):
        qtype = slot.get('question_type', '')
        lang = slot.get('language', '')
        difficulty = slot.get('difficulty', '')

        conds = ['ipq.pool_id=:pid', 'ipq.drawn=0', 'q.question_type=:qt']
        params = {'pid': pool_id, 'qt': qtype}
        if lang and lang not in ('all', '任意', ''):
            conds.append('q.language=:lang')
            params['lang'] = lang
        if difficulty and difficulty not in ('all', '任意', ''):
            conds.append('q.difficulty=:diff')
            params['diff'] = difficulty

        where = ' AND '.join(conds)
        from sqlalchemy import text
        with db.engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT q.question_id
                FROM interview_pool_questions ipq
                JOIN questions q ON q.question_id=ipq.question_id
                WHERE {where}
            """), params).fetchall()
        qids = [r[0] for r in rows]
        random.shuffle(qids)

        if len(qids) < total_sets:
            warnings.append({
                'type': 'slot_insufficient',
                'slot_index': i + 1,
                'question_type': qtype,
                'available': len(qids),
                'required': total_sets,
                'message': f'槽位{i+1}（{qtype}）可用题目仅 {len(qids)} 道，无法生成 {total_sets} 套不重复套题',
            })
        slot_pools.append(qids)

    if warnings:
        return jsonify({'ok': False, 'warnings': warnings}), 422

    # ── 创建 session 记录 ─────────────────────────────────────────────────────
    now = _now_str()
    from sqlalchemy import text
    with db.engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO interview_sessions
              (pool_id, config_id, session_name, interview_count, sets_multiplier, score_per_slot_json, created_at, owner_id)
            VALUES (:pid, :cid, :sn, :ic, :sm, :sp, :t, :uid)
        """), {
            'pid': pool_id, 'cid': cfg['id'], 'sn': session_name,
            'ic': interview_count, 'sm': sets_multiplier,
            'sp': json.dumps(score_per_slot, ensure_ascii=False), 't': now,
            'uid': user.id
        })
        session_id = result.lastrowid

    # ── 分配套题（全局无重复：每道题只出现在一套里） ─────────────────────────
    sets_created = []
    with db.engine.begin() as conn:
        for set_idx in range(total_sets):
            set_code = f'SET-{set_idx + 1:03d}'
            question_ids = []
            for slot_qids in slot_pools:
                if set_idx < len(slot_qids):
                    question_ids.append(slot_qids[set_idx])
                else:
                    question_ids.append(None)  # 不足时留空

            qids_json = json.dumps(question_ids, ensure_ascii=False)
            r = conn.execute(text("""
                INSERT INTO interview_sets (session_id, set_code, question_ids_json, created_at)
                VALUES (:sid, :sc, :qj, :t)
            """), {'sid': session_id, 'sc': set_code, 'qj': qids_json, 't': now})
            sets_created.append({'set_id': r.lastrowid, 'set_code': set_code, 'question_ids': question_ids})

    # 同步所有被分配进套题的题目状态（interview_set=1）
    all_assigned = [qid for s in sets_created for qid in s['question_ids'] if qid]
    _sync_question_interview_status(all_assigned, owner_id=user.id)

    return jsonify({
        'ok': True,
        'session_id': session_id,
        'session_name': session_name,
        'total_sets': total_sets,
        'sets': sets_created,
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
# 6. 套题查询 & 单次抽选
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/sessions/<int:session_id>/sets', methods=['GET'])
@login_required
def list_sets(session_id):
    user = get_current_user()
    _, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, int(request.args.get('per_page', 50)))
    used_filter = request.args.get('is_used')

    base = "SELECT * FROM interview_sets WHERE session_id=:sid"
    params = {'sid': session_id}
    if used_filter == '0':
        base += ' AND is_used=0'
    elif used_filter == '1':
        base += ' AND is_used=1'

    total = len(_fetch(base, **params))
    rows = _fetch(
        base + f' ORDER BY id LIMIT {per_page} OFFSET {(page-1)*per_page}',
        **params
    )
    # 附加每套题的题目简要信息
    for s in rows:
        qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
        s['question_ids'] = qids
        s['questions_brief'] = _get_questions_brief(qids)

    return jsonify({'sets': rows, 'total': total, 'page': page, 'per_page': per_page})


@interview_bp.route('/api/interview/sessions/<int:session_id>/draw', methods=['POST'])
@login_required
def draw_set(session_id):
    """从指定场次中随机抽取一套未使用的套题并标记为已使用。"""
    user = get_current_user()
    _, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    available = _fetch(
        "SELECT id, set_code, question_ids_json FROM interview_sets WHERE session_id=:sid AND is_used=0",
        sid=session_id
    )
    if not available:
        return jsonify({'error': '该场次已没有未使用的套题，请释放部分套题或补充生成', 'code': 'no_available'}), 422

    chosen = random.choice(available)
    now = _now_str()
    _run(
        "UPDATE interview_sets SET is_used=1, used_at=:t WHERE id=:id",
        t=now, id=chosen['id']
    )

    qids = json.loads(chosen['question_ids_json']) if chosen['question_ids_json'] else []
    questions = _get_questions_full(qids)
    _sync_question_interview_status([q for q in qids if q], owner_id=user.id)

    return jsonify({
        'ok': True,
        'set_id': chosen['id'],
        'set_code': chosen['set_code'],
        'used_at': now,
        'questions': questions,
    })


@interview_bp.route('/api/interview/sets/<int:set_id>', methods=['GET'])
@login_required
def get_set_detail(set_id):
    user = get_current_user()
    s, _, err = _check_set_access(set_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
    s['questions'] = _get_questions_full(qids)
    return jsonify({'set': s})


@interview_bp.route('/api/interview/sets/<int:set_id>/use', methods=['POST'])
@login_required
def mark_set_used(set_id):
    user = get_current_user()
    s, _, err = _check_set_access(set_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    now = _now_str()
    _run("UPDATE interview_sets SET is_used=1, used_at=:t WHERE id=:id", t=now, id=set_id)
    qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
    _sync_question_interview_status([q for q in qids if q], owner_id=user.id)
    return jsonify({'ok': True, 'used_at': now})


@interview_bp.route('/api/interview/sets/<int:set_id>/release', methods=['POST'])
@login_required
def release_set(set_id):
    """释放套题：将套题标记为未使用，并重置池中对应题目的 drawn 状态。"""
    user = get_current_user()
    s, _, err = _check_set_access(set_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    _run("UPDATE interview_sets SET is_used=0, used_at=NULL WHERE id=:id", id=set_id)

    # 重置该套题中题目在所有池中的 drawn 状态
    qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
    qids = [q for q in qids if q]  # 去掉 None
    for qid in qids:
        _run(
            "UPDATE interview_pool_questions SET drawn=0, drawn_at=NULL WHERE question_id=:qid",
            qid=qid
        )
    _sync_question_interview_status(qids, owner_id=user.id)
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/sessions/<int:session_id>/release-all', methods=['POST'])
@login_required
def release_all_used_sets(session_id):
    """一键释放本场次所有已使用的套题，重置 drawn 状态。"""
    user = get_current_user()
    _, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    used_sets = _fetch(
        "SELECT id, question_ids_json FROM interview_sets WHERE session_id=:sid AND is_used=1",
        sid=session_id
    )
    if not used_sets:
        return jsonify({'ok': True, 'released': 0})

    all_qids = []
    for s in used_sets:
        _run("UPDATE interview_sets SET is_used=0, used_at=NULL WHERE id=:id", id=s['id'])
        qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
        all_qids.extend(q for q in qids if q)

    # 重置所有涉及题目的 drawn 状态
    unique_qids = list(dict.fromkeys(all_qids))
    for qid in unique_qids:
        _run(
            "UPDATE interview_pool_questions SET drawn=0, drawn_at=NULL WHERE question_id=:qid",
            qid=qid
        )
    _sync_question_interview_status(unique_qids, owner_id=user.id)
    return jsonify({'ok': True, 'released': len(used_sets)})


@interview_bp.route('/api/interview/sessions/<int:session_id>/quality-check', methods=['POST'])
@login_required
def quality_check_session(session_id):
    """用 DeepSeek 检查本场次所有套题题目的质量。

    检查项目：
    1. 题干答案混淆/重叠（答案混入题干，或 reference_answer 为空但题干已含答案）
    2. 英文题干语法错误（content_en 字段）
    """
    user = get_current_user()
    _, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    import time as _time

    from app.rag_routes import _get_deepseek_key
    api_key = _get_deepseek_key()
    if not api_key:
        return jsonify({'error': '未配置 DeepSeek API Key，请在「API 配置」中填写'}), 400

    # ── 收集本场次全部唯一题目 ─────────────────────────────────────────────────
    sets = _fetch("SELECT question_ids_json FROM interview_sets WHERE session_id=:sid", sid=session_id)
    if not sets:
        return jsonify({'error': '场次不存在或尚未生成套题'}), 404

    all_qids = []
    for s in sets:
        try:
            all_qids.extend(json.loads(s['question_ids_json'] or '[]'))
        except Exception:
            pass
    unique_qids = list(dict.fromkeys(qid for qid in all_qids if qid))
    if not unique_qids:
        return jsonify({'error': '该场次无题目'}), 400

    questions = []
    for qid in unique_qids:
        q = _fetch_one(
            "SELECT question_id, content, content_en, reference_answer FROM questions WHERE question_id=:qid",
            qid=qid
        )
        if q:
            questions.append({
                'question_id': q['question_id'],
                'content': _strip_html(q['content'] or ''),
                'content_en': _strip_html(q['content_en'] or ''),
                'reference_answer': _strip_html(q['reference_answer'] or ''),
            })

    # ── 分批调用 DeepSeek ─────────────────────────────────────────────────────
    try:
        from openai import OpenAI as _OAI
    except ImportError:
        return jsonify({'error': '缺少 openai 依赖，请 pip install openai'}), 500

    ds = _OAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=120)
    BATCH = 8
    all_results = []
    for i in range(0, len(questions), BATCH):
        batch_results = _qc_call_deepseek(ds, questions[i:i+BATCH])
        all_results.extend(batch_results)
        if i + BATCH < len(questions):
            _time.sleep(0.4)

    # ── 过滤误报（suggested 与 original 完全相同，或 suggested 为空）──────────
    for r in all_results:
        r['issues'] = [
            iss for iss in r.get('issues', [])
            if iss.get('suggested', '').strip()
            and iss.get('suggested', '').strip() != iss.get('original', '').strip()
        ]

    issues_only = [r for r in all_results if r.get('issues')]
    return jsonify({
        'total_checked': len(questions),
        'issues_found': len(issues_only),
        'results': issues_only,
    })


@interview_bp.route('/api/interview/sessions/<int:session_id>/quality-check/stream', methods=['GET'])
@login_required
def quality_check_session_stream(session_id):
    """SSE 流式质量检查：逐批推送进度，最后推送完整结果。"""
    user = get_current_user()
    _, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    import time as _time

    def _sse(obj):
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    @stream_with_context
    def generate():
        from app.rag_routes import _get_deepseek_key
        api_key = _get_deepseek_key()
        if not api_key:
            yield _sse({'type': 'error', 'message': '未配置 DeepSeek API Key，请在「API 配置」中填写'})
            return

        sets = _fetch("SELECT question_ids_json FROM interview_sets WHERE session_id=:sid", sid=session_id)
        if not sets:
            yield _sse({'type': 'error', 'message': '场次不存在或尚未生成套题'})
            return

        all_qids = []
        for s in sets:
            try:
                all_qids.extend(json.loads(s['question_ids_json'] or '[]'))
            except Exception:
                pass
        unique_qids = list(dict.fromkeys(qid for qid in all_qids if qid))
        if not unique_qids:
            yield _sse({'type': 'error', 'message': '该场次无题目'})
            return

        questions = []
        for qid in unique_qids:
            q = _fetch_one(
                "SELECT question_id, content, content_en, reference_answer FROM questions WHERE question_id=:qid",
                qid=qid
            )
            if q:
                questions.append({
                    'question_id': q['question_id'],
                    'content': _strip_html(q['content'] or ''),
                    'content_en': _strip_html(q['content_en'] or ''),
                    'reference_answer': _strip_html(q['reference_answer'] or ''),
                })

        total = len(questions)
        yield _sse({'type': 'start', 'total': total})

        try:
            from openai import OpenAI as _OAI
        except ImportError:
            yield _sse({'type': 'error', 'message': '缺少 openai 依赖，请 pip install openai'})
            return

        ds = _OAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=120)
        BATCH = 8
        all_results = []

        for i in range(0, total, BATCH):
            batch = questions[i:i + BATCH]
            batch_end = min(i + BATCH, total)
            yield _sse({'type': 'progress', 'checked': i, 'total': total,
                        'batch_start': i + 1, 'batch_end': batch_end})
            try:
                batch_results = _qc_call_deepseek(ds, batch)
                all_results.extend(batch_results)
            except Exception as e:
                yield _sse({'type': 'error', 'message': f'第 {i+1}~{batch_end} 题调用失败：{e}'})
                return
            if i + BATCH < total:
                _time.sleep(0.4)

        for r in all_results:
            r['issues'] = [
                iss for iss in r.get('issues', [])
                if iss.get('suggested', '').strip()
                and iss.get('suggested', '').strip() != iss.get('original', '').strip()
            ]
        issues_only = [r for r in all_results if r.get('issues')]
        yield _sse({'type': 'done', 'total_checked': total,
                    'issues_found': len(issues_only), 'results': issues_only})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


_QC_SYSTEM = """你是专业面试题库质检员。只检查以下两类明确错误，发现则报告，否则issues数组为空。

1. stem_answer_confusion（题干答案混淆）：
   - 题干(content)字段中包含完整答案内容（如"X是指…包括…特点…"这类定义式内容被混入题干）
   - reference_answer为"（空）"但题干里已经包含了答案性陈述
   - content字段包含多个互不相关的独立问题（数据导入错误）

2. grammar_error（英文语法错误）：
   - 仅检查content_en（英文题干），content_en为空则跳过
   - 只报告明确的语法错误：主谓不一致、冠词误用、明确的介词错误、句子结构不完整等
   - 不报告主观措辞偏好，只报告明确错误

注意：
- 简答题参考答案详细展开是正常的，不算混淆
- 参考答案较长不是问题
- 不要报告基于推测的问题，只报告有明确证据的错误
- 只返回JSON，不加markdown代码块"""

_QC_USER_TPL = """检查以下{n}道题目，返回JSON结果。

题目列表：
{qs_json}

返回格式（严格JSON）：
{{"results":[{{"question_id":"...","issues":[{{"type":"stem_answer_confusion或grammar_error","field":"content或content_en或reference_answer","description":"问题描述","original":"原文节选","suggested":"修正后的完整内容"}}]}}]}}"""


def _qc_call_deepseek(ds_client, batch):
    """调用 DeepSeek 检查一批题目，返回 results 列表。"""
    payload = []
    for q in batch:
        payload.append({
            'question_id': q['question_id'],
            'content': q['content'],
            'content_en': q['content_en'] if q['content_en'] else '',
            'reference_answer': q['reference_answer'] if q['reference_answer'] else '（空）',
        })
    user_msg = _QC_USER_TPL.format(
        n=len(payload),
        qs_json=json.dumps(payload, ensure_ascii=False, indent=2)
    )
    try:
        resp = ds_client.chat.completions.create(
            model='deepseek-chat',
            temperature=0.1,
            max_tokens=4096,
            messages=[
                {'role': 'system', 'content': _QC_SYSTEM},
                {'role': 'user', 'content': user_msg},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw).get('results', [])
    except Exception as e:
        return [{'question_id': q['question_id'], 'issues': [], '_error': str(e)} for q in batch]


@interview_bp.route('/api/interview/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    """删除指定场次及其所有套题，并重置受影响题目的 drawn 状态。"""
    user = get_current_user()
    sess, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    pool_id = sess['pool_id']

    # 收集该场次所有套题中的题目 ID
    sets = _fetch("SELECT question_ids_json FROM interview_sets WHERE session_id=:sid", sid=session_id)
    affected_qids = []
    for s in sets:
        try:
            affected_qids.extend([q for q in json.loads(s['question_ids_json'] or '[]') if q])
        except Exception:
            pass

    # 删除套题和场次
    _run("DELETE FROM interview_sets WHERE session_id=:sid", sid=session_id)
    _run("DELETE FROM interview_sessions WHERE id=:sid", sid=session_id)

    # 重新计算 drawn 状态：遍历剩余所有套题，找出仍在套题中的题目
    remaining_sets = _fetch("SELECT question_ids_json FROM interview_sets")
    still_in_set = set()
    for s in remaining_sets:
        try:
            for qid in json.loads(s['question_ids_json'] or '[]'):
                if qid:
                    still_in_set.add(qid)
        except Exception:
            pass

    for qid in set(affected_qids):
        if qid not in still_in_set:
            _run(
                "UPDATE interview_pool_questions SET drawn=0, drawn_at=NULL WHERE pool_id=:pid AND question_id=:qid",
                pid=pool_id, qid=qid
            )

    _sync_question_interview_status(list(set(affected_qids)), owner_id=user.id)
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/sets/<int:set_id>/candidates', methods=['GET'])
@login_required
def get_replacement_candidates(set_id):
    """获取指定槽位的可替换候选题目（同池、未被使用、同题型）。"""
    slot_index = request.args.get('slot_index', default=0, type=int)

    user = get_current_user()
    s, sess, err = _check_set_access(set_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    pool_id = sess['pool_id']

    question_ids = json.loads(s['question_ids_json'] or '[]')

    # 从配置中获取该槽位的题型
    question_type = None
    if sess['config_id']:
        cfg = _fetch_one("SELECT slots_json FROM interview_configs WHERE id=:id", id=sess['config_id'])
        if cfg:
            try:
                slots = json.loads(cfg['slots_json'] or '[]')
                if slot_index < len(slots):
                    question_type = slots[slot_index].get('question_type')
            except Exception:
                pass

    # 查询同池中 drawn=0 的题目，在 Python 层过滤
    candidates_raw = _fetch(
        """SELECT ipq.question_id, q.content, q.question_type, q.subject,
                  q.difficulty, q.language, q.knowledge_point
           FROM interview_pool_questions ipq
           JOIN questions q ON q.question_id = ipq.question_id
           WHERE ipq.pool_id = :pid AND ipq.drawn = 0""",
        pid=pool_id
    )

    excluded = set(qid for qid in question_ids if qid)
    candidates = [
        c for c in candidates_raw
        if c['question_id'] not in excluded
        and (not question_type or c['question_type'] == question_type)
    ]
    # 为每道题添加内容预览（用于前端搜索和展示）
    for c in candidates:
        c['content_preview'] = _strip_html(c['content'] or '')[:200]

    return jsonify({
        'candidates': candidates[:300],
        'question_type': question_type,
        'current_qid': question_ids[slot_index] if slot_index < len(question_ids) else None,
    })


@interview_bp.route('/api/interview/sets/<int:set_id>/replace', methods=['POST'])
@login_required
def replace_question_in_set(set_id):
    """替换套题中某槽位的题目。"""
    data = request.get_json(silent=True) or {}
    slot_index = data.get('slot_index')
    new_qid = (data.get('new_question_id') or '').strip()

    if slot_index is None or not new_qid:
        return jsonify({'error': '缺少 slot_index 或 new_question_id'}), 400

    user = get_current_user()
    s, sess, err = _check_set_access(set_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]
    pool_id = sess['pool_id']

    question_ids = json.loads(s['question_ids_json'] or '[]')
    if slot_index >= len(question_ids):
        return jsonify({'error': '槽位索引越界'}), 400

    old_qid = question_ids[slot_index]
    question_ids[slot_index] = new_qid

    # 更新 question_ids_json
    _run("UPDATE interview_sets SET question_ids_json=:qj WHERE id=:id",
         qj=json.dumps(question_ids), id=set_id)

    # 重置旧题目的 drawn（若其不在任何其他套题中）
    if old_qid:
        remaining_sets = _fetch("SELECT question_ids_json FROM interview_sets WHERE id != :id", id=set_id)
        old_still_in_set = any(
            old_qid in json.loads(rs['question_ids_json'] or '[]')
            for rs in remaining_sets
        )
        if not old_still_in_set:
            _run(
                "UPDATE interview_pool_questions SET drawn=0, drawn_at=NULL WHERE pool_id=:pid AND question_id=:qid",
                pid=pool_id, qid=old_qid
            )

    # 标记新题目为已使用
    _run(
        "UPDATE interview_pool_questions SET drawn=1, drawn_at=:t WHERE pool_id=:pid AND question_id=:qid",
        t=_now_str(), pid=pool_id, qid=new_qid
    )

    affected = [q for q in [old_qid, new_qid] if q]
    _sync_question_interview_status(affected, owner_id=user.id)
    return jsonify({'ok': True, 'question_ids': question_ids})


@interview_bp.route('/api/interview/sets/batch-use', methods=['POST'])
@login_required
def batch_use_sets():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    set_ids = data.get('set_ids', [])
    if not set_ids:
        return jsonify({'error': '未提供 set_ids'}), 400
    now = _now_str()
    updated = 0
    all_qids = []
    for sid in set_ids:
        s, _, err = _check_set_access(sid, user)
        if err:
            return jsonify({'error': err[0]}), err[1]
        try:
            all_qids.extend([q for q in json.loads(s['question_ids_json'] or '[]') if q])
        except Exception:
            pass
        _run("UPDATE interview_sets SET is_used=1, used_at=:t WHERE id=:id", t=now, id=sid)
        updated += 1
    _sync_question_interview_status(all_qids, owner_id=user.id)
    return jsonify({'ok': True, 'updated': updated})


def _get_questions_brief(qids):
    result = []
    for qid in qids:
        if not qid:
            result.append(None)
            continue
        row = _fetch_one(
            "SELECT question_id, question_type, subject, content, difficulty, language FROM questions WHERE question_id=:qid",
            qid=qid
        )
        if row:
            row['content_preview'] = _strip_html(row['content'])[:100]
        result.append(row)
    return result


def _get_questions_full(qids):
    result = []
    for qid in qids:
        if not qid:
            result.append(None)
            continue
        row = _fetch_one(
            """SELECT question_id, question_type, subject, difficulty, language,
                      knowledge_point, tags, content, options, answer,
                      reference_answer, explanation, content_en, options_en
               FROM questions WHERE question_id=:qid""",
            qid=qid
        )
        if row:
            try:
                row['options'] = json.loads(row['options']) if row['options'] else []
            except Exception:
                row['options'] = []
            try:
                row['options_en'] = json.loads(row['options_en']) if row['options_en'] else []
            except Exception:
                row['options_en'] = []
        result.append(row)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 7. Word 导出
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/export/word', methods=['POST'])
@login_required
def export_word():
    """将指定套题导出为 Word 文档（含答案，保留富文本格式）。"""
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    set_ids = data.get('set_ids', [])
    include_answers = data.get('include_answers', True)
    filename_base = (data.get('filename') or '面试套题').strip()

    if not set_ids:
        return jsonify({'error': '未指定套题'}), 400

    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from app.utils import _add_html_to_doc

    doc = Document()

    # 页边距
    section = doc.sections[0]
    section.left_margin = Cm(3)
    section.right_margin = Cm(2.5)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)

    for order_idx, set_id in enumerate(set_ids):
        s, _, err = _check_set_access(set_id, user)
        if err:
            return jsonify({'error': err[0]}), err[1]
        qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
        questions = _get_questions_full(qids)

        # 每套题标题
        if order_idx > 0:
            doc.add_page_break()
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = heading.add_run(f"{s['set_code']}")
        run.bold = True
        run.font.size = Pt(14)

        sep = doc.add_paragraph('─' * 40)
        sep.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for q_idx, q in enumerate(questions):
            if not q:
                continue
            q_num = q_idx + 1
            type_label = q.get('question_type', '')

            # 题号+题型标签
            label_para = doc.add_paragraph()
            label_run = label_para.add_run(f'第{q_num}题  【{type_label}】')
            label_run.bold = True
            label_run.font.size = Pt(11)

            # 题干（中文）
            _add_html_to_doc(doc, q.get('content') or '', size_pt=11,
                             indent_cm=0.5, prefix_text='题目：')

            # 英文题干（如有）
            if q.get('content_en'):
                _add_html_to_doc(doc, q['content_en'], size_pt=11,
                                 indent_cm=0.5, prefix_text='Q: ')

            # 选项（如有）
            options = q.get('options') or []
            if options:
                letters = 'ABCDEFGHIJ'
                for oi, opt in enumerate(options):
                    opt_text = f'{letters[oi]}. {opt}'
                    p = doc.add_paragraph(opt_text)
                    p.paragraph_format.left_indent = Cm(1)
                    for run in p.runs:
                        run.font.size = Pt(10.5)

            # 答案 / 参考答案
            if include_answers:
                ans = q.get('answer') or ''
                ref = q.get('reference_answer') or ''
                if ans:
                    _add_html_to_doc(doc, ans, size_pt=10.5,
                                     indent_cm=0.5, prefix_text='答案：')
                if ref:
                    _add_html_to_doc(doc, ref, size_pt=10.5,
                                     indent_cm=0.5, prefix_text='参考答案：')

            doc.add_paragraph('')  # 题目间空行

    # 保存到内存
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    safe_name = re.sub(r'[^\w\-_\u4e00-\u9fff]', '_', filename_base)
    date_str = datetime.now().strftime('%Y%m%d')
    dl_name = f'{safe_name}_{date_str}.docx'

    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=dl_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Excel 导出
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/export-xlsx', methods=['GET'])
@login_required
def export_pool_xlsx(pool_id):
    """导出面试题库池到 Excel（含完整题目信息，支持跨机器导入）。"""
    user = get_current_user()
    pool, err = _check_pool_access(pool_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    rows = _fetch("""
        SELECT ipq.drawn, ipq.drawn_at, ipq.added_at,
               q.question_id, q.question_type, q.subject, q.difficulty,
               q.language, q.knowledge_point, q.tags,
               q.content, q.answer, q.reference_answer, q.explanation,
               q.content_en, q.options, q.options_en
        FROM interview_pool_questions ipq
        JOIN questions q ON q.question_id=ipq.question_id
        WHERE ipq.pool_id=:pid
        ORDER BY ipq.added_at
    """, pid=pool_id)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '面试题库池'

    headers = [
        'question_id', 'question_type', 'subject', 'difficulty', 'language',
        'knowledge_point', 'tags', 'content', 'answer', 'reference_answer',
        'explanation', 'content_en', 'options', 'options_en', 'drawn', 'drawn_at', 'added_at'
    ]
    header_fill = PatternFill('solid', fgColor='366092')
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', wrap_text=True)

    for r_idx, row in enumerate(rows, 2):
        values = [
            row.get('question_id', ''),
            row.get('question_type', ''),
            row.get('subject', ''),
            row.get('difficulty', ''),
            row.get('language', ''),
            row.get('knowledge_point', ''),
            row.get('tags', ''),
            _strip_html(row.get('content') or ''),
            _strip_html(row.get('answer') or ''),
            _strip_html(row.get('reference_answer') or ''),
            _strip_html(row.get('explanation') or ''),
            _strip_html(row.get('content_en') or ''),
            row.get('options', ''),
            row.get('options_en', ''),
            '已抽取' if row.get('drawn') else '可用',
            row.get('drawn_at', '') or '',
            row.get('added_at', '') or '',
        ]
        for col_idx, v in enumerate(values, 1):
            ws.cell(row=r_idx, column=col_idx, value=v)

    # 列宽
    col_widths = [20, 12, 15, 10, 8, 20, 20, 60, 40, 60, 40, 60, 30, 30, 8, 18, 18]
    for col_idx, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_pool = re.sub(r'[^\w\-_\u4e00-\u9fff]', '_', pool['pool_name'])
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'面试题库池_{safe_pool}_{date_str}.xlsx',
    )


@interview_bp.route('/api/interview/sessions/<int:session_id>/export-xlsx', methods=['GET'])
@login_required
def export_sets_xlsx(session_id):
    """导出指定场次的套题记录到 Excel（双 Sheet）。"""
    user = get_current_user()
    sess, err = _check_session_access(session_id, user)
    if err:
        return jsonify({'error': err[0]}), err[1]

    sets = _fetch(
        "SELECT * FROM interview_sets WHERE session_id=:sid ORDER BY id",
        sid=session_id
    )

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.Workbook()

    # ── Sheet1: 套题列表 ──────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = '套题列表'
    h1 = ['set_id', 'set_code', 'session_name', 'question_ids', 'is_used', 'used_at', 'created_at']
    header_fill = PatternFill('solid', fgColor='366092')
    for col_idx, h in enumerate(h1, 1):
        cell = ws1.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    for r_idx, s in enumerate(sets, 2):
        qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
        ws1.cell(row=r_idx, column=1, value=s['id'])
        ws1.cell(row=r_idx, column=2, value=s['set_code'])
        ws1.cell(row=r_idx, column=3, value=sess['session_name'])
        ws1.cell(row=r_idx, column=4, value=','.join(str(q) for q in qids if q))
        ws1.cell(row=r_idx, column=5, value='已使用' if s['is_used'] else '未使用')
        ws1.cell(row=r_idx, column=6, value=s.get('used_at') or '')
        ws1.cell(row=r_idx, column=7, value=s.get('created_at') or '')

    for col_idx, w in enumerate([8, 12, 30, 40, 8, 18, 18], 1):
        ws1.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w

    # ── Sheet2: 题目详情 ──────────────────────────────────────────────────────
    ws2 = wb.create_sheet('题目详情')
    h2 = ['set_code', 'slot_index', 'question_id', 'question_type', 'subject',
          'difficulty', 'language', 'content', 'answer', 'reference_answer', 'explanation']
    for col_idx, h in enumerate(h2, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    detail_row = 2
    for s in sets:
        qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
        questions = _get_questions_full(qids)
        for slot_idx, q in enumerate(questions):
            if not q:
                continue
            ws2.cell(row=detail_row, column=1, value=s['set_code'])
            ws2.cell(row=detail_row, column=2, value=slot_idx + 1)
            ws2.cell(row=detail_row, column=3, value=q.get('question_id', ''))
            ws2.cell(row=detail_row, column=4, value=q.get('question_type', ''))
            ws2.cell(row=detail_row, column=5, value=q.get('subject', ''))
            ws2.cell(row=detail_row, column=6, value=q.get('difficulty', ''))
            ws2.cell(row=detail_row, column=7, value=q.get('language', ''))
            ws2.cell(row=detail_row, column=8, value=_strip_html(q.get('content') or ''))
            ws2.cell(row=detail_row, column=9, value=_strip_html(q.get('answer') or ''))
            ws2.cell(row=detail_row, column=10, value=_strip_html(q.get('reference_answer') or ''))
            ws2.cell(row=detail_row, column=11, value=_strip_html(q.get('explanation') or ''))
            detail_row += 1

    for col_idx, w in enumerate([12, 8, 20, 12, 15, 10, 8, 60, 40, 60, 40], 1):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = re.sub(r'[^\w\-_\u4e00-\u9fff]', '_', sess['session_name'])
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'面试套题_{safe_name}_{date_str}.xlsx',
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Excel 导入
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/import-xlsx', methods=['POST'])
@login_required
def import_pool_xlsx(pool_id):
    """
    从 Excel 导入题目到面试题库池。
    支持跨机器迁移：若 question_id 在本地不存在，自动从 Excel 行数据中新建题目。
    支持自动匹配和创建新题型。
    """
    from sqlalchemy import text
    from app.db_models import QuestionTypeModel
    from app.routes import _match_question_type, _ensure_question_type
    
    user = get_current_user()
    pool, perr = _check_pool_access(pool_id, user)
    if perr:
        return jsonify({'error': perr[0]}), perr[1]

    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': '只支持 .xlsx 格式'}), 400

    try:
        import openpyxl
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.load_workbook(f, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return jsonify({'error': 'Excel 为空或仅有表头'}), 400

    headers = [str(h).strip().lower() if h else '' for h in rows[0]]

    def _col(row, name):
        try:
            idx = headers.index(name)
            return row[idx] if row[idx] is not None else ''
        except ValueError:
            return ''

    added = 0
    skipped = 0
    created = 0
    created_types = []  # 记录新创建的题型
    now = _now_str()
    
    # 获取已知题型
    known_types = {
        qt.name for qt in QuestionTypeModel.query.filter(
            db.or_(
                QuestionTypeModel.owner_id.is_(None),
                QuestionTypeModel.owner_id == user.id,
            )
        ).all()
    }

    for row in rows[1:]:
        qid = str(_col(row, 'question_id')).strip()
        if not qid:
            continue

        # 检查题目是否存在于本地
        existing_q = QuestionModel.query.filter_by(question_id=qid).first()
        if not existing_q:
            # 跨机器导入：从 Excel 行数据新建题目
            raw_qtype = str(_col(row, 'question_type') or '简答').strip()
            
            # 处理题型匹配和创建
            qtype, is_builtin, needs_create = _match_question_type(raw_qtype, known_types)
            if needs_create:
                final_type, error = _ensure_question_type(raw_qtype, user)
                if error:
                    skipped += 1
                    continue
                qtype = final_type
                if qtype not in known_types:
                    known_types.add(qtype)
                    created_types.append(qtype)
            
            content_text = str(_col(row, 'content') or '').strip()
            if not content_text:
                continue
            now_dt = datetime.now()
            new_q = QuestionModel(
                question_id=qid,
                question_type=qtype,
                content=content_text,
                options=json.dumps([], ensure_ascii=False),
                answer=str(_col(row, 'answer') or ''),
                reference_answer=str(_col(row, 'reference_answer') or ''),
                explanation=str(_col(row, 'explanation') or ''),
                content_en=str(_col(row, 'content_en') or '') or None,
                subject=str(_col(row, 'subject') or '') or None,
                knowledge_point=str(_col(row, 'knowledge_point') or '') or None,
                tags=str(_col(row, 'tags') or '') or None,
                difficulty=str(_col(row, 'difficulty') or '') or None,
                language=str(_col(row, 'language') or 'zh'),
                metadata_json='{}',
                is_used=False,
                owner_id=user.id,
                visibility='private',
                created_at=now_dt,
                updated_at=now_dt,
            )
            db.session.add(new_q)
            try:
                db.session.flush()
                created += 1
            except Exception:
                db.session.rollback()
                continue

        # 加入面试池（用 db.session 避免与 ORM 写锁冲突）
        try:
            db.session.execute(
                text("INSERT OR IGNORE INTO interview_pool_questions (pool_id, question_id, added_at) VALUES (:pid, :qid, :t)"),
                dict(pid=pool_id, qid=qid, t=now)
            )
            added += 1
        except Exception:
            skipped += 1

    db.session.commit()
    # 同步所有被加入池的题目状态
    all_pool_qids = _fetch(
        "SELECT question_id FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id
    )
    _sync_question_interview_status([r['question_id'] for r in all_pool_qids], owner_id=user.id)
    
    result = {'ok': True, 'added': added, 'skipped': skipped, 'created_questions': created}
    if created_types:
        result['created_types'] = list(set(created_types))  # 去重
    return jsonify(result)


@interview_bp.route('/api/interview/sessions/import-xlsx/prepare', methods=['POST'])
@login_required
def prepare_import_sets_xlsx():
    """
    预检 Excel 文件：解析题目数、套题数，并返回现有题库池列表供前端决策。
    """
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': '只支持 .xlsx 格式'}), 400

    try:
        import openpyxl
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.load_workbook(f, read_only=True)

    question_count = 0
    if '题目详情' in wb.sheetnames:
        rows2 = list(wb['题目详情'].iter_rows(values_only=True))
        question_count = max(0, len(rows2) - 1)

    set_count = 0
    if '套题列表' in wb.sheetnames:
        rows1 = list(wb['套题列表'].iter_rows(values_only=True))
        set_count = max(0, len(rows1) - 1)

    user = get_current_user()
    if user.role == 'admin':
        pools = _fetch("SELECT id, pool_name FROM interview_pools ORDER BY id")
    else:
        pools = _fetch("SELECT id, pool_name FROM interview_pools WHERE owner_id=:uid ORDER BY id", uid=user.id)
    return jsonify({
        'ok': True,
        'question_count': question_count,
        'set_count': set_count,
        'existing_pools': [{'id': p['id'], 'pool_name': p['pool_name']} for p in pools],
    })


@interview_bp.route('/api/interview/sessions/import-xlsx', methods=['POST'])
@login_required
def import_sets_xlsx():
    """
    从 Excel 导入套题记录（Sheet1: 套题列表, Sheet2: 题目详情）。
    支持 pool_mode=new（自动建池）或 pool_mode=existing（加入已有池）。
    场次名由调用方通过 session_name 参数指定。
    """
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': '只支持 .xlsx 格式'}), 400

    session_name = (request.form.get('session_name') or '').strip()
    if not session_name:
        return jsonify({'error': '缺少场次名称'}), 400

    pool_mode = request.form.get('pool_mode', 'new')
    user = get_current_user()

    if pool_mode == 'existing':
        pool_id_str = request.form.get('pool_id')
        if not pool_id_str:
            return jsonify({'error': '缺少 pool_id 参数'}), 400
        pool_id = int(pool_id_str)
        pool_row, perr = _check_pool_access(pool_id, user)
        if perr:
            return jsonify({'error': perr[0]}), perr[1]
        pool_name = pool_row['pool_name']
    else:
        # 新建题库池
        from sqlalchemy import text
        new_pool_name = f'{session_name}-题库池'
        r = db.session.execute(
            text("INSERT INTO interview_pools (pool_name, description, created_at, owner_id) VALUES (:n, :d, :t, :uid)"),
            dict(n=new_pool_name, d='由套题导入自动创建', t=_now_str(), uid=user.id)
        )
        pool_id = r.lastrowid
        pool_name = new_pool_name

    try:
        import openpyxl
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    wb = openpyxl.load_workbook(f, read_only=True)

    # ── 先处理 Sheet2 题目详情，建立 question_id → 题目数据 映射 ─────────────
    q_detail_map = {}
    if '题目详情' in wb.sheetnames:
        ws2 = wb['题目详情']
        rows2 = list(ws2.iter_rows(values_only=True))
        if rows2:
            h2 = [str(h).strip().lower() if h else '' for h in rows2[0]]
            def _c2(row, name):
                try:
                    return row[h2.index(name)] if h2.index(name) < len(row) else ''
                except ValueError:
                    return ''
            for row in rows2[1:]:
                qid = str(_c2(row, 'question_id') or '').strip()
                if qid:
                    q_detail_map[qid] = {
                        'question_id': qid,
                        'question_type': str(_c2(row, 'question_type') or '简答'),
                        'subject': str(_c2(row, 'subject') or ''),
                        'difficulty': str(_c2(row, 'difficulty') or ''),
                        'language': str(_c2(row, 'language') or 'zh'),
                        'content': str(_c2(row, 'content') or ''),
                        'answer': str(_c2(row, 'answer') or ''),
                        'reference_answer': str(_c2(row, 'reference_answer') or ''),
                        'explanation': str(_c2(row, 'explanation') or ''),
                    }

    # 确保题目存在，并将题目加入目标题库池
    now_dt = datetime.now()
    now = _now_str()
    created_questions = 0
    questions_added = 0
    questions_skipped = 0

    for qid, qdata in q_detail_map.items():
        # 确保题目在 questions 表中存在
        if not QuestionModel.query.filter_by(question_id=qid).first():
            if not qdata['content']:
                continue
            new_q = QuestionModel(
                question_id=qid,
                question_type=qdata['question_type'],
                content=qdata['content'],
                options=json.dumps([], ensure_ascii=False),
                answer=qdata['answer'],
                reference_answer=qdata['reference_answer'],
                explanation=qdata['explanation'],
                subject=qdata['subject'] or None,
                difficulty=qdata['difficulty'] or None,
                language=qdata['language'] or 'zh',
                metadata_json='{}',
                is_used=False,
                owner_id=user.id,
                visibility='private',
                created_at=now_dt,
                updated_at=now_dt,
            )
            db.session.add(new_q)
            created_questions += 1

        # 检查题目是否已在目标池中，决定跳过还是加入
        existing = _fetch_one(
            "SELECT id FROM interview_pool_questions WHERE pool_id=:pid AND question_id=:qid",
            pid=pool_id, qid=qid
        )
        if existing:
            questions_skipped += 1
        else:
            db.session.execute(
                text("INSERT OR IGNORE INTO interview_pool_questions (pool_id, question_id, drawn, added_at) VALUES (:p, :q, 0, :t)"),
                dict(p=pool_id, q=qid, t=now)
            )
            questions_added += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    # ── 处理 Sheet1 套题列表 ──────────────────────────────────────────────────
    if '套题列表' not in wb.sheetnames:
        return jsonify({'error': 'Excel 中缺少"套题列表" Sheet'}), 400

    ws1 = wb['套题列表']
    rows1 = list(ws1.iter_rows(values_only=True))
    if len(rows1) < 2:
        return jsonify({'error': '"套题列表"为空'}), 400

    h1 = [str(h).strip().lower() if h else '' for h in rows1[0]]
    def _c1(row, name):
        try:
            idx = h1.index(name)
            return row[idx] if row[idx] is not None else ''
        except ValueError:
            return ''

    # 创建导入场次（使用用户自定义场次名）
    from sqlalchemy import text
    r2 = db.session.execute(text("""
        INSERT INTO interview_sessions
          (pool_id, config_id, session_name, interview_count, sets_multiplier, score_per_slot_json, created_at, owner_id)
        VALUES (:pid, NULL, :sn, 0, 1, '{}', :t, :uid)
    """), {'pid': pool_id, 'sn': session_name, 't': now, 'uid': user.id})
    session_id = r2.lastrowid

    sets_imported = 0
    for row in rows1[1:]:
        set_code = str(_c1(row, 'set_code') or '').strip()
        qids_str = str(_c1(row, 'question_ids') or '').strip()
        is_used_str = str(_c1(row, 'is_used') or '').strip()
        used_at_str = str(_c1(row, 'used_at') or '').strip()

        if not set_code:
            continue

        qids = [q.strip() for q in qids_str.split(',') if q.strip()] if qids_str else []
        is_used = 1 if is_used_str in ('已使用', '1', 'True', 'true') else 0
        used_at = used_at_str if (is_used and used_at_str) else None

        db.session.execute(text("""
            INSERT INTO interview_sets (session_id, set_code, question_ids_json, is_used, used_at, created_at)
            VALUES (:sid, :sc, :qj, :iu, :ua, :t)
        """), dict(sid=session_id, sc=set_code,
             qj=json.dumps(qids, ensure_ascii=False),
             iu=is_used, ua=used_at, t=now))
        sets_imported += 1

    db.session.commit()
    return jsonify({
        'ok': True,
        'session_id': session_id,
        'session_name': session_name,
        'pool_id': pool_id,
        'pool_name': pool_name,
        'sets_imported': sets_imported,
        'created_questions': created_questions,
        'questions_added': questions_added,
        'questions_skipped': questions_skipped,
    })
