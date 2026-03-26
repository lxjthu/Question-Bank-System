"""
tests/conftest.py — 测试基础 fixtures

覆盖范围：
- 内存 SQLite（完全隔离，不影响真实数据库）
- 自动创建 admin / user_a / user_b / guest 四个测试账号
- 登录辅助函数
"""
import pytest
import json
from datetime import datetime
from werkzeug.security import generate_password_hash

from app.factory import create_app
from app.db_models import db as _db, QuestionModel, ExamModel, QuestionTypeModel, exam_questions, User


# ──────────────────────────────────────────────────────────────────────────────
# 核心 fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """内存 SQLite，每个测试函数独立隔离。"""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


# ──────────────────────────────────────────────────────────────────────────────
# 用户 fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    # create_app('testing') 的 _seed_system_users 已创建 admin，直接复用
    existing = User.query.filter_by(username='admin', role='admin').first()
    if existing:
        return existing
    u = User(
        username='admin',
        password_hash=generate_password_hash('admin123'),
        role='admin',
    )
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def user_a(db):
    u = User(
        username='user_a',
        password_hash=generate_password_hash('pass_a'),
        role='user',
    )
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def user_b(db):
    u = User(
        username='user_b',
        password_hash=generate_password_hash('pass_b'),
        role='user',
    )
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def guest_user(db):
    # create_app('testing') 的 _seed_system_users 已创建 guest，直接复用
    existing = User.query.filter_by(username='guest', role='guest').first()
    if existing:
        return existing
    u = User(
        username='guest',
        password_hash=generate_password_hash(''),
        role='guest',
    )
    db.session.add(u)
    db.session.commit()
    return u


# ──────────────────────────────────────────────────────────────────────────────
# 登录辅助
# ──────────────────────────────────────────────────────────────────────────────

def login(client, username, password=''):
    return client.post('/api/auth/login', json={'username': username, 'password': password})


def login_as(client, username, password):
    r = login(client, username, password)
    assert r.status_code == 200, f"登录失败: {r.get_json()}"
    return r


def guest_login(client):
    r = client.post('/api/auth/guest')
    assert r.status_code == 200
    return r


# ──────────────────────────────────────────────────────────────────────────────
# 题目 / 试卷构造辅助
# ──────────────────────────────────────────────────────────────────────────────

def make_question(db_session, question_id, owner_id=None,
                  visibility='private', question_type='单选',
                  content='测试题目', team_id=None):
    now = datetime.now()
    q = QuestionModel(
        question_id=question_id,
        question_type=question_type,
        content=content,
        options=json.dumps(['A', 'B', 'C', 'D'], ensure_ascii=False),
        answer='A',
        language='zh',
        metadata_json='{}',
        owner_id=owner_id,
        visibility=visibility,
        team_id=team_id,
        created_at=now,
        updated_at=now,
    )
    db_session.session.add(q)
    db_session.session.commit()
    return q


def make_exam(db_session, exam_id, owner_id=None, visibility='private', name='测试试卷'):
    now = datetime.now()
    e = ExamModel(
        exam_id=exam_id,
        name=name,
        config='{}',
        owner_id=owner_id,
        visibility=visibility,
        created_at=now,
        updated_at=now,
    )
    db_session.session.add(e)
    db_session.session.commit()
    return e
