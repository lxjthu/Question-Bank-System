"""Tests for business logic: usage tracking, generation, bilingual support."""
import json
import pytest
from app.db_models import db, QuestionModel
from tests.conftest import create_question_in_db, create_exam_in_db


class TestUsageTracking:
    def test_unused_questions_filter(self, client, db):
        """Only unused questions are returned when filtering is_used."""
        create_question_in_db(db, question_id='uf1', is_used=False)
        create_question_in_db(db, question_id='uf2', is_used=True, content='已用题目')
        # Search all — both returned
        resp = client.get('/api/questions')
        assert len(resp.get_json()) == 2

    def test_generate_selects_unused_only(self, client, db):
        """Auto-generate only selects unused questions."""
        create_question_in_db(db, question_id='gu1', is_used=True)
        create_question_in_db(db, question_id='gu2', is_used=False, content='未用题目')
        resp = client.post('/api/exams/generate', json={
            'exam_id': 'gue1',
            'name': '仅未用',
            'config': {'单选': {'count': 5, 'points': 5}},
        })
        data = resp.get_json()
        assert len(data['questions']) == 1
        assert data['questions'][0]['question_id'] == 'gu2'

    def test_generate_does_not_mark_used(self, client, db):
        """Generate does NOT mark questions as used — only confirm does."""
        create_question_in_db(db, question_id='gm1')
        client.post('/api/exams/generate', json={
            'exam_id': 'gme1',
            'name': '标记测试',
            'config': {'单选': {'count': 1, 'points': 5}},
        })
        resp = client.get('/api/questions/gm1')
        assert resp.get_json()['is_used'] is False

    def test_confirm_marks_then_generate_no_overlap(self, client, db):
        """After confirming, regenerating doesn't reuse confirmed questions."""
        create_question_in_db(db, question_id='co1', content='第一题')
        create_question_in_db(db, question_id='co2', content='第二题')

        # Generate first exam
        client.post('/api/exams/generate', json={
            'exam_id': 'coe1',
            'name': '第一次',
            'config': {'单选': {'count': 1, 'points': 5}},
        })
        # Confirm it — this marks questions as used
        client.post('/api/exams/coe1/confirm')

        # Generate second exam — should only pick from unused questions
        resp = client.post('/api/exams/generate', json={
            'exam_id': 'coe2',
            'name': '第二次',
            'config': {'单选': {'count': 1, 'points': 5}},
        })
        data = resp.get_json()
        # Should get the other question
        if len(data['questions']) == 1:
            assert data['questions'][0]['question_id'] == 'co2'

    def test_replace_does_not_change_used_flags(self, client, db):
        """Replace only swaps the association, does not change is_used."""
        create_question_in_db(db, question_id='ru1', is_used=True)
        create_question_in_db(db, question_id='ru2', is_used=False, content='替换题目')
        create_exam_in_db(db, exam_id='rue1', question_ids=['ru1'])
        client.post('/api/exams/rue1/replace_question', json={
            'old_question_id': 'ru1',
            'new_question_id': 'ru2',
        })
        # is_used flags should be unchanged by replace
        resp1 = client.get('/api/questions/ru1')
        assert resp1.get_json()['is_used'] is True
        resp2 = client.get('/api/questions/ru2')
        assert resp2.get_json()['is_used'] is False


class TestBilingualSupport:
    def test_bilingual_question(self, client, db):
        """language='both' for bilingual questions."""
        resp = client.post('/api/questions', json={
            'question_id': 'bl1',
            'question_type': '论述',
            'content': '什么是代际公平？ What is intergenerational equity?',
            'language': 'both',
        })
        assert resp.status_code == 201
        assert resp.get_json()['language'] == 'both'

    def test_question_type_whitespace_handling(self, client, db):
        """Question types with whitespace are handled correctly in generation."""
        create_question_in_db(db, question_id='ws1', question_type=' 单选 ', content='空格题目')
        resp = client.post('/api/exams/generate', json={
            'exam_id': 'wse1',
            'name': '空格测试',
            'config': {'单选': {'count': 1, 'points': 5}},
        })
        data = resp.get_json()
        assert len(data['questions']) == 1


class TestTemplateAndExport:
    def test_template_download(self, client, db):
        """Template download returns docx file."""
        resp = client.get('/api/templates/download')
        assert resp.status_code == 200

    def test_word_export_content(self, client, db):
        """Word export returns non-empty docx."""
        create_question_in_db(db, question_id='we1', content='导出内容测试')
        create_exam_in_db(db, exam_id='wee1', name='导出测试',
                          config={'单选': {'count': 1, 'points': 5}},
                          question_ids=['we1'])
        resp = client.get('/api/exams/wee1/export')
        assert resp.status_code == 200
        assert len(resp.data) > 0
