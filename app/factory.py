from flask import Flask, jsonify
from app.routes import bp
from app.db_models import db, QuestionTypeModel, User
from config import config
from datetime import datetime
from sqlalchemy import text, event
from sqlalchemy.engine import Engine
from werkzeug.security import generate_password_hash
import sqlite3
import os
import threading


@event.listens_for(Engine, "connect")
def _set_sqlite_wal(dbapi_conn, connection_record):
    """SQLite 启用 WAL 模式 + 30s 超时，解决多 worker 并发写锁问题。"""
    if isinstance(dbapi_conn, sqlite3.Connection):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=30000")


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    for key in ('UPLOAD_FOLDER', 'TEMP_FOLDER', 'EXPORTS_FOLDER'):
        folder = app.config.get(key)
        if folder:
            os.makedirs(folder, exist_ok=True)
    upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(os.path.join(upload_folder, 'images'), exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_question_types()
        _seed_system_users(app)

    app.register_blueprint(bp)

    from app.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    from app.team_routes import team_bp
    app.register_blueprint(team_bp)

    try:
        from app.rag_routes import rag_bp
        app.register_blueprint(rag_bp)
    except Exception:
        pass

    try:
        from app.kg_routes import kg_bp
        app.register_blueprint(kg_bp)
    except Exception:
        pass

    try:
        from app.interview_routes import interview_bp
        app.register_blueprint(interview_bp)
    except Exception:
        pass

    # ── 微信小程序相关（新增）────────────────────────────────────────────
    try:
        from app.mp_auth_routes import mp_bp
        app.register_blueprint(mp_bp)
    except Exception as e:
        app.logger.warning(f'[mp_auth] 加载失败: {e}')

    try:
        from app.session_routes import session_bp
        app.register_blueprint(session_bp)
    except Exception as e:
        app.logger.warning(f'[session] 加载失败: {e}')

    try:
        from app.answer_routes import answer_bp
        app.register_blueprint(answer_bp)
    except Exception as e:
        app.logger.warning(f'[answer] 加载失败: {e}')

    @app.route('/api/shutdown', methods=['POST'])
    def _shutdown():
        def _kill():
            import time
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=_kill, daemon=True).start()
        return jsonify({'ok': True, 'message': '正在退出...'})

    return app


