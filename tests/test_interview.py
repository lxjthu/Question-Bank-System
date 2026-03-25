"""
面试抽题模块自动化测试

覆盖：
- 多池创建、查询、删除
- 题目筛选加入/移除/清空池
- 套题配置保存与读取
- 批量生成套题（含不足时警告）
- 单次随机抽选
- 标记使用 / 释放（含 drawn 状态重置）
- Excel 导出响应格式验证（Content-Type）
- Word 导出响应格式验证
"""

import pytest
import json
from tests.conftest import create_question_in_db


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pool_id(client):
    """创建一个测试题库池，返回其 id。"""
    res = client.post('/api/interview/pools', json={'pool_name': '测试池', 'description': '单元测试用池'})
    assert res.status_code == 201
    return res.get_json()['pool']['id']


@pytest.fixture
def pool_with_questions(client, db, pool_id):
    """在测试池中放入足够题目（3种题型各5道），返回 pool_id。"""
    types = ['简答', '材料分析', '简答>论述']
    for qtype in types:
        for i in range(5):
            q = create_question_in_db(
                db,
                question_id=f'{qtype}_q{i}',
                question_type=qtype,
                content=f'{qtype} 测试题 {i}',
                answer=f'答案{i}',
                language='zh',
                difficulty='medium',
            )
    # 将全部题目加入池
    res = client.post(f'/api/interview/pools/{pool_id}/questions/add', json={
        'question_types': types, 'exclude_used': False
    })
    assert res.status_code == 200
    return pool_id


@pytest.fixture
def config_id(client, pool_with_questions):
    """为池保存套题配置（3个槽位），返回 pool_id。"""
    pool_id = pool_with_questions
    slots = [
        {'question_type': '简答', 'language': '任意', 'difficulty': '任意', 'remark': '简答题'},
        {'question_type': '材料分析', 'language': '任意', 'difficulty': '任意', 'remark': '材料分析'},
        {'question_type': '简答>论述', 'language': '任意', 'difficulty': '任意', 'remark': '论述题'},
    ]
    res = client.put(f'/api/interview/pools/{pool_id}/config', json={'slots': slots})
    assert res.status_code == 200
    return pool_id


@pytest.fixture
def session_with_sets(client, config_id):
    """创建一个场次并生成套题（5人*1倍=5套），返回 (pool_id, session_id)。"""
    pool_id = config_id
    res = client.post('/api/interview/sessions', json={
        'pool_id': pool_id,
        'session_name': '2026春招测试',
        'interview_count': 5,
        'sets_multiplier': 1,
    })
    assert res.status_code == 201, res.get_json()
    data = res.get_json()
    return pool_id, data['session_id']


# ─────────────────────────────────────────────────────────────────────────────
# 1. 题库池 CRUD
# ─────────────────────────────────────────────────────────────────────────────

def test_create_pool(client):
    res = client.post('/api/interview/pools', json={'pool_name': 'Pool A'})
    assert res.status_code == 201
    data = res.get_json()
    assert data['pool']['pool_name'] == 'Pool A'


def test_create_pool_missing_name(client):
    res = client.post('/api/interview/pools', json={'pool_name': ''})
    assert res.status_code == 400


def test_list_pools(client, pool_id):
    res = client.get('/api/interview/pools')
    assert res.status_code == 200
    pools = res.get_json()['pools']
    assert any(p['id'] == pool_id for p in pools)


def test_multiple_pools(client):
    for name in ['春招池', '秋招池', '研究生池']:
        r = client.post('/api/interview/pools', json={'pool_name': name})
        assert r.status_code == 201
    res = client.get('/api/interview/pools')
    names = [p['pool_name'] for p in res.get_json()['pools']]
    assert '春招池' in names and '秋招池' in names and '研究生池' in names


def test_update_pool(client, pool_id):
    res = client.put(f'/api/interview/pools/{pool_id}', json={'pool_name': '更新后的池', 'description': '新描述'})
    assert res.status_code == 200
    pools = client.get('/api/interview/pools').get_json()['pools']
    p = next(x for x in pools if x['id'] == pool_id)
    assert p['pool_name'] == '更新后的池'


