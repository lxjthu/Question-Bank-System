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

from flask import Blueprint, request, jsonify, send_file

from app.db_models import db, QuestionModel

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


# ─────────────────────────────────────────────────────────────────────────────
# 1. 题库池管理
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools', methods=['GET'])
def list_pools():
    pools = _fetch("SELECT * FROM interview_pools ORDER BY id")
    # 附加每个池的题目数量
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
def create_pool():
    data = request.get_json(silent=True) or {}
    name = (data.get('pool_name') or '').strip()
    if not name:
        return jsonify({'error': '池名称不能为空'}), 400
    desc = (data.get('description') or '').strip()
    _run(
        "INSERT INTO interview_pools (pool_name, description, created_at) VALUES (:n, :d, :t)",
        n=name, d=desc, t=_now_str()
    )
    pool = _fetch_one("SELECT * FROM interview_pools WHERE pool_name=:n ORDER BY id DESC LIMIT 1", n=name)
    return jsonify({'pool': pool}), 201


@interview_bp.route('/api/interview/pools/<int:pool_id>', methods=['PUT'])
def update_pool(pool_id):
    pool = _fetch_one("SELECT * FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get('pool_name') or pool['pool_name']).strip()
    desc = (data.get('description') or pool['description'] or '').strip()
    _run("UPDATE interview_pools SET pool_name=:n, description=:d WHERE id=:id",
         n=name, d=desc, id=pool_id)
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/pools/<int:pool_id>', methods=['DELETE'])
def delete_pool(pool_id):
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404
    _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    _run("DELETE FROM interview_configs WHERE pool_id=:pid", pid=pool_id)
    # 注意：不删除关联的 sessions/sets，它们保留历史记录
    _run("DELETE FROM interview_pools WHERE id=:id", id=pool_id)
    return jsonify({'ok': True})


# ─────────────────────────────────────────────────────────────────────────────
# 2. 池中题目管理
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/questions', methods=['GET'])
def list_pool_questions(pool_id):
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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
def pool_stats(pool_id):
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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
def preview_filter(pool_id):
    """预览筛选结果（不实际加入池），返回命中题目数量和摘要列表。"""
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

    data = request.get_json(silent=True) or {}
    qs, params = _build_filter_query(data, pool_id, exclude_pool=True)
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
            'content_preview': _strip_html(r['content'])[:80],
        }
        for r in rows
    ]
    return jsonify({'count': len(preview), 'questions': preview})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/add', methods=['POST'])
def add_to_pool(pool_id):
    """按筛选条件将题目批量加入池。"""
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

    data = request.get_json(silent=True) or {}
    qs, params = _build_filter_query(data, pool_id, exclude_pool=True)
    rows = _fetch(qs, **params)

    added = 0
    now = _now_str()
    for r in rows:
        try:
            _run(
                "INSERT OR IGNORE INTO interview_pool_questions (pool_id, question_id, added_at) VALUES (:pid, :qid, :t)",
                pid=pool_id, qid=r['question_id'], t=now
            )
            added += 1
        except Exception:
            pass
    return jsonify({'ok': True, 'added': added})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions/remove', methods=['POST'])
def remove_from_pool(pool_id):
    data = request.get_json(silent=True) or {}
    qids = data.get('question_ids', [])
    if not qids:
        return jsonify({'error': '未提供 question_ids'}), 400
    removed = 0
    for qid in qids:
        _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid AND question_id=:qid",
             pid=pool_id, qid=qid)
        removed += 1
    return jsonify({'ok': True, 'removed': removed})


@interview_bp.route('/api/interview/pools/<int:pool_id>/questions', methods=['DELETE'])
def clear_pool(pool_id):
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404
    _run("DELETE FROM interview_pool_questions WHERE pool_id=:pid", pid=pool_id)
    return jsonify({'ok': True})


def _build_filter_query(data, pool_id, exclude_pool=False):
    """Build SELECT query from filter dict. Returns (sql, params_dict)."""
    conds = ['1=1']
    params = {}

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
def get_config(pool_id):
    cfg = _fetch_one(
        "SELECT * FROM interview_configs WHERE pool_id=:pid ORDER BY updated_at DESC LIMIT 1",
        pid=pool_id
    )
    if not cfg:
        return jsonify({'config': None, 'slots': []})
    slots = json.loads(cfg['slots_json']) if cfg['slots_json'] else []
    return jsonify({'config': cfg, 'slots': slots})


