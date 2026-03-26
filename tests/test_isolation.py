"""
tests/test_isolation.py — 数据隔离测试（P1 验证）

验证：
- 用户只能看到自己的题目 / 试卷
- 不能编辑/删除他人的题目 / 试卷
- 团队共享可见性正确
- guest_preview 对所有人可见
- admin 可见全部
- 未登录用户全部 401
"""
import pytest
from tests.conftest import login_as, guest_login, make_question, make_exam
from app.db_models import Team, TeamMember


# ──────────────────────────────────────────────────────────────────────────────
# 未登录保护
# ──────────────────────────────────────────────────────────────────────────────

class TestUnauthenticated:
    """所有需要登录的接口，未登录时必须返回 401。"""

    ENDPOINTS = [
        ('GET',    '/api/questions'),
        ('POST',   '/api/questions'),
        ('GET',    '/api/exams'),
        ('POST',   '/api/exams'),
        ('GET',    '/api/teams'),
        ('POST',   '/api/teams'),
        ('GET',    '/api/auth/me'),
        ('GET',    '/api/auth/apikey'),
    ]

    @pytest.mark.parametrize('method,path', ENDPOINTS)
    def test_requires_login(self, client, method, path):
        r = getattr(client, method.lower())(path, json={})
        assert r.status_code == 401, f"{method} {path} 应返回 401，实际 {r.status_code}"


# ──────────────────────────────────────────────────────────────────────────────
# 题目可见性
# ──────────────────────────────────────────────────────────────────────────────

class TestQuestionVisibility:
    def test_user_sees_own_questions(self, client, db, user_a, user_b):
        """user_a 只能看到自己的题目。"""
        make_question(db, 'q_a1', owner_id=user_a.id, visibility='private', content='A的题')
        make_question(db, 'q_b1', owner_id=user_b.id, visibility='private', content='B的题')

        login_as(client, 'user_a', 'pass_a')
        r = client.get('/api/questions')
        assert r.status_code == 200
        ids = [q['question_id'] for q in r.get_json()]
        assert 'q_a1' in ids
        assert 'q_b1' not in ids

    def test_guest_preview_visible_to_all(self, client, db, user_a, user_b, admin_user):
        """visibility=guest_preview 对所有登录用户可见。"""
        make_question(db, 'q_preview', owner_id=admin_user.id,
                      visibility='guest_preview', content='公开示例题')

        for username, password in [('user_a', 'pass_a'), ('user_b', 'pass_b')]:
            with client.session_transaction() as sess:
                sess.clear()
            login_as(client, username, password)
            ids = [q['question_id'] for q in client.get('/api/questions').get_json()]
            assert 'q_preview' in ids, f"{username} 看不到 guest_preview 题目"

    def test_team_visibility(self, client, db, user_a, user_b):
        """visibility=team 的题目：同团队成员可见，其他人不可见。"""
        # 建团队
        team = Team(name='测试团队', created_by=user_a.id)
        db.session.add(team)
        db.session.flush()
        db.session.add(TeamMember(team_id=team.id, user_id=user_a.id, role='admin'))
        db.session.add(TeamMember(team_id=team.id, user_id=user_b.id, role='member'))
        db.session.commit()

        make_question(db, 'q_team', owner_id=user_a.id,
                      visibility='team', team_id=team.id, content='团队共享题')

        # user_b 在团队里，能看到
        login_as(client, 'user_b', 'pass_b')
        ids = [q['question_id'] for q in client.get('/api/questions').get_json()]
        assert 'q_team' in ids

    def test_team_question_invisible_to_outsider(self, client, db, user_a, user_b):
        """不在团队的用户看不到团队题目。"""
        team = Team(name='A的团队', created_by=user_a.id)
        db.session.add(team)
        db.session.flush()
        db.session.add(TeamMember(team_id=team.id, user_id=user_a.id, role='admin'))
        db.session.commit()

        make_question(db, 'q_team2', owner_id=user_a.id,
                      visibility='team', team_id=team.id, content='团队私有题')

        # user_b 不在团队，看不到
        login_as(client, 'user_b', 'pass_b')
        ids = [q['question_id'] for q in client.get('/api/questions').get_json()]
        assert 'q_team2' not in ids

    def test_admin_sees_all(self, client, db, user_a, user_b, admin_user):
        """admin 可以看到所有人的所有题目。"""
        make_question(db, 'q_a_priv', owner_id=user_a.id, visibility='private')
        make_question(db, 'q_b_priv', owner_id=user_b.id, visibility='private')

        login_as(client, 'admin', 'admin123')
        ids = [q['question_id'] for q in client.get('/api/questions').get_json()]
        assert 'q_a_priv' in ids
        assert 'q_b_priv' in ids

    def test_guest_sees_only_preview(self, client, db, admin_user, guest_user, user_a):
        """guest 账号只能看到 guest_preview 题目。"""
        make_question(db, 'q_preview', owner_id=admin_user.id, visibility='guest_preview')
        make_question(db, 'q_private', owner_id=user_a.id, visibility='private')

        guest_login(client)
        ids = [q['question_id'] for q in client.get('/api/questions').get_json()]
        assert 'q_preview' in ids
        assert 'q_private' not in ids


# ──────────────────────────────────────────────────────────────────────────────
# 题目写权限
# ──────────────────────────────────────────────────────────────────────────────

