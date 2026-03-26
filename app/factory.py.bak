from flask import Flask, jsonify
from app.routes import bp
from app.db_models import db, QuestionTypeModel
from config import config
from datetime import datetime
from sqlalchemy import text
import os
import sys
import threading


def create_app(config_name=None):
    """Application factory function to create and configure the Flask app"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure writable data directories exist at startup
    for key in ('UPLOAD_FOLDER', 'TEMP_FOLDER', 'EXPORTS_FOLDER'):
        folder = app.config.get(key)
        if folder:
            os.makedirs(folder, exist_ok=True)
    upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(os.path.join(upload_folder, 'images'), exist_ok=True)

    # Initialize database
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_question_types()

    # Register core blueprint
    app.register_blueprint(bp)

    # Register optional AI/KG blueprints (may be absent in bundled builds)
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

    # ── 退出端点（打包版 EXE 使用，彻底结束进程）────────────────────────────────
    @app.route('/api/shutdown', methods=['POST'])
    def _shutdown():
        """彻底退出 EXE 进程。延迟 0.5s 确保响应已发送。"""
        def _kill():
            import time
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=_kill, daemon=True).start()
        return jsonify({'ok': True, 'message': '正在退出...'})

    return app


def _migrate_db():
    """Add new columns to existing tables if they don't exist (idempotent)."""
    new_cols = [
        ('exams', 'subject', 'VARCHAR(128)'),
        ('exams', 'is_confirmed', 'BOOLEAN DEFAULT 0'),
        ('exams', 'confirmed_at', 'DATETIME'),
        ('questions', 'imported_at', 'DATETIME'),
        ('questions', 'interview_pool', 'BOOLEAN DEFAULT 0'),
        ('questions', 'interview_set', 'BOOLEAN DEFAULT 0'),
        ('questions', 'interview_used', 'BOOLEAN DEFAULT 0'),
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
    """Insert built-in question types if the table is empty."""
    if QuestionTypeModel.query.count() == 0:
        now = datetime.now()
        builtins = [
            QuestionTypeModel(name='单选', label='单选题', has_options=True, is_builtin=True, created_at=now),
            QuestionTypeModel(name='多选', label='多选题', has_options=True, is_builtin=True, created_at=now),
            QuestionTypeModel(name='是非', label='是非题', has_options=True, is_builtin=True, created_at=now),
            QuestionTypeModel(name='简答', label='简答题', has_options=False, is_builtin=True, created_at=now),
            QuestionTypeModel(name='简答>计算', label='计算题', has_options=False, is_builtin=True, created_at=now),
            QuestionTypeModel(name='简答>论述', label='论述题', has_options=False, is_builtin=True, created_at=now),
            QuestionTypeModel(name='简答>材料分析', label='材料分析题', has_options=False, is_builtin=True, created_at=now),
        ]
        db.session.add_all(builtins)
        db.session.commit()