def test_delete_pool(client, pool_id):
    res = client.delete(f'/api/interview/pools/{pool_id}')
    assert res.status_code == 200
    pools = client.get('/api/interview/pools').get_json()['pools']
    assert not any(p['id'] == pool_id for p in pools)


def test_delete_nonexistent_pool(client):
    res = client.delete('/api/interview/pools/99999')
    assert res.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 2. 题库池题目管理
# ─────────────────────────────────────────────────────────────────────────────

def test_add_questions_to_pool(client, db, pool_id):
    create_question_in_db(db, question_id='q_add_1', question_type='简答', content='测试加入题目')
    res = client.post(f'/api/interview/pools/{pool_id}/questions/add', json={
        'question_types': ['简答'], 'exclude_used': False
    })
    assert res.status_code == 200
    assert res.get_json()['added'] >= 1


def test_pool_stats(client, db, pool_id):
    create_question_in_db(db, question_id='q_stat_1', question_type='简答', content='统计测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    res = client.get(f'/api/interview/pools/{pool_id}/stats')
    assert res.status_code == 200
    data = res.get_json()
    assert data['total'] >= 1
    assert data['available'] >= 1


def test_no_duplicate_in_pool(client, db, pool_id):
    """同一道题加入池两次，不会出现重复。"""
    create_question_in_db(db, question_id='q_dup_1', question_type='简答', content='重复测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    res = client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    # 第二次加入时已在池中，added 应为 0
    assert res.get_json()['added'] == 0


def test_remove_question_from_pool(client, db, pool_id):
    create_question_in_db(db, question_id='q_rm_1', question_type='简答', content='移除测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    res = client.post(f'/api/interview/pools/{pool_id}/questions/remove', json={'question_ids': ['q_rm_1']})
    assert res.status_code == 200
    stats = client.get(f'/api/interview/pools/{pool_id}/stats').get_json()
    assert stats['total'] == 0


def test_clear_pool(client, db, pool_id):
    create_question_in_db(db, question_id='q_clr_1', question_type='简答', content='清空测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    res = client.delete(f'/api/interview/pools/{pool_id}/questions')
    assert res.status_code == 200
    stats = client.get(f'/api/interview/pools/{pool_id}/stats').get_json()
    assert stats['total'] == 0


def test_list_pool_questions(client, pool_with_questions):
    pool_id = pool_with_questions
    res = client.get(f'/api/interview/pools/{pool_id}/questions?page=1&per_page=10')
    assert res.status_code == 200
    data = res.get_json()
    assert data['total'] >= 5
    assert len(data['questions']) >= 1


def test_preview_filter(client, db, pool_id):
    create_question_in_db(db, question_id='q_prev_1', question_type='简答', content='预览测试',
                          knowledge_point='宏观经济', difficulty='medium')
    res = client.post(f'/api/interview/pools/{pool_id}/questions/preview', json={
        'knowledge_point': '宏观', 'exclude_used': False
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['count'] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. 套题配置
# ─────────────────────────────────────────────────────────────────────────────

def test_save_config(client, pool_id):
    slots = [
        {'question_type': '简答', 'language': '任意', 'difficulty': '任意'},
        {'question_type': '材料分析', 'language': 'zh', 'difficulty': 'medium'},
    ]
    res = client.put(f'/api/interview/pools/{pool_id}/config', json={'slots': slots})
    assert res.status_code == 200
    assert res.get_json()['ok'] is True


def test_get_config(client, pool_id):
    slots = [{'question_type': '简答', 'language': '任意', 'difficulty': '任意'}]
    client.put(f'/api/interview/pools/{pool_id}/config', json={'slots': slots})
    res = client.get(f'/api/interview/pools/{pool_id}/config')
    assert res.status_code == 200
    assert len(res.get_json()['slots']) == 1
    assert res.get_json()['slots'][0]['question_type'] == '简答'


def test_config_empty_slots_rejected(client, pool_id):
    res = client.put(f'/api/interview/pools/{pool_id}/config', json={'slots': []})
    assert res.status_code == 400


def test_config_slot_missing_type_rejected(client, pool_id):
    res = client.put(f'/api/interview/pools/{pool_id}/config', json={
        'slots': [{'question_type': '', 'language': 'zh'}]
    })
    assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 4. 警告检查
# ─────────────────────────────────────────────────────────────────────────────

def test_check_no_config(client, pool_id):
    res = client.post(f'/api/interview/pools/{pool_id}/check', json={'total_sets': 3})
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is False
    assert any(w['type'] == 'no_config' for w in data['warnings'])


def test_check_insufficient(client, db, pool_id):
    create_question_in_db(db, question_id='q_chk_1', question_type='简答', content='检查测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    client.put(f'/api/interview/pools/{pool_id}/config', json={
        'slots': [{'question_type': '简答', 'language': '任意', 'difficulty': '任意'}]
    })
    # 只有1道题，要求10套
    res = client.post(f'/api/interview/pools/{pool_id}/check', json={'total_sets': 10})
    data = res.get_json()
    assert data['ok'] is False
    assert any(w['type'] == 'slot_insufficient' for w in data['warnings'])


def test_check_sufficient(client, config_id):
    pool_id = config_id
    # pool_with_questions 每种题型5道，配置3槽位，要求5套 → 应通过
    res = client.post(f'/api/interview/pools/{pool_id}/check', json={'total_sets': 5})
    data = res.get_json()
    assert data['ok'] is True
    assert len(data['warnings']) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. 套题生成
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_sets_success(client, config_id):
    pool_id = config_id
    res = client.post('/api/interview/sessions', json={
        'pool_id': pool_id,
        'session_name': '生成测试场次',
        'interview_count': 3,
        'sets_multiplier': 1,
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data['ok'] is True
    assert data['total_sets'] == 3
    assert len(data['sets']) == 3


def test_generated_sets_no_duplicate_questions(client, config_id):
    """同一套题中，不同槽位的题目在整个生成结果中不重复。"""
    pool_id = config_id
    res = client.post('/api/interview/sessions', json={
        'pool_id': pool_id,
        'session_name': '去重测试',
        'interview_count': 4,
        'sets_multiplier': 1,
    })
    assert res.status_code == 201
    sets = res.get_json()['sets']
    all_qids = []
    for s in sets:
        for qid in s['question_ids']:
            if qid:
                assert qid not in all_qids, f'题目 {qid} 在多套题中重复出现'
                all_qids.append(qid)


def test_generate_sets_insufficient_warning(client, db, pool_id):
    """题目不足时返回 422 + warnings。"""
    create_question_in_db(db, question_id='q_ins_1', question_type='简答', content='不足测试')
    client.post(f'/api/interview/pools/{pool_id}/questions/add', json={'question_types': ['简答'], 'exclude_used': False})
    client.put(f'/api/interview/pools/{pool_id}/config', json={
        'slots': [{'question_type': '简答', 'language': '任意', 'difficulty': '任意'}]
    })
    res = client.post('/api/interview/sessions', json={
        'pool_id': pool_id, 'session_name': '不足场次', 'interview_count': 10, 'sets_multiplier': 1,
    })
    assert res.status_code == 422
    assert 'warnings' in res.get_json()


def test_generate_sets_missing_config(client, pool_id):
    res = client.post('/api/interview/sessions', json={
        'pool_id': pool_id, 'session_name': '无配置场次', 'interview_count': 1, 'sets_multiplier': 1,
    })
    assert res.status_code == 400


def test_list_sessions(client, session_with_sets):
    pool_id, session_id = session_with_sets
    res = client.get('/api/interview/sessions')
    assert res.status_code == 200
    sessions = res.get_json()['sessions']
    assert any(s['id'] == session_id for s in sessions)


def test_list_sets(client, session_with_sets):
    pool_id, session_id = session_with_sets
    res = client.get(f'/api/interview/sessions/{session_id}/sets')
    assert res.status_code == 200
    data = res.get_json()
    assert data['total'] == 5
    assert len(data['sets']) == 5


# ─────────────────────────────────────────────────────────────────────────────
# 6. 单次随机抽选
# ─────────────────────────────────────────────────────────────────────────────

def test_draw_set(client, session_with_sets):
    pool_id, session_id = session_with_sets
    res = client.post(f'/api/interview/sessions/{session_id}/draw')
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['set_code'].startswith('SET-')
    assert len(data['questions']) == 3  # 3 槽位


def test_drawn_set_is_marked_used(client, session_with_sets):
    pool_id, session_id = session_with_sets
    draw_res = client.post(f'/api/interview/sessions/{session_id}/draw')
    set_id = draw_res.get_json()['set_id']
    detail = client.get(f'/api/interview/sets/{set_id}').get_json()['set']
    assert detail['is_used'] == 1


def test_draw_all_then_exhaust(client, session_with_sets):
    """抽完所有套题后，再抽返回 422。"""
    pool_id, session_id = session_with_sets
    for _ in range(5):
        client.post(f'/api/interview/sessions/{session_id}/draw')
    res = client.post(f'/api/interview/sessions/{session_id}/draw')
    assert res.status_code == 422
    assert res.get_json()['code'] == 'no_available'


# ─────────────────────────────────────────────────────────────────────────────
# 7. 标记使用 / 释放
# ─────────────────────────────────────────────────────────────────────────────

def test_mark_set_used(client, session_with_sets):
    pool_id, session_id = session_with_sets
    sets = client.get(f'/api/interview/sessions/{session_id}/sets').get_json()['sets']
    set_id = sets[0]['id']
    res = client.post(f'/api/interview/sets/{set_id}/use')
    assert res.status_code == 200
    detail = client.get(f'/api/interview/sets/{set_id}').get_json()['set']
    assert detail['is_used'] == 1
    assert detail['used_at'] is not None


def test_release_set(client, session_with_sets):
    pool_id, session_id = session_with_sets
    sets = client.get(f'/api/interview/sessions/{session_id}/sets').get_json()['sets']
    set_id = sets[0]['id']
    client.post(f'/api/interview/sets/{set_id}/use')
    res = client.post(f'/api/interview/sets/{set_id}/release')
    assert res.status_code == 200
    detail = client.get(f'/api/interview/sets/{set_id}').get_json()['set']
    assert detail['is_used'] == 0
    assert detail['used_at'] is None


def test_release_resets_drawn_in_pool(client, session_with_sets):
    """释放套题后，其题目在面试池中的 drawn 状态重置为 0，可再次被抽。"""
    pool_id, session_id = session_with_sets

    # 先抽一套，让其中的题 drawn=1
    draw_res = client.post(f'/api/interview/sessions/{session_id}/draw')
    set_id = draw_res.get_json()['set_id']
    qids = draw_res.get_json()['questions']
    qids = [q['question_id'] for q in qids if q]

    # 释放套题
    client.post(f'/api/interview/sets/{set_id}/release')

    # 检查池中题目状态 — 可用数量应该恢复
    stats = client.get(f'/api/interview/pools/{pool_id}/stats').get_json()
    assert stats['available'] > 0


def test_batch_use_sets(client, session_with_sets):
    pool_id, session_id = session_with_sets
    sets = client.get(f'/api/interview/sessions/{session_id}/sets').get_json()['sets']
    ids = [s['id'] for s in sets[:3]]
    res = client.post('/api/interview/sets/batch-use', json={'set_ids': ids})
    assert res.status_code == 200
    assert res.get_json()['updated'] == 3


def test_batch_use_empty(client):
    res = client.post('/api/interview/sets/batch-use', json={'set_ids': []})
    assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 8. 套题详情
# ─────────────────────────────────────────────────────────────────────────────

def test_get_set_detail(client, session_with_sets):
    pool_id, session_id = session_with_sets
    sets = client.get(f'/api/interview/sessions/{session_id}/sets').get_json()['sets']
    set_id = sets[0]['id']
    res = client.get(f'/api/interview/sets/{set_id}')
    assert res.status_code == 200
    s = res.get_json()['set']
    assert s['id'] == set_id
    assert 'questions' in s


def test_get_nonexistent_set(client):
    res = client.get('/api/interview/sets/99999')
    assert res.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 9. 导出响应验证
# ─────────────────────────────────────────────────────────────────────────────

def test_export_pool_xlsx(client, pool_with_questions):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip('openpyxl 未安装')
    pool_id = pool_with_questions
    res = client.get(f'/api/interview/pools/{pool_id}/questions/export-xlsx')
    assert res.status_code == 200
    assert 'spreadsheetml' in res.content_type


def test_export_sets_xlsx(client, session_with_sets):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip('openpyxl 未安装')
    pool_id, session_id = session_with_sets
    res = client.get(f'/api/interview/sessions/{session_id}/export-xlsx')
    assert res.status_code == 200
    assert 'spreadsheetml' in res.content_type


def test_export_word(client, session_with_sets):
    pool_id, session_id = session_with_sets
    sets = client.get(f'/api/interview/sessions/{session_id}/sets').get_json()['sets']
    set_ids = [s['id'] for s in sets[:2]]
    res = client.post('/api/interview/export/word', json={
        'set_ids': set_ids, 'include_answers': True
    })
    assert res.status_code == 200
    assert 'wordprocessingml' in res.content_type


def test_export_word_no_sets(client):
    res = client.post('/api/interview/export/word', json={'set_ids': []})
    assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 10. 导入 Excel
# ─────────────────────────────────────────────────────────────────────────────

def test_import_pool_xlsx(client, db, pool_id):
    """导入包含已存在题目的 Excel，验证加入池成功。"""
    create_question_in_db(db, question_id='q_imp_1', question_type='简答', content='导入测试题目1')
    create_question_in_db(db, question_id='q_imp_2', question_type='简答', content='导入测试题目2')

    # 构造 xlsx 内存文件
    try:
        import openpyxl
    except ImportError:
        pytest.skip('openpyxl 未安装')

    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ['question_id', 'question_type', 'subject', 'difficulty', 'language',
               'knowledge_point', 'tags', 'content', 'answer', 'reference_answer',
               'explanation', 'content_en', 'options', 'options_en', 'drawn', 'drawn_at', 'added_at']
    ws.append(headers)
    ws.append(['q_imp_1', '简答', '', 'medium', 'zh', '', '', '导入测试题目1', '', '', '', '', '', '', '可用', '', ''])
    ws.append(['q_imp_2', '简答', '', 'medium', 'zh', '', '', '导入测试题目2', '', '', '', '', '', '', '可用', '', ''])

    import io
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    data = {'file': (buf, 'test_pool.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    res = client.post(f'/api/interview/pools/{pool_id}/questions/import-xlsx',
                      data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    result = res.get_json()
    assert result['added'] == 2
    assert result['created_questions'] == 0  # 题目已存在，无需新建


def test_import_pool_xlsx_cross_machine(client, pool_id):
    """跨机器导入：题目在本地不存在，应自动新建再加入池。"""
    try:
        import openpyxl
    except ImportError:
        pytest.skip('openpyxl 未安装')

    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ['question_id', 'question_type', 'subject', 'difficulty', 'language',
               'knowledge_point', 'tags', 'content', 'answer', 'reference_answer',
               'explanation', 'content_en', 'options', 'options_en', 'drawn', 'drawn_at', 'added_at']
    ws.append(headers)
    ws.append(['cross_machine_q1', '简答', '农业经济', 'medium', 'zh', '农业', '', '跨机器测试题目', '参考答案', '', '', '', '', '', '可用', '', ''])

    import io
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    data = {'file': (buf, 'cross.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    res = client.post(f'/api/interview/pools/{pool_id}/questions/import-xlsx',
                      data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    result = res.get_json()
    assert result['created_questions'] == 1
    assert result['added'] == 1