class TestQuestionWritePermission:
    def test_user_can_edit_own_question(self, client, db, user_a):
        make_question(db, 'q_mine', owner_id=user_a.id)
        login_as(client, 'user_a', 'pass_a')
        r = client.put('/api/questions/q_mine', json={'content': '修改后的题目'})
        assert r.status_code == 200

    def test_user_cannot_edit_others_question(self, client, db, user_a, user_b):
        make_question(db, 'q_b', owner_id=user_b.id)
        login_as(client, 'user_a', 'pass_a')
        r = client.put('/api/questions/q_b', json={'content': '试图修改'})
        assert r.status_code == 403

    def test_user_cannot_delete_others_question(self, client, db, user_a, user_b):
        make_question(db, 'q_b2', owner_id=user_b.id)
        login_as(client, 'user_a', 'pass_a')
        r = client.delete('/api/questions/q_b2')
        assert r.status_code == 403

    def test_admin_can_edit_any_question(self, client, db, user_a, admin_user):
        make_question(db, 'q_user', owner_id=user_a.id)
        login_as(client, 'admin', 'admin123')
        r = client.put('/api/questions/q_user', json={'content': 'admin 修改'})
        assert r.status_code == 200

    def test_guest_cannot_create_question(self, client, db, guest_user):
        guest_login(client)
        r = client.post('/api/questions', json={
            'question_type': '单选',
            'content': '游客试图创建',
            'options': ['A', 'B', 'C', 'D'],
            'answer': 'A',
        })
        assert r.status_code == 403

    def test_created_question_has_owner(self, client, db, user_a):
        """创建的题目自动挂上 owner_id。"""
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/questions', json={
            'question_type': '单选',
            'content': '新建测试题',
            'options': ['A', 'B', 'C', 'D'],
            'answer': 'A',
        })
        assert r.status_code == 201
        from app.db_models import QuestionModel
        q = QuestionModel.query.filter_by(content='新建测试题').first()
        assert q is not None
        assert q.owner_id == user_a.id
        assert q.visibility == 'private'

    def test_batch_delete_only_own(self, client, db, user_a, user_b):
        """batch-delete 只能删自己的题目，他人的题目被忽略。"""
        make_question(db, 'q_own', owner_id=user_a.id)
        make_question(db, 'q_other', owner_id=user_b.id)

        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/questions/batch-delete',
                        json={'question_ids': ['q_own', 'q_other']})
        assert r.status_code == 200
        d = r.get_json()
        assert d['deleted_count'] == 1   # 只删了自己的

        from app.db_models import QuestionModel
        assert QuestionModel.query.get('q_other') is not None


# ──────────────────────────────────────────────────────────────────────────────
# 试卷可见性与写权限
# ──────────────────────────────────────────────────────────────────────────────

class TestExamIsolation:
    def test_user_sees_own_exam(self, client, db, user_a, user_b):
        make_exam(db, 'e_a', owner_id=user_a.id)
        make_exam(db, 'e_b', owner_id=user_b.id)

        login_as(client, 'user_a', 'pass_a')
        ids = [e['exam_id'] for e in client.get('/api/exams').get_json()]
        assert 'e_a' in ids
        assert 'e_b' not in ids

    def test_user_cannot_delete_others_exam(self, client, db, user_a, user_b):
        make_exam(db, 'e_b2', owner_id=user_b.id)
        login_as(client, 'user_a', 'pass_a')
        r = client.delete('/api/exams/e_b2')
        assert r.status_code == 403

    def test_created_exam_has_owner(self, client, db, user_a):
        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/exams', json={'name': '我的试卷', 'config': {}})
        assert r.status_code == 201
        from app.db_models import ExamModel
        e = ExamModel.query.filter_by(name='我的试卷').first()
        assert e.owner_id == user_a.id


# ──────────────────────────────────────────────────────────────────────────────
# 组卷隔离（generate_exam 只从可见题中抽取）
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateExamIsolation:
    def test_generate_only_uses_visible_questions(self, client, db, user_a, user_b):
        """组卷时只抽取当前用户可见的题目。"""
        # user_a 有 5 道题
        for i in range(5):
            make_question(db, f'qa_{i}', owner_id=user_a.id, question_type='单选')
        # user_b 有 5 道题（user_a 不可见）
        for i in range(5):
            make_question(db, f'qb_{i}', owner_id=user_b.id, question_type='单选')

        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/exams/generate', json={
            'name': '隔离测试卷',
            'config': {'单选': {'count': 3, 'points': 5}},
        })
        assert r.status_code == 200
        exam = r.get_json()
        q_ids = [q['question_id'] for q in exam['questions']]
        # 所有抽到的题都是 user_a 的
        assert all(qid.startswith('qa_') for qid in q_ids)
        assert len(q_ids) == 3

    def test_generate_reports_shortage(self, client, db, user_a):
        """题目不足时 shortages 字段有内容。"""
        # 只有 2 道题，但要求 5 道
        for i in range(2):
            make_question(db, f'short_{i}', owner_id=user_a.id, question_type='单选')

        login_as(client, 'user_a', 'pass_a')
        r = client.post('/api/exams/generate', json={
            'name': '缺题测试卷',
            'config': {'单选': {'count': 5, 'points': 5}},
        })
        assert r.status_code == 200
        d = r.get_json()
        assert len(d['shortages']) == 1
        shortage = d['shortages'][0]
        assert shortage['requested'] == 5
        assert shortage['available'] == 2
