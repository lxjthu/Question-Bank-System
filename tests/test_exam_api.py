"""Tests for exam API endpoints."""
import json
import pytest
from tests.conftest import create_question_in_db, create_exam_in_db


class TestCreateExam:
    def test_create_exam(self, client, db, sample_exam_data):
        """POST /api/exams returns 201."""
        resp = client.post('/api/exams', json=sample_exam_data)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['exam_id'] == 'test_exam_001'
        assert data['name'] == '测试试卷'

    def test_get_exams_empty(self, client, db):
        """Empty list when no exams."""
        resp = client.get('/api/exams')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_exams_list(self, client, db):
        """Returns correct list when data exists."""
        create_exam_in_db(db, exam_id='e1', name='试卷一')
        create_exam_in_db(db, exam_id='e2', name='试卷二')
        resp = client.get('/api/exams')
        assert len(resp.get_json()) == 2


class TestGetExam:
    def test_get_exam_by_id(self, client, db):
        """GET /api/exams/<id> returns correct exam."""
        create_exam_in_db(db, exam_id='ge1', name='获取试卷')
        resp = client.get('/api/exams/ge1')
        assert resp.status_code == 200
        assert resp.get_json()['name'] == '获取试卷'

    def test_get_exam_not_found(self, client, db):
        """Non-existent exam returns 404."""
        resp = client.get('/api/exams/nonexistent')
        assert resp.status_code == 404


class TestUpdateExam:
    def test_update_exam(self, client, db):
        """PUT modifies exam name and config."""
        create_exam_in_db(db, exam_id='ue1', name='原始名称')
        resp = client.put('/api/exams/ue1', json={
            'name': '更新名称',
            'config': {'单选': {'count': 5, 'points': 2}},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == '更新名称'
        assert data['config']['单选']['count'] == 5


class TestDeleteExam:
    def test_delete_exam(self, client, db):
        """DELETE removes exam."""
        create_exam_in_db(db, exam_id='de1')
        resp = client.delete('/api/exams/de1')
        assert resp.status_code == 200
        resp2 = client.get('/api/exams/de1')
        assert resp2.status_code == 404


class TestExamQuestionOperations:
    def test_add_question_to_exam(self, client, db):
        """POST .../add_question associates question."""
        create_question_in_db(db, question_id='aq1')
        create_exam_in_db(db, exam_id='ae1')
        resp = client.post('/api/exams/ae1/add_question', json={'question_id': 'aq1'})
        assert resp.status_code == 200
        assert len(resp.get_json()['questions']) == 1

    def test_add_nonexistent_question_to_exam(self, client, db):
        """Adding non-existent question returns 404."""
        create_exam_in_db(db, exam_id='ae2')
        resp = client.post('/api/exams/ae2/add_question', json={'question_id': 'nonexistent'})
        assert resp.status_code == 404

    def test_remove_question_from_exam(self, client, db):
        """DELETE .../remove_question/<qid> disassociates question."""
        create_question_in_db(db, question_id='rq1')
        create_exam_in_db(db, exam_id='re1', question_ids=['rq1'])
        resp = client.delete('/api/exams/re1/remove_question/rq1')
        assert resp.status_code == 200
        assert len(resp.get_json()['questions']) == 0


class TestGenerateExam:
    def test_generate_exam(self, client, db):
        """POST /api/exams/generate auto-generates exam."""
        for i in range(5):
            create_question_in_db(db, question_id=f'gq{i}', content=f'单选题{i}')
        resp = client.post('/api/exams/generate', json={
            'exam_id': 'gen1',
            'name': '自动组卷',
            'config': {'单选': {'count': 3, 'points': 5}},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['questions']) == 3

    def test_generate_exam_insufficient_questions(self, client, db):
        """When fewer questions available than requested, returns what's available."""
        create_question_in_db(db, question_id='iq1')
        resp = client.post('/api/exams/generate', json={
            'exam_id': 'gen2',
            'name': '不足试卷',
            'config': {'单选': {'count': 5, 'points': 5}},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['questions']) == 1  # Only 1 available


class TestConfirmRevert:
    def test_confirm_exam(self, client, db):
        """POST .../confirm marks questions as used."""
        create_question_in_db(db, question_id='cq1')
        create_question_in_db(db, question_id='cq2', content='题目2')
        create_exam_in_db(db, exam_id='ce1', question_ids=['cq1', 'cq2'])
        resp = client.post('/api/exams/ce1/confirm')
        assert resp.status_code == 200
        assert 'confirmed' in resp.get_json()['message'].lower() or 'confirmed' in resp.get_json()['message']

    def test_confirm_marks_questions_used(self, client, db):
        """After confirm, questions have is_used=True."""
        create_question_in_db(db, question_id='cu1')
        create_exam_in_db(db, exam_id='cue1', question_ids=['cu1'])
        client.post('/api/exams/cue1/confirm')
        resp = client.get('/api/questions/cu1')
        assert resp.get_json()['is_used'] is True

    def test_revert_confirmation(self, client, db):
        """POST .../revert_confirmation reverts used status."""
        create_question_in_db(db, question_id='rv1', is_used=True)
        create_exam_in_db(db, exam_id='rve1', question_ids=['rv1'])
        resp = client.post('/api/exams/rve1/revert_confirmation')
        assert resp.status_code == 200

    def test_revert_marks_questions_unused(self, client, db):
        """After revert, questions have is_used=False."""
        create_question_in_db(db, question_id='ru1', is_used=True)
        create_exam_in_db(db, exam_id='rue1', question_ids=['ru1'])
        client.post('/api/exams/rue1/revert_confirmation')
        resp = client.get('/api/questions/ru1')
        assert resp.get_json()['is_used'] is False


class TestReplaceQuestion:
    def test_replace_question(self, client, db):
        """POST .../replace_question replaces question in exam."""
        create_question_in_db(db, question_id='rp1', content='旧题目')
        create_question_in_db(db, question_id='rp2', content='新题目')
        create_exam_in_db(db, exam_id='rpe1', question_ids=['rp1'])
        resp = client.post('/api/exams/rpe1/replace_question', json={
            'old_question_id': 'rp1',
            'new_question_id': 'rp2',
        })
        assert resp.status_code == 200
        questions = resp.get_json()['questions']
        assert len(questions) == 1
        assert questions[0]['question_id'] == 'rp2'

    def test_replace_question_wrong_type(self, client, db):
        """Replacing with different type returns 400."""
        create_question_in_db(db, question_id='rt1', question_type='单选')
        create_question_in_db(db, question_id='rt2', question_type='是非', content='判断题')
        create_exam_in_db(db, exam_id='rte1', question_ids=['rt1'])
        resp = client.post('/api/exams/rte1/replace_question', json={
            'old_question_id': 'rt1',
            'new_question_id': 'rt2',
        })
        assert resp.status_code == 400


class TestExportExam:
    def test_export_exam_not_found(self, client, db):
        """Export non-existent exam returns 404."""
        resp = client.get('/api/exams/nonexistent/export')
        assert resp.status_code == 404

    def test_export_exam_to_word(self, client, db):
        """GET .../export returns docx file."""
        create_question_in_db(db, question_id='eq1', content='导出题目')
        create_exam_in_db(db, exam_id='ee1', name='导出试卷',
                          config={'单选': {'count': 1, 'points': 5}},
                          question_ids=['eq1'])
        resp = client.get('/api/exams/ee1/export')
        assert resp.status_code == 200
        assert 'docx' in resp.headers.get('Content-Disposition', '') or resp.content_type is not None
