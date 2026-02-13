import json
import pytest
from datetime import datetime
from tests.conftest import create_question_in_db


class TestUsageManagement:
    """Tests for usage management features: is_used filter and batch release."""

    def test_filter_used_questions(self, client, db):
        """GET /api/questions?is_used=1 returns only used questions."""
        create_question_in_db(db, question_id='u1', content='已使用', is_used=True)
        create_question_in_db(db, question_id='u2', content='未使用', is_used=False)
        create_question_in_db(db, question_id='u3', content='也已使用', is_used=True)

        resp = client.get('/api/questions?is_used=1')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        ids = {q['question_id'] for q in data}
        assert ids == {'u1', 'u3'}

    def test_filter_unused_questions(self, client, db):
        """GET /api/questions?is_used=0 returns only unused questions."""
        create_question_in_db(db, question_id='u1', content='已使用', is_used=True)
        create_question_in_db(db, question_id='u2', content='未使用', is_used=False)

        resp = client.get('/api/questions?is_used=0')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'u2'

    def test_batch_release_questions(self, client, db):
        """POST /api/questions/batch-release marks questions as unused."""
        create_question_in_db(db, question_id='r1', content='题1', is_used=True)
        create_question_in_db(db, question_id='r2', content='题2', is_used=True)
        create_question_in_db(db, question_id='r3', content='题3', is_used=False)

        resp = client.post('/api/questions/batch-release', json={
            'question_ids': ['r1', 'r2']
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['released_count'] == 2

        # Verify they are now unused
        resp = client.get('/api/questions/r1')
        assert resp.get_json()['is_used'] is False
        assert resp.get_json()['used_date'] is None

        resp = client.get('/api/questions/r2')
        assert resp.get_json()['is_used'] is False

    def test_batch_release_empty_list(self, client):
        """POST /api/questions/batch-release with empty list returns 400."""
        resp = client.post('/api/questions/batch-release', json={
            'question_ids': []
        })
        assert resp.status_code == 400

    def test_batch_release_already_unused(self, client, db):
        """Releasing already-unused questions returns released_count=0."""
        create_question_in_db(db, question_id='nu1', content='未使用', is_used=False)

        resp = client.post('/api/questions/batch-release', json={
            'question_ids': ['nu1']
        })
        assert resp.status_code == 200
        assert resp.get_json()['released_count'] == 0

    def test_batch_release_partial(self, client, db):
        """Mix of used and unused — only used ones are counted."""
        create_question_in_db(db, question_id='p1', content='已使用', is_used=True)
        create_question_in_db(db, question_id='p2', content='未使用', is_used=False)

        resp = client.post('/api/questions/batch-release', json={
            'question_ids': ['p1', 'p2', 'nonexistent']
        })
        assert resp.status_code == 200
        assert resp.get_json()['released_count'] == 1

    def test_filter_used_combined_with_type(self, client, db):
        """is_used filter works together with type filter."""
        create_question_in_db(db, question_id='ct1', question_type='单选', content='单选已使用', is_used=True)
        create_question_in_db(db, question_id='ct2', question_type='多选', content='多选已使用', is_used=True)
        create_question_in_db(db, question_id='ct3', question_type='单选', content='单选未使用', is_used=False)

        resp = client.get('/api/questions?is_used=1&type=单选')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['question_id'] == 'ct1'
