import json
import pytest
from tests.conftest import create_question_in_db, create_exam_in_db


class TestBatchDelete:
    """Tests for batch delete endpoint."""

    def test_batch_delete_multiple_questions(self, client, db):
        create_question_in_db(db, question_id='bd_q1', content='题目1')
        create_question_in_db(db, question_id='bd_q2', content='题目2')
        create_question_in_db(db, question_id='bd_q3', content='题目3')

        resp = client.post('/api/questions/batch-delete', json={
            'question_ids': ['bd_q1', 'bd_q2']
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['deleted_count'] == 2

        # q3 should still exist
        resp = client.get('/api/questions/bd_q3')
        assert resp.status_code == 200

        # q1 should be gone
        resp = client.get('/api/questions/bd_q1')
        assert resp.status_code == 404

    def test_batch_delete_empty_list(self, client):
        resp = client.post('/api/questions/batch-delete', json={
            'question_ids': []
        })
        assert resp.status_code == 400

    def test_batch_delete_cleans_exam_associations(self, client, db):
        create_question_in_db(db, question_id='assoc_q1', content='关联题目')
        create_exam_in_db(db, exam_id='assoc_exam', name='关联试卷',
                          question_ids=['assoc_q1'])

        resp = client.post('/api/questions/batch-delete', json={
            'question_ids': ['assoc_q1']
        })
        assert resp.status_code == 200
        assert resp.get_json()['deleted_count'] == 1

        # Exam should still exist but have no questions
        resp = client.get('/api/exams/assoc_exam')
        assert resp.status_code == 200
        assert len(resp.get_json()['questions']) == 0

    def test_batch_delete_partial_existing(self, client, db):
        create_question_in_db(db, question_id='partial_q1', content='存在')

        resp = client.post('/api/questions/batch-delete', json={
            'question_ids': ['partial_q1', 'nonexistent_q']
        })
        assert resp.status_code == 200
        # Only the existing one gets deleted
        assert resp.get_json()['deleted_count'] == 1

    def test_batch_delete_all_nonexistent(self, client):
        resp = client.post('/api/questions/batch-delete', json={
            'question_ids': ['nope1', 'nope2']
        })
        assert resp.status_code == 200
        assert resp.get_json()['deleted_count'] == 0