@interview_bp.route('/api/interview/pools/<int:pool_id>/config', methods=['PUT'])
def save_config(pool_id):
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

    data = request.get_json(silent=True) or {}
    slots = data.get('slots', [])
    if not slots:
        return jsonify({'error': '套题配置至少需要一个槽位'}), 400

    # 校验每个槽位
    for i, slot in enumerate(slots):
        if not slot.get('question_type'):
            return jsonify({'error': f'第 {i+1} 个槽位缺少题型'}), 400

    slots_json = json.dumps(slots, ensure_ascii=False)
    now = _now_str()
    cfg_name = (data.get('config_name') or 'default').strip()

    existing = _fetch_one(
        "SELECT id FROM interview_configs WHERE pool_id=:pid LIMIT 1",
        pid=pool_id
    )
    if existing:
        _run(
            "UPDATE interview_configs SET slots_json=:sj, config_name=:cn, updated_at=:t WHERE pool_id=:pid",
            sj=slots_json, cn=cfg_name, t=now, pid=pool_id
        )
    else:
        _run(
            "INSERT INTO interview_configs (pool_id, config_name, slots_json, created_at, updated_at) VALUES (:pid, :cn, :sj, :t, :t)",
            pid=pool_id, cn=cfg_name, sj=slots_json, t=now
        )
    return jsonify({'ok': True, 'slots': slots})


# ─────────────────────────────────────────────────────────────────────────────
# 4. 警告检查
# ─────────────────────────────────────────────────────────────────────────────

