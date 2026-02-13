"""Tests for edge cases and boundary conditions."""
import json
import pytest
from tests.conftest import create_question_in_db, create_exam_in_db


class TestInputValidation:
    def test_add_question_missing_fields(self, client, db):
        """Missing required fields still creates (content may be None but DB allows it)."""
        resp = client.post('/api/questions', json={
            'question_id': 'mf1',
            'question_type': '单选',
            'content': '',
        })
        # Should succeed since we allow empty content at API level
        assert resp.status_code == 201

    def test_add_question_empty_content(self, client, db):
        """Empty content question can be created."""
        resp = client.post('/api/questions', json={
            'question_id': 'ec1',
            'question_type': '简答',
            'content': '',
        })
        assert resp.status_code == 201
        assert resp.get_json()['content'] == ''


class TestSpecialContent:
    def test_question_special_characters(self, client, db):
        """Special characters (quotes, newlines, HTML) preserved."""
        content = '这是一个"特殊"题目\n包含<html>标签&符号'
        resp = client.post('/api/questions', json={
            'question_id': 'sp1',
            'question_type': '简答',
            'content': content,
        })
        assert resp.status_code == 201
        assert resp.get_json()['content'] == content

    def test_question_unicode_content(self, client, db):
        """Chinese/English mixed content works correctly."""
        content = '林业经济学 Forestry Economics 第三章 Chapter 3'
        resp = client.post('/api/questions', json={
            'question_id': 'uc1',
            'question_type': '论述',
            'content': content,
            'language': 'both',
        })
        assert resp.status_code == 201
        assert resp.get_json()['content'] == content

    def test_very_long_content(self, client, db):
        """Very long content is handled correctly."""
        content = '长内容测试' * 1000  # 5000 Chinese characters
        resp = client.post('/api/questions', json={
            'question_id': 'lc1',
            'question_type': '论述',
            'content': content,
        })
        assert resp.status_code == 201
        assert resp.get_json()['content'] == content


class TestDuplicateHandling:
    def test_duplicate_question_id(self, client, db):
        """Duplicate question ID results in error (primary key constraint)."""
        client.post('/api/questions', json={
            'question_id': 'dup1',
            'question_type': '单选',
            'content': '第一题',
        })
        resp = client.post('/api/questions', json={
            'question_id': 'dup1',
            'question_type': '单选',
            'content': '重复题',
        })
        # SQLAlchemy raises IntegrityError — any error status is acceptable
        assert resp.status_code >= 400


class TestEmptyExamOperations:
    def test_empty_exam_operations(self, client, db):
        """Operations on empty exam work without error."""
        create_exam_in_db(db, exam_id='empty1', name='空试卷')
        # Confirm empty exam
        resp = client.post('/api/exams/empty1/confirm')
        assert resp.status_code == 200
        # Revert empty exam
        resp = client.post('/api/exams/empty1/revert_confirmation')
        assert resp.status_code == 200

    def test_exam_with_no_config(self, client, db):
        """Exam with empty config works."""
        resp = client.post('/api/exams', json={
            'exam_id': 'nc1',
            'name': '无配置试卷',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['config'] == {}


class TestDataIntegrity:
    def test_concurrent_data_integrity(self, client, db):
        """Rapid sequential operations maintain data integrity."""
        # Create 10 questions rapidly
        for i in range(10):
            client.post('/api/questions', json={
                'question_id': f'ci{i}',
                'question_type': '单选',
                'content': f'快速题目{i}',
                'options': ['A', 'B', 'C', 'D'],
                'answer': 'A',
            })
        # Verify all 10 exist
        resp = client.get('/api/questions')
        assert len(resp.get_json()) == 10

        # Delete 5 rapidly
        for i in range(5):
            client.delete(f'/api/questions/ci{i}')
        resp = client.get('/api/questions')
        assert len(resp.get_json()) == 5


class TestIndexPage:
    def test_index_page(self, client, db):
        """GET / returns 200 and HTML."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'html' in resp.data.lower() or b'<!DOCTYPE' in resp.data or b'<html' in resp.data
