"""Tests for SQLAlchemy ORM models (QuestionModel, ExamModel)."""
import json
import pytest
from datetime import datetime
from app.db_models import db, QuestionModel, ExamModel, exam_questions
from tests.conftest import create_question_in_db, create_exam_in_db


class TestQuestionModel:
    def test_create_question_model(self, app, db):
        """Create a QuestionModel and verify fields."""
        q = create_question_in_db(db, question_id='q1', content='What is 1+1?')
        fetched = db.session.get(QuestionModel, 'q1')
        assert fetched is not None
        assert fetched.question_id == 'q1'
        assert fetched.content == 'What is 1+1?'
        assert fetched.question_type == '单选'

    def test_question_to_dict(self, app, db):
        """to_dict() output has correct format and options deserialized as list."""
        q = create_question_in_db(db, question_id='q2', options=['A', 'B', 'C', 'D'])
        d = q.to_dict()
        assert d['question_id'] == 'q2'
        assert isinstance(d['options'], list)
        assert d['options'] == ['A', 'B', 'C', 'D']
        assert isinstance(d['metadata'], dict)

    def test_question_options_json(self, app, db):
        """Options stored as JSON string and read back correctly."""
        opts = ['选项一', '选项二', '选项三']
        q = create_question_in_db(db, question_id='q3', options=opts)
        # Raw column value is JSON string
        assert isinstance(q.options, str)
        assert json.loads(q.options) == opts

    def test_question_metadata_json(self, app, db):
        """Metadata stored as JSON string and read back correctly."""
        now = datetime.now()
        q = QuestionModel(
            question_id='q4', question_type='单选', content='test',
            options='[]', metadata_json=json.dumps({'source': 'textbook', 'chapter': 3}),
            created_at=now, updated_at=now,
        )
        db.session.add(q)
        db.session.commit()
        d = q.to_dict()
        assert d['metadata'] == {'source': 'textbook', 'chapter': 3}

    def test_question_is_used_default(self, app, db):
        """is_used defaults to False."""
        q = create_question_in_db(db, question_id='q5')
        assert q.is_used is False

    def test_question_timestamps(self, app, db):
        """created_at and updated_at are properly set."""
        q = create_question_in_db(db, question_id='q6')
        assert q.created_at is not None
        assert q.updated_at is not None
        d = q.to_dict()
        # Should be ISO format strings
        assert 'T' in d['created_at']
        assert 'T' in d['updated_at']

    def test_question_nullable_fields(self, app, db):
        """Nullable fields (answer, explanation, reference_answer) can be None."""
        now = datetime.now()
        q = QuestionModel(
            question_id='q7', question_type='简答', content='Describe something.',
            options='[]', created_at=now, updated_at=now,
        )
        db.session.add(q)
        db.session.commit()
        d = q.to_dict()
        assert d['answer'] is None
        assert d['explanation'] is None
        assert d['reference_answer'] is None


class TestExamModel:
    def test_create_exam_model(self, app, db):
        """Create an ExamModel and verify fields."""
        exam = create_exam_in_db(db, exam_id='e1', name='期末考试')
        fetched = db.session.get(ExamModel, 'e1')
        assert fetched is not None
        assert fetched.name == '期末考试'

    def test_exam_to_dict(self, app, db):
        """to_dict() output has correct format."""
        exam = create_exam_in_db(db, exam_id='e2', name='测试')
        d = exam.to_dict()
        assert d['exam_id'] == 'e2'
        assert d['name'] == '测试'
        assert isinstance(d['questions'], list)
        assert isinstance(d['config'], dict)

    def test_exam_question_relationship(self, app, db):
        """Many-to-many relationship: add and remove questions."""
        q1 = create_question_in_db(db, question_id='rq1')
        q2 = create_question_in_db(db, question_id='rq2', content='第二题')
        exam = create_exam_in_db(db, exam_id='re1', question_ids=['rq1', 'rq2'])

        d = exam.to_dict()
        assert len(d['questions']) == 2

        # Remove one question
        db.session.execute(
            exam_questions.delete().where(
                (exam_questions.c.exam_id == 're1') &
                (exam_questions.c.question_id == 'rq1')
            )
        )
        db.session.commit()
        d = exam.to_dict()
        assert len(d['questions']) == 1
        assert d['questions'][0]['question_id'] == 'rq2'

    def test_exam_config_json(self, app, db):
        """Config stored as JSON string and read back correctly."""
        config = {'单选': {'count': 10, 'points': 2}}
        exam = create_exam_in_db(db, exam_id='e3', config=config)
        d = exam.to_dict()
        assert d['config'] == config

    def test_exam_calculate_total_score(self, app, db):
        """calculate_total_score uses config to sum points."""
        q1 = create_question_in_db(db, question_id='sq1', question_type='单选')
        q2 = create_question_in_db(db, question_id='sq2', question_type='单选', content='题目2')
        q3 = create_question_in_db(db, question_id='sq3', question_type='是非', content='判断题')
        config = {'单选': {'count': 2, 'points': 5}, '是非': {'count': 1, 'points': 2}}
        exam = create_exam_in_db(db, exam_id='se1', config=config, question_ids=['sq1', 'sq2', 'sq3'])
        assert exam.calculate_total_score() == 12  # 5+5+2

    def test_exam_get_ordered_questions(self, app, db):
        """get_ordered_questions returns questions in position order."""
        q1 = create_question_in_db(db, question_id='oq1', content='第一题')
        q2 = create_question_in_db(db, question_id='oq2', content='第二题')
        q3 = create_question_in_db(db, question_id='oq3', content='第三题')
        exam = create_exam_in_db(db, exam_id='oe1', question_ids=['oq1', 'oq2', 'oq3'])
        ordered = exam.get_ordered_questions()
        assert [q.question_id for q in ordered] == ['oq1', 'oq2', 'oq3']