def _migrate_db():
    new_cols = [
        ('exams',     'subject',        'VARCHAR(128)'),
        ('exams',     'is_confirmed',   'BOOLEAN DEFAULT 0'),
        ('exams',     'confirmed_at',   'DATETIME'),
        ('questions', 'imported_at',    'DATETIME'),
        ('questions', 'interview_pool', 'BOOLEAN DEFAULT 0'),
        ('questions', 'interview_set',  'BOOLEAN DEFAULT 0'),
        ('questions', 'interview_used', 'BOOLEAN DEFAULT 0'),
        # 多用户隔离字段
        ('questions',      'owner_id',   'INTEGER'),
        ('questions',      'visibility', "VARCHAR(16) DEFAULT 'private'"),
        ('questions',      'team_id',    'INTEGER'),
        ('exams',          'owner_id',   'INTEGER'),
        ('exams',          'visibility', "VARCHAR(16) DEFAULT 'private'"),
        ('exams',          'team_id',    'INTEGER'),
        ('interview_pools',    'owner_id', 'INTEGER'),
        ('interview_sessions', 'owner_id', 'INTEGER'),
        ('question_types',     'owner_id', 'INTEGER'),
    ]
    new_tables = [
        """CREATE TABLE IF NOT EXISTS interview_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_name VARCHAR(128) NOT NULL,
            description TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS interview_pool_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_id INTEGER NOT NULL,
            question_id VARCHAR(64) NOT NULL,
            drawn BOOLEAN DEFAULT 0,
            drawn_at DATETIME,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pool_id, question_id)
        )""",
        """CREATE TABLE IF NOT EXISTS interview_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_id INTEGER NOT NULL,
            config_name VARCHAR(128) DEFAULT 'default',
            slots_json TEXT NOT NULL DEFAULT '[]',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS interview_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_id INTEGER NOT NULL,
            config_id INTEGER,
            session_name VARCHAR(256) NOT NULL,
            interview_count INTEGER NOT NULL DEFAULT 1,
            sets_multiplier INTEGER NOT NULL DEFAULT 3,
            score_per_slot_json TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS interview_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            set_code VARCHAR(32) NOT NULL,
            question_ids_json TEXT NOT NULL DEFAULT '[]',
            is_used BOOLEAN DEFAULT 0,
            used_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS demo_kp_hidden (
            user_id INTEGER NOT NULL,
            kp_id   INTEGER NOT NULL,
            PRIMARY KEY (user_id, kp_id)
        )""",
        # ── 微信小程序相关（新增）──────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS wx_users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            openid      VARCHAR(64) UNIQUE NOT NULL,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            nickname    VARCHAR(128) DEFAULT '',
            avatar_url  TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login  DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS exam_sessions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id           VARCHAR(64) NOT NULL REFERENCES exams(exam_id),
            teacher_id        INTEGER NOT NULL REFERENCES users(id),
            title             VARCHAR(256) NOT NULL,
            code              VARCHAR(8) UNIQUE NOT NULL,
            qr_key            VARCHAR(64) UNIQUE NOT NULL,
            status            VARCHAR(16) DEFAULT 'draft',
            duration_minutes  INTEGER DEFAULT 0,
            allow_retake      BOOLEAN DEFAULT 0,
            shuffle_questions BOOLEAN DEFAULT 1,
            show_answer       BOOLEAN DEFAULT 1,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at        DATETIME,
            ended_at          DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS student_exams (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     INTEGER NOT NULL REFERENCES exam_sessions(id),
            wx_user_id     INTEGER NOT NULL REFERENCES wx_users(id),
            question_order TEXT DEFAULT '[]',
            status         VARCHAR(16) DEFAULT 'joined',
            obj_score      REAL DEFAULT 0,
            total_score    REAL,
            started_at     DATETIME,
            submitted_at   DATETIME,
            graded_at      DATETIME,
            grader_id      INTEGER REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS student_answers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_exam_id INTEGER NOT NULL REFERENCES student_exams(id),
            question_id     VARCHAR(64) NOT NULL REFERENCES questions(question_id),
            answer_text     TEXT DEFAULT '',
            is_correct      BOOLEAN,
            auto_score      REAL DEFAULT 0,
            manual_score    REAL,
            answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_exam_id, question_id)
        )""",
    ]
    with db.engine.connect() as conn:
        for table, col, col_def in new_cols:
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {col_def}'))
                conn.commit()
            except Exception:
                pass  # Column already exists
        for ddl in new_tables:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass


def _seed_question_types():
    # 只在内置题型（owner_id IS NULL + is_builtin）缺失时补充
    if QuestionTypeModel.query.filter_by(is_builtin=True, owner_id=None).count() == 0:
        now = datetime.now()
        builtins = [
            QuestionTypeModel(name='单选',          label='单选题',     has_options=True,  is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='多选',          label='多选题',     has_options=True,  is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='是非',          label='是非题',     has_options=True,  is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='简答',          label='简答题',     has_options=False, is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='简答>计算',     label='计算题',     has_options=False, is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='简答>论述',     label='论述题',     has_options=False, is_builtin=True, owner_id=None, created_at=now),
            QuestionTypeModel(name='简答>材料分析', label='材料分析题', has_options=False, is_builtin=True, owner_id=None, created_at=now),
        ]
        db.session.add_all(builtins)
        db.session.commit()


def _seed_system_users(app):
    """
    初始化系统账号：
    - admin：密码来自 ADMIN_PASSWORD 环境变量，默认 admin123（首次启动后请立即修改）
    - guest：role=guest，通过 /api/auth/guest 一键登录
    旧数据（无 owner_id 的题目/试卷）自动归给 admin，visibility=private。
    """
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin_pw = os.environ.get('ADMIN_PASSWORD', 'admin123')
        admin = User(
            username='admin',
            password_hash=generate_password_hash(admin_pw),
            role='admin',
        )
        db.session.add(admin)
        db.session.flush()
        db.session.execute(text(
            f"UPDATE questions SET owner_id={admin.id}, visibility='private' WHERE owner_id IS NULL"
        ))
        db.session.execute(text(
            f"UPDATE exams SET owner_id={admin.id}, visibility='private' WHERE owner_id IS NULL"
        ))
        db.session.commit()
        app.logger.info('[init] admin 账号已创建，请尽快修改默认密码 (ADMIN_PASSWORD 环境变量)')

    guest = User.query.filter_by(username='guest', role='guest').first()
    if not guest:
        guest = User(
            username='guest',
            password_hash=generate_password_hash(''),
            role='guest',
        )
        db.session.add(guest)
        db.session.commit()
        app.logger.info('[init] guest 账号已创建')
