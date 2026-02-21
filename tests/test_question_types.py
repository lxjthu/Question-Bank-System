import json
import pytest
from tests.conftest import create_question_in_db


class TestQuestionTypeCRUD:
    """Tests for question type CRUD endpoints."""

    def test_get_question_types_returns_builtin(self, client):
        """Seed data should include 7 built-in types."""
        resp = client.get('/api/question-types')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 7
        names = [t['name'] for t in data]
        assert '单选' in names
        assert '简答>材料分析' in names
        assert all(t['is_builtin'] for t in data)

    def test_create_custom_type(self, client):
        resp = client.post('/api/question-types', json={
            'name': '简答>案例',
            'label': '案例分析题',
            'has_options': False,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == '简答>案例'
        assert data['label'] == '案例分析题'
        assert data['has_options'] is False
        assert data['is_builtin'] is False

    def test_create_duplicate_name_fails(self, client):
        resp = client.post('/api/question-types', json={
            'name': '单选',
            'label': '重复',
        })
        assert resp.status_code == 400
        assert 'already exists' in resp.get_json()['error']

    def test_create_empty_name_fails(self, client):
        resp = client.post('/api/question-types', json={
            'name': '',
            'label': '空名字',
        })
        assert resp.status_code == 400

    def test_update_question_type(self, client):
        # Create a custom type first
        resp = client.post('/api/question-types', json={
            'name': '自定义',
            'label': '自定义题',
        })
        type_id = resp.get_json()['id']

        resp = client.put(f'/api/question-types/{type_id}', json={
            'label': '改名后',
        })
        assert resp.status_code == 200
        assert resp.get_json()['label'] == '改名后'

    def test_update_duplicate_name_fails(self, client):
        resp = client.post('/api/question-types', json={
            'name': '测试题型',
            'label': '测试',
        })
        type_id = resp.get_json()['id']

        resp = client.put(f'/api/question-types/{type_id}', json={
            'name': '单选',  # conflicts with built-in
        })
        assert resp.status_code == 400

    def test_delete_custom_type(self, client):
        resp = client.post('/api/question-types', json={
            'name': '要删除',
            'label': '要删除',
        })
        type_id = resp.get_json()['id']

        resp = client.delete(f'/api/question-types/{type_id}')
        assert resp.status_code == 200

        # Verify deleted
        types = client.get('/api/question-types').get_json()
        assert all(t['name'] != '要删除' for t in types)

    def test_delete_builtin_fails(self, client):
        types = client.get('/api/question-types').get_json()
        builtin_id = next(t['id'] for t in types if t['is_builtin'])

        resp = client.delete(f'/api/question-types/{builtin_id}')
        assert resp.status_code == 400
        assert 'built-in' in resp.get_json()['error']

    def test_delete_referenced_type_fails(self, client, db):
        # Create custom type
        resp = client.post('/api/question-types', json={
            'name': '被引用',
            'label': '被引用题',
        })
        type_id = resp.get_json()['id']

        # Create a question referencing this type
        create_question_in_db(db, question_id='ref_q', question_type='被引用')

        resp = client.delete(f'/api/question-types/{type_id}')
        assert resp.status_code == 400
        assert 'questions use this type' in resp.get_json()['error']

    def test_delete_nonexistent_type(self, client):
        resp = client.delete('/api/question-types/99999')
        assert resp.status_code == 404
