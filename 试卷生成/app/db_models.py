from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

# Many-to-many association table: exam_questions
exam_questions = db.Table('exam_questions',
    db.Column('exam_id', db.String(64), db.ForeignKey('exams.exam_id'), primary_key=True),
    db.Column('question_id', db.String(64), db.ForeignKey('questions.question_id'), primary_key=True),
    db.Column('position', db.Integer)  # Question order within exam
)


class QuestionTypeModel(db.Model):
    __tablename__ = 'question_types'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    label = db.Column(db.String(64), nullable=False)
    has_options = db.Column(db.Boolean, default=False)
    is_builtin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'label': self.label,
            'has_options': self.has_options,
            'is_builtin': self.is_builtin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class QuestionModel(db.Model):
    __tablename__ = 'questions'
    question_id = db.Column(db.String(64), primary_key=True)
    question_type = db.Column(db.String(32), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text, default='[]')          # JSON string
    answer = db.Column(db.Text)
    reference_answer = db.Column(db.Text)
    explanation = db.Column(db.Text)
    content_en = db.Column(db.Text, nullable=True)
    options_en = db.Column(db.Text, nullable=True)          # JSON string
    subject = db.Column(db.String(128), nullable=True, index=True)   # 考试科目
    knowledge_point = db.Column(db.String(256), nullable=True)
    tags = db.Column(db.String(512), nullable=True)         # comma-separated
    difficulty = db.Column(db.String(32), nullable=True)    # easy/medium/hard
    language = db.Column(db.String(10), default='zh', index=True)
    metadata_json = db.Column(db.Text, default='{}')    # JSON string
    is_used = db.Column(db.Boolean, default=False, index=True)
    used_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'question_id': self.question_id,
            'question_type': self.question_type,
            'content': self.content,
            'options': json.loads(self.options) if self.options else [],
            'answer': self.answer,
            'reference_answer': self.reference_answer,
            'explanation': self.explanation,
            'content_en': self.content_en,
            'options_en': json.loads(self.options_en) if self.options_en else [],
            'subject': self.subject,
            'knowledge_point': self.knowledge_point,
            'tags': self.tags,
            'difficulty': self.difficulty,
            'language': self.language,
            'metadata': json.loads(self.metadata_json) if self.metadata_json else {},
            'is_used': self.is_used,
            'used_date': self.used_date.isoformat() if self.used_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CourseSettingsModel(db.Model):
    __tablename__ = 'course_settings'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_name = db.Column(db.String(256), default='')
    course_code = db.Column(db.String(64), default='')
    exam_format = db.Column(db.String(32), default='')     # 开卷/闭卷
    exam_method = db.Column(db.String(32), default='')     # 笔试/口试
    target_audience = db.Column(db.String(256), default='')
    institution_name = db.Column(db.String(256), default='')   # 学校/机构名称
    semester_info = db.Column(db.String(256), default='')      # 学期信息，如 "2023–2024学年第1学期"
    exam_title = db.Column(db.String(256), default='期末考试试卷')  # 考试标题
    paper_label = db.Column(db.String(16), default='A')        # 试卷标签，如 A/B
    updated_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'course_name': self.course_name or '',
            'course_code': self.course_code or '',
            'exam_format': self.exam_format or '',
            'exam_method': self.exam_method or '',
            'target_audience': self.target_audience or '',
            'institution_name': self.institution_name or '',
            'semester_info': self.semester_info or '',
            'exam_title': self.exam_title or '期末考试试卷',
            'paper_label': self.paper_label or 'A',
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ExamModel(db.Model):
    __tablename__ = 'exams'
    exam_id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    config = db.Column(db.Text, default='{}')    # JSON string
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

    questions = db.relationship(
        'QuestionModel',
        secondary=exam_questions,
        backref=db.backref('exams', lazy='dynamic'),
        lazy='dynamic'
    )

    def to_dict(self):
        # Get questions ordered by position
        ordered_questions = db.session.query(QuestionModel).join(
            exam_questions,
            QuestionModel.question_id == exam_questions.c.question_id
        ).filter(
            exam_questions.c.exam_id == self.exam_id
        ).order_by(exam_questions.c.position).all()

        return {
            'exam_id': self.exam_id,
            'name': self.name,
            'questions': [q.to_dict() for q in ordered_questions],
            'config': json.loads(self.config) if self.config else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_ordered_questions(self):
        """Get questions ordered by position."""
        return db.session.query(QuestionModel).join(
            exam_questions,
            QuestionModel.question_id == exam_questions.c.question_id
        ).filter(
            exam_questions.c.exam_id == self.exam_id
        ).order_by(exam_questions.c.position).all()

    def calculate_total_score(self):
        """Calculate the total score of the exam based on config."""
        total_score = 0
        config = json.loads(self.config) if self.config else {}
        if config:
            for q in self.get_ordered_questions():
                question_config = config.get(q.question_type, {})
                points_per_question = question_config.get('points', 0)
                total_score += points_per_question
        return total_score
