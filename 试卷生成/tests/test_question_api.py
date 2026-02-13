"""Tests for question bank API endpoints."""
import json
import io
import pytest
from tests.conftest import create_question_in_db


class TestAddQuestion:
    def test_add_question(self, client, db, sample_question_data):
        """POST /api/questions returns 201 with correct data."""
        resp = client.post('/api/questions', json=sample_question_data)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['question_id'] == 'test_q_001'
        assert data['question_type'] == '单选'
        assert data['content'] == '以下哪个是Python的关键字？'
        assert data['options'] == ['class', 'define', 'include', 'var']
        assert data['answer'] == 'A'

    def test_add_question_single_choice(self, client, db):
        """Test adding single choice question."""
        resp = client.post('/api/questions', json={
            'question_id': 'sc1', 'question_type': '单选',
            'content': '单选题内容', 'options': ['A', 'B', 'C', 'D'], 'answer': 'A',
        })
        assert resp.status_code == 201
        assert resp.get_json()['question_type'] == '单选'

    def test_add_question_true_false(self, client, db):
        """Test adding true/false question."""
        resp = client.post('/api/questions', json={
            'question_id': 'tf1', 'question_type': '是非',
            'content': '判断题内容', 'options': ['是', '否'], 'answer': 'A',
        })
        assert resp.status_code == 201
        assert resp.get_json()['question_type'] == '是非'

    def test_add_question_essay(self, client, db):
        """Test adding essay question."""
        resp = client.post('/api/questions', json={
            'question_id': 'es1', 'question_type': '论述',
            'content': '论述题内容', 'reference_answer': '参考答案内容',
        })
        assert resp.status_code == 201
        assert resp.get_json()['question_type'] == '论述'

    def test_add_question_calculation(self, client, db):
        """Test adding calculation question."""
        resp = client.post('/api/questions', json={
            'question_id': 'ca1', 'question_type': '计算',
            'content': '计算题内容', 'answer': '42',
        })
        assert resp.status_code == 201
        assert resp.get_json()['question_type'] == '计算'

    def test_add_question_material(self, client, db):
        """Test adding material-based question."""
        resp = client.post('/api/questions', json={
            'question_id': 'ma1', 'question_type': '材料',
            'content': '材料题内容', 'reference_answer': '参考答案',
        })
        assert resp.status_code == 201
        assert resp.get_json()['question_type'] == '材料'


class TestGetQuestions:
    def test_get_questions_empty(self, client, db):
        """Empty database returns empty list."""
        resp = client.get('/api/questions')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_questions_list(self, client, db):
        """Returns correct list when data exists."""
        create_question_in_db(db, question_id='q1', content='题目一')
        create_question_in_db(db, question_id='q2', content='题目二')
        resp = client.get('/api/questions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_get_question_by_id(self, client, db):
        """GET /api/questions/<id> returns correct question."""
        create_question_in_db(db, question_id='qx1', content='特定题目')
        resp = client.get('/api/questions/qx1')
        assert resp.status_code == 200
        assert resp.get_json()['content'] == '特定题目'

    def test_get_question_not_found(self, client, db):
        """Non-existent id returns 404."""
        resp = client.get('/api/questions/nonexistent')
        assert resp.status_code == 404


class TestUpdateQuestion:
    def test_update_question(self, client, db):
        """PUT modifies question content."""
        create_question_in_db(db, question_id='uq1', content='原始内容')
        resp = client.put('/api/questions/uq1', json={'content': '更新后内容'})
        assert resp.status_code == 200
        assert resp.get_json()['content'] == '更新后内容'

    def test_update_question_not_found(self, client, db):
        """PUT on non-existent id returns 404."""
        resp = client.put('/api/questions/nonexistent', json={'content': '内容'})
        assert resp.status_code == 404


class TestDeleteQuestion:
    def test_delete_question(self, client, db):
        """DELETE removes question, subsequent GET returns 404."""
        create_question_in_db(db, question_id='dq1')
        resp = client.delete('/api/questions/dq1')
        assert resp.status_code == 200
        resp2 = client.get('/api/questions/dq1')
        assert resp2.status_code == 404

    def test_delete_question_not_found(self, client, db):
        """DELETE non-existent id returns 404."""
        resp = client.delete('/api/questions/nonexistent')
        assert resp.status_code == 404


class TestSearchQuestions:
    def test_search_by_keyword(self, client, db):
        """keyword search filters correctly."""
        create_question_in_db(db, question_id='sk1', content='Python是编程语言')
        create_question_in_db(db, question_id='sk2', content='Java是编程语言')
        resp = client.get('/api/questions?keyword=Python')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'sk1'

    def test_search_by_type(self, client, db):
        """type filter works correctly."""
        create_question_in_db(db, question_id='st1', question_type='单选')
        create_question_in_db(db, question_id='st2', question_type='是非', content='判断题')
        resp = client.get('/api/questions?type=是非')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'st2'

    def test_search_by_language(self, client, db):
        """language filter works correctly."""
        create_question_in_db(db, question_id='sl1', language='zh')
        create_question_in_db(db, question_id='sl2', language='en', content='English question')
        resp = client.get('/api/questions?language=en')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'sl2'

    def test_search_combined(self, client, db):
        """Combined search filters work."""
        create_question_in_db(db, question_id='sc1', question_type='单选', language='zh', content='Python基础')
        create_question_in_db(db, question_id='sc2', question_type='单选', language='en', content='Python basics')
        create_question_in_db(db, question_id='sc3', question_type='是非', language='zh', content='Python判断')
        resp = client.get('/api/questions?type=单选&language=zh&keyword=Python')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'sc1'

    def test_search_no_results(self, client, db):
        """Search with no matches returns empty list."""
        create_question_in_db(db, question_id='sn1', content='数学题目')
        resp = client.get('/api/questions?keyword=不存在的关键词')
        assert resp.get_json() == []


class TestImportExport:
    def test_import_txt_file(self, client, db):
        """POST /api/questions/import imports TXT file."""
        txt_content = """[单选][A]
测试题目内容
[A]选项A
[B]选项B
[C]选项C
[D]选项D
"""
        data = {
            'file': (io.BytesIO(txt_content.encode('utf-8')), 'test.txt'),
        }
        resp = client.post('/api/questions/import', data=data, content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert result['count'] >= 1

    def test_import_no_file(self, client, db):
        """No file upload returns 400."""
        resp = client.post('/api/questions/import', data={}, content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_export_invalid_format(self, client, db):
        """Invalid export format returns 400."""
        resp = client.get('/api/questions/export?format=xml')
        assert resp.status_code == 400
