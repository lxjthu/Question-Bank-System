from flask import Flask
from app.routes import bp
from app.rag_routes import rag_bp
from app.kg_routes import kg_bp
from app.db_models import db, QuestionTypeModel
from config import config
from datetime import datetime
from sqlalchemy import text
import os


def create_app(config_name=None):
    """Application factory function to create and configure the Flask app"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize database
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_question_types()
        # Ensure image upload directory exists
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(os.path.join(upload_folder, 'images'), exist_ok=True)

    # Register blueprints
    app.register_blueprint(bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(kg_bp)

    return app


def _migrate_db():
    """Add new columns to existing tables if they don't exist (idempotent)."""
    new_cols = [
        ('exams', 'subject', 'VARCHAR(128)'),
        ('exams', 'is_confirmed', 'BOOLEAN DEFAULT 0'),
        ('exams', 'confirmed_at', 'DATETIME'),
    ]
    with db.engine.connect() as conn:
        for table, col, col_def in new_cols:
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {col_def}'))
                conn.commit()
            except Exception:
                pass  # Column already exists


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
