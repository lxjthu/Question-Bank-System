from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import uuid
import os
import base64
import hashlib
from cryptography.fernet import Fernet

db = SQLAlchemy()


def _get_fernet():
    """获取 Fernet 实例，密钥来自 FERNET_KEY 环境变量，不存在则从 SECRET_KEY 派生。"""
    key = os.environ.get('FERNET_KEY')
    if not key:
        secret = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_api_key(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


# ──────────────────────────────────────────────────────────────────────────────
# 用户 & 权限模型
# ──────────────────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id               = db.Column(db.Integer, primary_key=True)
    username         = db.Column(db.String(64), unique=True, nullable=False)
    email            = db.Column(db.String(128), unique=True, nullable=True)
    password_hash    = db.Column(db.String(256), nullable=False)
    role             = db.Column(db.String(16), default='user')   # admin/user/guest
    api_key_encrypted = db.Column(db.Text, nullable=True)         # Fernet 加密
    invited_by       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime, default=datetime.now)
    last_login       = db.Column(db.DateTime, nullable=True)

    def set_api_key(self, plaintext: str):
        self.api_key_encrypted = encrypt_api_key(plaintext)

    def get_api_key(self) -> str | None:
        if not self.api_key_encrypted:
            return None
        try:
            return decrypt_api_key(self.api_key_encrypted)
        except Exception:
            return None

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'has_api_key': bool(self.api_key_encrypted),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class InviteCode(db.Model):
    __tablename__ = 'invite_codes'
    id          = db.Column(db.Integer, primary_key=True)
    code        = db.Column(db.String(32), unique=True, nullable=False)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    used_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    used_at     = db.Column(db.DateTime, nullable=True)
    expires_at  = db.Column(db.DateTime, nullable=True)
    max_uses    = db.Column(db.Integer, default=1)
    use_count   = db.Column(db.Integer, default=0)
    note        = db.Column(db.String(256), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.now)

    def is_valid(self) -> bool:
        if self.use_count >= self.max_uses:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'created_by': self.created_by,
            'used_by': self.used_by,
            'use_count': self.use_count,
            'max_uses': self.max_uses,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'note': self.note,
            'is_valid': self.is_valid(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Team(db.Model):
    __tablename__ = 'teams'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, default='')
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.now)
    members     = db.relationship('TeamMember', backref='team', lazy='dynamic')

    def to_dict(self, include_members=False):
        d = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_members:
            d['members'] = [m.to_dict() for m in self.members]
        return d


class TeamMember(db.Model):
    __tablename__ = 'team_members'
    id        = db.Column(db.Integer, primary_key=True)
    team_id   = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role      = db.Column(db.String(16), default='member')   # admin/member
    joined_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('team_id', 'user_id'),)

    def to_dict(self):
        return {
            'team_id': self.team_id,
            'user_id': self.user_id,
            'role': self.role,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
        }

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
    # ── 多用户隔离 ──
    owner_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    visibility = db.Column(db.String(16), default='private', index=True)  # private/team/guest_preview
    team_id    = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
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
    imported_at = db.Column(db.DateTime, nullable=True)
    interview_pool = db.Column(db.Boolean, default=False)   # 已加入某面试题库池
    interview_set  = db.Column(db.Boolean, default=False)   # 已被分配进某套题
    interview_used = db.Column(db.Boolean, default=False)   # 所在套题已被标记使用
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
            'imported_at': self.imported_at.strftime('%Y-%m-%d %H:%M') if self.imported_at else None,
            'interview_pool': bool(self.interview_pool),
            'interview_set':  bool(self.interview_set),
            'interview_used': bool(self.interview_used),
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


class QuestionImageModel(db.Model):
    """Stores metadata for images embedded in question fields (content/reference_answer/explanation).
    Actual image bytes are stored on disk in uploads/images/.
    """
    __tablename__ = 'question_images'
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    image_id     = db.Column(db.String(64), unique=True, nullable=False,
                             default=lambda: 'img_' + uuid.uuid4().hex[:8])
    question_id  = db.Column(db.String(64), db.ForeignKey('questions.question_id'),
                             nullable=True, index=True)
    field        = db.Column(db.String(32))          # 'content' | 'reference_answer' | 'explanation'
    filename     = db.Column(db.String(256), nullable=False)   # basename on disk
    original_name = db.Column(db.String(256))
    content_type = db.Column(db.String(64), default='image/png')
    file_size    = db.Column(db.Integer)
    created_at   = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'image_id': self.image_id,
            'question_id': self.question_id,
            'field': self.field,
            'filename': self.filename,
            'content_type': self.content_type,
            'url': f'/api/images/{self.image_id}',
        }


class ExamModel(db.Model):
    __tablename__ = 'exams'
    exam_id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    # ── 多用户隔离 ──
    owner_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    visibility = db.Column(db.String(16), default='private', index=True)
    team_id    = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    config = db.Column(db.Text, default='{}')    # JSON string
    subject = db.Column(db.String(128), nullable=True)   # 组卷时选择的科目
    is_confirmed = db.Column(db.Boolean, default=False)  # 是否已最终确认
    confirmed_at = db.Column(db.DateTime, nullable=True) # 最终确认时间
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
            'subject': self.subject or '',
            'is_confirmed': self.is_confirmed or False,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
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
