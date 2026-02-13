from flask import Flask
from app.routes import bp
from app.db_models import db, QuestionTypeModel
from config import config
from datetime import datetime
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
        _seed_question_types()

    # Register blueprints
    app.register_blueprint(bp)

    return app


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