@interview_bp.route('/api/interview/pools/<int:pool_id>/check', methods=['POST'])
def check_pool(pool_id):
    """校验池中可用题目是否满足生成 N 套题的需求。"""
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
def list_sessions():
    rows = _fetch("SELECT * FROM interview_sessions ORDER BY id DESC")
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

    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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
              (pool_id, config_id, session_name, interview_count, sets_multiplier, score_per_slot_json, created_at)
            VALUES (:pid, :cid, :sn, :ic, :sm, :sp, :t)
        """), {
            'pid': pool_id, 'cid': cfg['id'], 'sn': session_name,
            'ic': interview_count, 'sm': sets_multiplier,
            'sp': json.dumps(score_per_slot, ensure_ascii=False), 't': now
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
def list_sets(session_id):
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
def draw_set(session_id):
    """从指定场次中随机抽取一套未使用的套题并标记为已使用。"""
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

    return jsonify({
        'ok': True,
        'set_id': chosen['id'],
        'set_code': chosen['set_code'],
        'used_at': now,
        'questions': questions,
    })


@interview_bp.route('/api/interview/sets/<int:set_id>', methods=['GET'])
def get_set_detail(set_id):
    s = _fetch_one("SELECT * FROM interview_sets WHERE id=:id", id=set_id)
    if not s:
        return jsonify({'error': '套题不存在'}), 404
    qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
    s['questions'] = _get_questions_full(qids)
    return jsonify({'set': s})


@interview_bp.route('/api/interview/sets/<int:set_id>/use', methods=['POST'])
def mark_set_used(set_id):
    s = _fetch_one("SELECT id FROM interview_sets WHERE id=:id", id=set_id)
    if not s:
        return jsonify({'error': '套题不存在'}), 404
    now = _now_str()
    _run("UPDATE interview_sets SET is_used=1, used_at=:t WHERE id=:id", t=now, id=set_id)
    return jsonify({'ok': True, 'used_at': now})


@interview_bp.route('/api/interview/sets/<int:set_id>/release', methods=['POST'])
def release_set(set_id):
    """释放套题：将套题标记为未使用，并重置池中对应题目的 drawn 状态。"""
    s = _fetch_one("SELECT * FROM interview_sets WHERE id=:id", id=set_id)
    if not s:
        return jsonify({'error': '套题不存在'}), 404

    _run("UPDATE interview_sets SET is_used=0, used_at=NULL WHERE id=:id", id=set_id)

    # 重置该套题中题目在所有池中的 drawn 状态
    qids = json.loads(s['question_ids_json']) if s['question_ids_json'] else []
    qids = [q for q in qids if q]  # 去掉 None
    for qid in qids:
        _run(
            "UPDATE interview_pool_questions SET drawn=0, drawn_at=NULL WHERE question_id=:qid",
            qid=qid
        )
    return jsonify({'ok': True})


@interview_bp.route('/api/interview/sets/batch-use', methods=['POST'])
def batch_use_sets():
    data = request.get_json(silent=True) or {}
    set_ids = data.get('set_ids', [])
    if not set_ids:
        return jsonify({'error': '未提供 set_ids'}), 400
    now = _now_str()
    updated = 0
    for sid in set_ids:
        _run("UPDATE interview_sets SET is_used=1, used_at=:t WHERE id=:id", t=now, id=sid)
        updated += 1
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
def export_word():
    """将指定套题导出为 Word 文档（含答案，保留富文本格式）。"""
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
        s = _fetch_one("SELECT * FROM interview_sets WHERE id=:id", id=set_id)
        if not s:
            continue
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
def export_pool_xlsx(pool_id):
    """导出面试题库池到 Excel（含完整题目信息，支持跨机器导入）。"""
    pool = _fetch_one("SELECT * FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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
def export_sets_xlsx(session_id):
    """导出指定场次的套题记录到 Excel（双 Sheet）。"""
    sess = _fetch_one("SELECT * FROM interview_sessions WHERE id=:id", id=session_id)
    if not sess:
        return jsonify({'error': '场次不存在'}), 404

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
def import_pool_xlsx(pool_id):
    """
    从 Excel 导入题目到面试题库池。
    支持跨机器迁移：若 question_id 在本地不存在，自动从 Excel 行数据中新建题目。
    """
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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
    now = _now_str()

    for row in rows[1:]:
        qid = str(_col(row, 'question_id')).strip()
        if not qid:
            continue

        # 检查题目是否存在于本地
        existing_q = QuestionModel.query.filter_by(question_id=qid).first()
        if not existing_q:
            # 跨机器导入：从 Excel 行数据新建题目
            qtype = str(_col(row, 'question_type') or '简答').strip()
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

        # 加入面试池
        try:
            _run(
                "INSERT OR IGNORE INTO interview_pool_questions (pool_id, question_id, added_at) VALUES (:pid, :qid, :t)",
                pid=pool_id, qid=qid, t=now
            )
            added += 1
        except Exception:
            skipped += 1

    db.session.commit()
    return jsonify({'ok': True, 'added': added, 'skipped': skipped, 'created_questions': created})


@interview_bp.route('/api/interview/sessions/import-xlsx', methods=['POST'])
def import_sets_xlsx():
    """
    从 Excel 导入套题记录（Sheet1: 套题列表, Sheet2: 题目详情）。
    自动还原 session 和 sets 记录，若题目不存在则从 Sheet2 新建。
    """
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': '只支持 .xlsx 格式'}), 400

    pool_id = request.form.get('pool_id')
    if not pool_id:
        return jsonify({'error': '缺少 pool_id 参数'}), 400
    pool_id = int(pool_id)
    pool = _fetch_one("SELECT id FROM interview_pools WHERE id=:id", id=pool_id)
    if not pool:
        return jsonify({'error': '题库池不存在'}), 404

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

    # 确保题目存在
    now_dt = datetime.now()
    created_questions = 0
    for qid, qdata in q_detail_map.items():
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
                created_at=now_dt,
                updated_at=now_dt,
            )
            db.session.add(new_q)
            created_questions += 1
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

    # 创建一个导入场次
    now = _now_str()
    from sqlalchemy import text
    with db.engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO interview_sessions
              (pool_id, config_id, session_name, interview_count, sets_multiplier, score_per_slot_json, created_at)
            VALUES (:pid, NULL, :sn, 0, 1, '{}', :t)
        """), {'pid': pool_id, 'sn': f'[导入] {datetime.now().strftime("%Y-%m-%d %H:%M")}', 't': now})
        session_id = result.lastrowid

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

        _run("""
            INSERT INTO interview_sets (session_id, set_code, question_ids_json, is_used, used_at, created_at)
            VALUES (:sid, :sc, :qj, :iu, :ua, :t)
        """, sid=session_id, sc=set_code,
             qj=json.dumps(qids, ensure_ascii=False),
             iu=is_used, ua=used_at, t=now)
        sets_imported += 1

    return jsonify({
        'ok': True,
        'session_id': session_id,
        'sets_imported': sets_imported,
        'created_questions': created_questions,
    })
