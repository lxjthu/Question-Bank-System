import pytest
import json
from app.factory import create_app
from app.db_models import db as _db, QuestionModel, ExamModel, QuestionTypeModel, exam_questions
from datetime import datetime


@pytest.fixture
def app():
    """Create test application with in-memory SQLite."""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Database session."""
    with app.app_context():
        yield _db


@pytest.fixture
def sample_question_data():
    """Single choice question sample data."""
    return {
        'question_id': 'test_q_001',
        'question_type': '单选',
        'content': '以下哪个是Python的关键字？',
        'options': ['class', 'define', 'include', 'var'],
        'answer': 'A',
        'language': 'zh',
    }


@pytest.fixture
def sample_exam_data():
    """Exam sample data."""
    return {
        'exam_id': 'test_exam_001',
        'name': '测试试卷',
        'config': {'单选': {'count': 2, 'points': 5}},
    }


def create_question_in_db(db_session, question_id='test_q_001', question_type='单选',
                           content='测试题目', options=None, answer='A',
                           language='zh', is_used=False,
                           content_en=None, options_en=None,
                           knowledge_point=None, tags=None, difficulty=None):
    """Helper to insert a QuestionModel directly into the DB."""
    now = datetime.now()
    q = QuestionModel(
        question_id=question_id,
        question_type=question_type,
        content=content,
        options=json.dumps(options or ['A选项', 'B选项', 'C选项', 'D选项'], ensure_ascii=False),
        answer=answer,
        content_en=content_en,
        options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
        knowledge_point=knowledge_point,
        tags=tags,
        difficulty=difficulty,
        language=language,
        metadata_json='{}',
        is_used=is_used,
        created_at=now,
        updated_at=now,
    )
    db_session.session.add(q)
    db_session.session.commit()
    return q


def create_exam_in_db(db_session, exam_id='test_exam_001', name='测试试卷',
                       config=None, question_ids=None):
    """Helper to insert an ExamModel directly into the DB."""
    now = datetime.now()
    exam = ExamModel(
        exam_id=exam_id,
        name=name,
        config=json.dumps(config or {}, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    db_session.session.add(exam)
    db_session.session.flush()

    if question_ids:
        for pos, qid in enumerate(question_ids):
            db_session.session.execute(exam_questions.insert().values(
                exam_id=exam_id,
                question_id=qid,
                position=pos,
            ))

    db_session.session.commit()
    return exam
