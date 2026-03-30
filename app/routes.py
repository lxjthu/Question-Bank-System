from flask import Blueprint, request, jsonify, render_template, send_file
from app.db_models import db, QuestionModel, ExamModel, QuestionTypeModel, CourseSettingsModel, exam_questions, QuestionImageModel
from app.utils import allowed_file, generate_word_template, export_exam_to_word, save_image_file, delete_question_images, _IMAGES_DIR, _associate_images_in_html
from app.auth_routes import login_required, guest_readonly, get_current_user
import os
import json
import uuid
from datetime import datetime

bp = Blueprint('main', __name__)


# ─── 可见性过滤辅助函数 ────────────────────────────────────────────────────────

def _visible_q_filter(user):
    """返回当前用户可见的题目 OR 条件（用于 .filter()）。"""
    from app.db_models import TeamMember
    if user.role == 'admin':
        return db.true()   # admin 可见全部
    my_team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()]
    conds = [
        QuestionModel.owner_id == user.id,
        QuestionModel.visibility == 'guest_preview',
    ]
    if my_team_ids:
        conds.append(db.and_(
            QuestionModel.visibility == 'team',
            QuestionModel.team_id.in_(my_team_ids)
        ))
    return db.or_(*conds)


def _visible_e_filter(user):
    """返回当前用户可见的试卷 OR 条件。"""
    from app.db_models import TeamMember
    if user.role == 'admin':
        return db.true()
    my_team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()]
    conds = [
        ExamModel.owner_id == user.id,
        ExamModel.visibility == 'guest_preview',
    ]
    if my_team_ids:
        conds.append(db.and_(
            ExamModel.visibility == 'team',
            ExamModel.team_id.in_(my_team_ids)
        ))
    return db.or_(*conds)


def _can_write_question(question, user) -> bool:
    """是否有编辑/删除该题的权限（owner 或 admin）。"""
    return user.role == 'admin' or question.owner_id == user.id


def _can_write_exam(exam, user) -> bool:
    return user.role == 'admin' or exam.owner_id == user.id

import re as _re


# ─── 语言检测辅助函数 ──────────────────────────────────────────────────────────

def _detect_language(content: str, content_en: str | None) -> str:
    """根据 content 文本和 content_en 字段判断题目语言。

    规则：
    - content 去除 HTML 后无中文字符 → 纯英文题目 → 'en'
      （即使 AI 把英文同时写入了 content_en，也不误判为双语）
    - content 含中文 + content_en 非空 → 中英双语 → 'both'
    - content 含中文 + 无 content_en → 纯中文 → 'zh'
    """
    plain = _re.sub(r'<[^>]+>', ' ', content or '')
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in plain)
    if not has_chinese:
        return 'en'
    return 'both' if content_en else 'zh'


# ─── 查重辅助函数 ────────────────────────────────────────────────────────────

def _ngram_set(text: str, n: int = 2) -> set:
    """生成字符级 n-gram 集合，用于相似度计算。去除所有空白后处理。"""
    t = ''.join(text.split())
    return {t[i:i+n] for i in range(len(t) - n + 1)}


def _is_similar(new_text: str, existing_ngrams: list, threshold: float = 0.7) -> bool:
    """Jaccard 相似度 >= threshold 则认为重复。"""
    ng_new = _ngram_set(new_text)
    if not ng_new:
        return False
    for ng_ex in existing_ngrams:
        inter = len(ng_new & ng_ex)
        union = len(ng_new | ng_ex)
        if union > 0 and inter / union >= threshold:
            return True
    return False


@bp.route('/')
def index():
    """Main page route"""
    return render_template('index.html')


# ─── Image Storage Routes ───────────────────────────────────────────────────

@bp.route('/api/images/upload', methods=['POST'])
def upload_image():
    """Upload an image file and return {image_id, url}.

    Called by the Quill editor's custom image handler.
    The image is saved before the question is saved, so question_id may be null
    initially; it is later associated via _associate_images_in_html().
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f or f.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    content_type = f.content_type or 'image/png'
    image_bytes = f.read()
    if len(image_bytes) == 0:
        return jsonify({'error': 'Empty file'}), 400

    try:
        image_id = save_image_file(image_bytes, content_type, question_id=None)
        db.session.commit()
        return jsonify({'image_id': image_id, 'url': f'/api/images/{image_id}'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/images/<image_id>', methods=['GET'])
def serve_image(image_id):
    """Serve an image file by its image_id."""
    record = QuestionImageModel.query.filter_by(image_id=image_id).first()
    if not record:
        return jsonify({'error': 'Image not found'}), 404
    filepath = os.path.join(_IMAGES_DIR, record.filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Image file missing'}), 404
    return send_file(filepath, mimetype=record.content_type)


@bp.route('/api/images/<image_id>', methods=['DELETE'])
def delete_image(image_id):
    """Delete an image file and its DB record."""
    record = QuestionImageModel.query.filter_by(image_id=image_id).first()
    if not record:
        return jsonify({'error': 'Image not found'}), 404
    try:
        os.remove(os.path.join(_IMAGES_DIR, record.filename))
    except OSError:
        pass
    db.session.delete(record)
    db.session.commit()
    return jsonify({'message': 'Image deleted'})


# ─── Question Bank Management Routes ────────────────────────────────────────
@bp.route('/api/questions', methods=['GET'])
@login_required
def get_questions():
    """Get all questions or search questions"""
    from datetime import timedelta
    user = get_current_user()
    keyword = request.args.get('keyword', '')
    question_type = request.args.get('type', '')
    language = request.args.get('language', '')
    difficulty = request.args.get('difficulty', '')
    knowledge_point = request.args.get('knowledge_point', '')
    is_used = request.args.get('is_used', '')
    subject = request.args.get('subject', '')
    imported_after = request.args.get('imported_after', '').strip()
    imported_before = request.args.get('imported_before', '').strip()
    imported_only = request.args.get('imported_only', '')

    query = QuestionModel.query.filter(_visible_q_filter(user))

    if keyword:
        query = query.filter(QuestionModel.content.contains(keyword))
    if question_type:
        query = query.filter_by(question_type=question_type)
    if language:
        query = query.filter_by(language=language)
    if difficulty:
        query = query.filter_by(difficulty=difficulty)
    if knowledge_point:
        query = query.filter(QuestionModel.knowledge_point.contains(knowledge_point))
    if is_used == '1':
        query = query.filter_by(is_used=True)
    elif is_used == '0':
        query = query.filter_by(is_used=False)
    if subject:
        query = query.filter_by(subject=subject)
    if imported_after:
        try:
            dt = datetime.strptime(imported_after, '%Y-%m-%d')
            query = query.filter(QuestionModel.imported_at >= dt)
        except ValueError:
            pass
    if imported_before:
        try:
            dt = datetime.strptime(imported_before, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(QuestionModel.imported_at < dt)
        except ValueError:
            pass
    if imported_only == '1':
        query = query.filter(QuestionModel.imported_at.isnot(None))

    questions = query.all()
    return jsonify([q.to_dict() for q in questions])


@bp.route('/api/questions/count', methods=['GET'])
@login_required
def count_questions():
    """返回满足筛选条件的题目数量（用于组卷预估）。"""
    from datetime import timedelta
    subject = request.args.get('subject', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    kp = request.args.get('knowledge_point', '').strip()
    tags_str = request.args.get('tags', '').strip()
    is_used = request.args.get('is_used', '')
    language = request.args.get('language', '').strip()

    user = get_current_user()
    q = QuestionModel.query.filter(_visible_q_filter(user))
    if subject:
        q = q.filter_by(subject=subject)
    if difficulty:
        q = q.filter_by(difficulty=difficulty)
    if kp:
        q = q.filter(QuestionModel.knowledge_point.contains(kp))
    if tags_str:
        tags_list = [t.strip() for t in tags_str.split(',') if t.strip()]
        if tags_list:
            q = q.filter(db.or_(*[QuestionModel.tags.contains(t) for t in tags_list]))
    if is_used == '0':
        q = q.filter_by(is_used=False)
    elif is_used == '1':
        q = q.filter_by(is_used=True)
    if language:
        q = q.filter_by(language=language)
    return jsonify({'count': q.count()})


@bp.route('/api/questions/subjects', methods=['GET'])
@login_required
def get_subjects():
    """Get all distinct subject values from the question bank"""
    user = get_current_user()
    rows = db.session.query(QuestionModel.subject).filter(
        _visible_q_filter(user),
        QuestionModel.subject.isnot(None),
        QuestionModel.subject != ''
    ).distinct().all()
    subjects = sorted([r[0] for r in rows if r[0]])
    return jsonify(subjects)


@bp.route('/api/questions', methods=['POST'])
@login_required
@guest_readonly
def add_question():
    """Add a new question"""
    user = get_current_user()
    data = request.json
    now = datetime.now()

    content_en = data.get('content_en')
    options_en = data.get('options_en')
    # Use explicitly provided language; if not provided, auto-detect from content
    if 'language' in data and data['language']:
        language = data['language']
    else:
        language = _detect_language(data.get('content', ''), content_en)

    question = QuestionModel(
        question_id=data.get('question_id') or str(uuid.uuid4()),
        question_type=data.get('question_type'),
        content=data.get('content'),
        options=json.dumps(data.get('options', []), ensure_ascii=False),
        answer=data.get('answer'),
        reference_answer=data.get('reference_answer'),
        explanation=data.get('explanation'),
        content_en=content_en,
        options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
        subject=data.get('subject') or None,
        knowledge_point=data.get('knowledge_point'),
        tags=data.get('tags'),
        difficulty=data.get('difficulty'),
        language=language,
        metadata_json=json.dumps(data.get('metadata', {}), ensure_ascii=False),
        owner_id=user.id,
        visibility='private',
        created_at=now,
        updated_at=now,
    )
    db.session.add(question)
    try:
        db.session.commit()
        # Associate any images uploaded before the question was saved
        html_fields = [question.content, question.reference_answer, question.explanation]
        for html in html_fields:
            _associate_images_in_html(html, question.question_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Question with this ID already exists'}), 400
    return jsonify(question.to_dict()), 201


@bp.route('/api/questions/<question_id>', methods=['GET'])
@login_required
def get_question(question_id):
    """Get a specific question by ID"""
    user = get_current_user()
    question = QuestionModel.query.filter(
        QuestionModel.question_id == question_id,
        _visible_q_filter(user)
    ).first()
    if question:
        return jsonify(question.to_dict())
    return jsonify({'error': 'Question not found'}), 404


@bp.route('/api/questions/<question_id>', methods=['PUT'])
@login_required
@guest_readonly
def update_question(question_id):
    """Update a specific question"""
    user = get_current_user()
    question = db.session.get(QuestionModel, question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404
    if not _can_write_question(question, user):
        return jsonify({'error': '无权编辑他人题目'}), 403

    data = request.json
    question.content = data.get('content', question.content)
    if 'question_type' in data:
        question.question_type = data['question_type']
    if 'language' in data:
        question.language = data['language']
    if 'options' in data:
        question.options = json.dumps(data['options'], ensure_ascii=False)
    if 'answer' in data:
        question.answer = data['answer']
    if 'reference_answer' in data:
        question.reference_answer = data['reference_answer']
    if 'explanation' in data:
        question.explanation = data['explanation']
    if 'content_en' in data:
        question.content_en = data['content_en']
    if 'options_en' in data:
        question.options_en = json.dumps(data['options_en'], ensure_ascii=False) if data['options_en'] else None
    if 'subject' in data:
        question.subject = data['subject'] or None
    if 'knowledge_point' in data:
        question.knowledge_point = data['knowledge_point']
    if 'tags' in data:
        question.tags = data['tags']
    if 'difficulty' in data:
        question.difficulty = data['difficulty']
    # Auto-detect language when language field is not explicitly provided
    if 'language' not in data:
        question.language = _detect_language(question.content or '', question.content_en)
    question.updated_at = datetime.now()

    db.session.commit()
    # Associate any newly uploaded images in updated fields
    for html in [question.content, question.reference_answer, question.explanation]:
        _associate_images_in_html(html, question.question_id)
    db.session.commit()
    return jsonify(question.to_dict())


@bp.route('/api/questions/<question_id>', methods=['DELETE'])
@login_required
@guest_readonly
def delete_question(question_id):
    """Delete a specific question"""
    user = get_current_user()
    question = db.session.get(QuestionModel, question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404
    if not _can_write_question(question, user):
        return jsonify({'error': '无权删除他人题目'}), 403

    delete_question_images(question_id)
    db.session.delete(question)
    db.session.commit()
    return jsonify({'message': 'Question deleted successfully'})


@bp.route('/api/questions/batch-delete', methods=['POST'])
@login_required
@guest_readonly
def batch_delete_questions():
    """Delete multiple questions at once"""
    user = get_current_user()
    data = request.json
    question_ids = data.get('question_ids', [])

    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400

    # 非 admin 只能删自己的题目
    if user.role != 'admin':
        question_ids = [
            qid for qid in question_ids
            if QuestionModel.query.filter_by(question_id=qid, owner_id=user.id).first()
        ]

    for qid in question_ids:
        delete_question_images(qid)

    db.session.execute(
        exam_questions.delete().where(exam_questions.c.question_id.in_(question_ids))
    )
    deleted = QuestionModel.query.filter(QuestionModel.question_id.in_(question_ids)).delete(
        synchronize_session=False
    )
    db.session.commit()

    return jsonify({'message': f'{deleted} questions deleted successfully', 'deleted_count': deleted})


@bp.route('/api/questions/batch-update-type', methods=['POST'])
@login_required
@guest_readonly
def batch_update_question_type():
    """Change question_type for multiple questions at once"""
    user = get_current_user()
    data = request.json
    question_ids = data.get('question_ids', [])
    new_type = data.get('question_type', '')

    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400
    if not new_type:
        return jsonify({'error': 'No question_type provided'}), 400

    # Verify the target type exists and is accessible by current user
    qt = QuestionTypeModel.query.filter(
        QuestionTypeModel.name == new_type,
        db.or_(
            QuestionTypeModel.owner_id.is_(None),
            QuestionTypeModel.owner_id == user.id,
        )
    ).first()
    if not qt:
        return jsonify({'error': f'Question type "{new_type}" not found'}), 400

    now = datetime.now()
    q_filter = [QuestionModel.question_id.in_(question_ids)]
    if user.role != 'admin':
        q_filter.append(QuestionModel.owner_id == user.id)
    updated = QuestionModel.query.filter(*q_filter).update({
        QuestionModel.question_type: new_type,
        QuestionModel.updated_at: now,
    }, synchronize_session=False)
    db.session.commit()

    return jsonify({'message': f'{updated} questions updated to "{new_type}"', 'updated_count': updated})


# ─── xlsx Export ────────────────────────────────────────────────────────────

_XLSX_MAX_LEN = 500

_XLSX_TYPE_MAP = {
    "单选": "单选题", "多选": "多选题", "是非": "判断题",
    "简答": "简答题", "简答>计算": "简答题", "简答>论述": "简答题", "简答>材料分析": "简答题",
}
_XLSX_SCORE_MAP = {
    "单选": 1.5, "多选": 2, "是非": 1,
    "简答": 5, "简答>计算": 5, "简答>论述": 5, "简答>材料分析": 5,
}
_XLSX_DIFFICULTY_MAP = {"easy": 2, "medium": 3, "hard": 4}

# ─── xlsx Import helpers ─────────────────────────────────────────────────────

_XLSX_TYPE_REVERSE = {
    "单选题": "单选", "多选题": "多选", "判断题": "是非",
    "简答题": "简答", "计算题": "简答>计算",
    "论述题": "简答>论述", "材料分析题": "简答>材料分析",
}

# 题型模糊匹配规则（用于自动识别常见变体）
_XLSX_TYPE_PATTERNS = {
    "单选": ["单选", "单选题", "单项选择", "单项选择题"],
    "多选": ["多选", "多选题", "多项选择", "多项选择题", "不定项选择"],
    "是非": ["判断", "判断题", "是非", "是非题", "对错题", "正确错误"],
    "简答": ["简答", "简答题", "问答题", "问答", "名词解释", "解释"],
    "简答>计算": ["计算", "计算题"],
    "简答>论述": ["论述", "论述题"],
    "简答>材料分析": ["材料分析", "材料分析题", "案例分析", "案例分析题", "分析题"],
}


def _match_question_type(raw_type: str, known_types: set) -> tuple:
    """
    匹配题型，返回 (matched_type, is_builtin, needs_create)
    - matched_type: 匹配到的题型名称
    - is_builtin: 是否是内置题型
    - needs_create: 是否需要创建新题型
    """
    if not raw_type:
        return None, False, False
    
    raw_clean = raw_type.strip()
    raw_lower = raw_clean.lower()
    
    # 1. 直接匹配已知题型（精确匹配）
    if raw_clean in known_types:
        return raw_clean, True, False
    
    # 2. 反向映射匹配（如 "单选题" -> "单选"）
    if raw_clean in _XLSX_TYPE_REVERSE:
        mapped = _XLSX_TYPE_REVERSE[raw_clean]
        return mapped, True, False
    
    # 3. 模糊匹配内置题型模式
    for std_type, patterns in _XLSX_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in raw_lower or raw_lower in pattern:
                # 如果标准题型在已知类型中，使用它
                if std_type in known_types:
                    return std_type, True, False
                # 否则尝试找到包含该标准题型的层级题型
                for kt in known_types:
                    if std_type in kt:
                        return kt, True, False
    
    # 4. 尝试在已知类型中查找包含关系
    for kt in known_types:
        if raw_clean in kt or kt in raw_clean:
            return kt, True, False
    
    # 5. 无法匹配，需要创建新题型
    return raw_clean, False, True


def _ensure_question_type(type_name: str, user) -> tuple:
    """
    确保题型存在，如果不存在则创建新题型
    返回 (type_name, error_message)
    """
    from app.db_models import QuestionTypeModel
    
    if not type_name:
        return None, "题型名称为空"
    
    type_name = type_name.strip()
    
    # 查找所有可见题型（内置 + 用户自定义）
    known_types = {
        qt.name for qt in QuestionTypeModel.query.filter(
            db.or_(
                QuestionTypeModel.owner_id.is_(None),
                QuestionTypeModel.owner_id == user.id,
            )
        ).all()
    }
    
    # 尝试匹配
    matched, is_builtin, needs_create = _match_question_type(type_name, known_types)
    
    if matched and not needs_create:
        return matched, None
    
    if needs_create:
        # 检查是否已存在同名自定义题型（避免重复创建）
        existing = QuestionTypeModel.query.filter(
            QuestionTypeModel.name == type_name,
            QuestionTypeModel.owner_id == user.id
        ).first()
        
        if existing:
            return type_name, None
        
        # 创建新题型
        # 判断是否需要有选项（根据题型名称关键词）
        has_options = any(kw in type_name.lower() for kw in 
                         ['选', '单选', '多选', '选择'])
        
        new_type = QuestionTypeModel(
            name=type_name,
            label=type_name,
            has_options=has_options,
            is_builtin=False,
            owner_id=user.id,
            created_at=datetime.now(),
        )
        db.session.add(new_type)
        try:
            db.session.commit()
            return type_name, None
        except Exception as e:
            db.session.rollback()
            return None, f"创建题型失败: {str(e)}"
    
    return type_name, None


def _xlsx_diff_from_num(n):
    """难度数字 1-5 → easy/medium/hard"""
    try:
        n = int(float(n))
    except (TypeError, ValueError):
        return "medium"
    if n <= 2:
        return "easy"
    if n == 3:
        return "medium"
    return "hard"


def _xlsx_parse_tags(tag_str):
    """'#知识点#标签1#标签2' → (knowledge_point, tags_str)"""
    if not tag_str:
        return None, None
    parts = [p.strip() for p in str(tag_str).split('#') if p.strip()]
    if not parts:
        return None, None
    kp = parts[0]
    tags = ','.join(parts[1:]) if len(parts) > 1 else None
    return kp, tags


def _xlsx_normalize_answer(q_type, raw_answer):
    """
    按题型规范化答案，返回 (answer, reference_answer)
    - 单选: 'D' → ('D', '')
    - 多选: 'A,B'/'A;B'/'AB' → ('AB', '')
    - 判断: 'true'/'正确' → ('正确', ''),  'false'/'错误' → ('错误', '')
    - 简答: 文本 → ('', 文本)
    """
    import re
    raw = (raw_answer or '').strip()
    if q_type == '单选':
        return raw.upper() if raw else '', ''
    if q_type == '多选':
        letters = re.findall(r'[A-Oa-o]', raw)
        return ''.join(l.upper() for l in letters), ''
    if q_type == '是非':
        if raw.lower() in ('true', '正确', '对', '是'):
            return '正确', ''
        if raw.lower() in ('false', '错误', '错', '否'):
            return '错误', ''
        return raw, ''
    # 简答类
    return '', raw


def _parse_xlsx_questions(file_path, user=None):
    """
    解析 xlsx 题库文件，兼容两种格式：
    - muban_zh.xlsx 导出格式（标题行在第3行，数据从第4行）
    - 外部题库格式（标题行在第1行，数据从第2行）
    
    支持自动匹配和创建新题型
    返回: (questions_list, errors_list, created_types_list)
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError('openpyxl 未安装，无法解析 xlsx 文件')

    wb = load_workbook(file_path, data_only=True)
    ws = wb.active

    # 自动检测标题行（找包含 "题干" 的行，最多扫描5行）
    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), 1):
        row_str = ' '.join(str(c or '') for c in row)
        if '题干' in row_str:
            header_row = i
            break

    if header_row is None:
        raise ValueError("未找到标题行（含'题干'的行），请检查文件格式是否为 muban_zh.xlsx 模板")

    data_start = header_row + 1
    questions = []
    errors = []
    created_types = []  # 记录新创建的题型
    
    # 获取当前用户可见的所有题型
    from app.db_models import QuestionTypeModel
    known_types = set()
    if user:
        known_types = {
            qt.name for qt in QuestionTypeModel.query.filter(
                db.or_(
                    QuestionTypeModel.owner_id.is_(None),
                    QuestionTypeModel.owner_id == user.id,
                )
            ).all()
        }

    for row_idx, row in enumerate(
        ws.iter_rows(min_row=data_start, values_only=True), data_start
    ):
        stem = str(row[7] or '').strip() if len(row) > 7 else ''
        if not stem:
            continue

        raw_type = str(row[1] or '').strip()
        
        # 使用新的题型匹配逻辑
        q_type, is_builtin, needs_create = _match_question_type(raw_type, known_types)
        
        if not q_type:
            errors.append(f"第{row_idx}行：题型为空，已跳过")
            continue
        
        # 如果需要创建新题型且提供了用户信息
        if needs_create and user:
            final_type, error = _ensure_question_type(raw_type, user)
            if error:
                errors.append(f"第{row_idx}行：题型 '{raw_type}' 处理失败: {error}")
                continue
            q_type = final_type
            if q_type not in known_types:
                known_types.add(q_type)
                created_types.append(q_type)
        elif needs_create and not user:
            # 没有用户信息，使用原始题型名并记录警告
            q_type = raw_type
            errors.append(f"第{row_idx}行：题型 '{raw_type}' 未匹配到已知题型，将使用原名称导入")

        difficulty = _xlsx_diff_from_num(row[3] if len(row) > 3 else None)
        tag_str = str(row[5] or '').strip() if len(row) > 5 else ''
        kp, tags = _xlsx_parse_tags(tag_str)
        raw_answer = str(row[8] or '').strip() if len(row) > 8 else ''
        explanation = str(row[9] or '').strip() if len(row) > 9 else ''

        answer, reference_answer = _xlsx_normalize_answer(q_type, raw_answer)

        options = []
        for ci in range(10, 25):
            val = row[ci] if ci < len(row) else None
            if val is not None and str(val).strip():
                options.append(str(val).strip())

        questions.append({
            'type': q_type,
            'content': stem,
            'options': options,
            'answer': answer,
            'reference_answer': reference_answer,
            'explanation': explanation,
            'knowledge_point': kp,
            'tags': tags,
            'difficulty': difficulty,
        })

    return questions, errors, created_types


# ─── xlsx Export ─────────────────────────────────────────────────────────────

def _xlsx_strip_html(text):
    import re
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').strip()


def _xlsx_convert_answer(q_type, answer, reference_answer):
    if q_type == "是非":
        return "true" if answer == "正确" else ("false" if answer == "错误" else (answer or ""))
    if q_type == "多选":
        return ";".join(list(answer.strip())) if answer else ""
    if q_type in ("简答", "简答>计算", "简答>论述", "简答>材料分析"):
        return _xlsx_strip_html(reference_answer or answer or "")
    return answer or ""


def _xlsx_check_fields(q):
    """返回该题超出 _XLSX_MAX_LEN 的字段列表，格式: [{'name': str, 'length': int}]"""
    options = json.loads(q.options) if q.options else []
    stem    = _xlsx_strip_html(q.content)
    answer  = _xlsx_convert_answer(q.question_type, q.answer, q.reference_answer)
    answer  = answer.replace('\n', ' ').replace('\r', '')
    explanation = _xlsx_strip_html(q.explanation or "")

    fields = {"题干": stem, "答案": answer, "解析": explanation}
    for i, opt in enumerate(options[:15]):
        fields[f"选项{chr(65+i)}"] = _xlsx_strip_html(opt)

    return [{"name": k, "length": len(v)} for k, v in fields.items() if len(v) > _XLSX_MAX_LEN]


@bp.route('/api/questions/check-export', methods=['POST'])
@login_required
def check_export_xlsx():
    """检查选中题目中哪些字段超过500字符，返回警告列表"""
    data = request.json or {}
    question_ids = data.get('question_ids', [])
    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400

    questions = QuestionModel.query.filter(QuestionModel.question_id.in_(question_ids)).all()
    warnings = []
    for q in questions:
        over = _xlsx_check_fields(q)
        if over:
            preview = _xlsx_strip_html(q.content or "")[:30]
            warnings.append({
                "question_id": q.question_id,
                "question_type": q.question_type,
                "content_preview": preview,
                "fields": over,
            })
    return jsonify({"warnings": warnings})


@bp.route('/api/questions/export-xlsx', methods=['POST'])
@login_required
def export_xlsx():
    """将选中题目导出为 xlsx 文件，skip_ids 中的题目跳过"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return jsonify({'error': 'openpyxl 未安装'}), 500

    import shutil, tempfile
    data = request.json or {}
    question_ids = data.get('question_ids', [])
    skip_ids     = set(data.get('skip_ids', []))
    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400

    # 保持前端传入的顺序
    id_order = {qid: i for i, qid in enumerate(question_ids)}
    questions = QuestionModel.query.filter(QuestionModel.question_id.in_(question_ids)).all()
    questions.sort(key=lambda q: id_order.get(q.question_id, 9999))

    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'muban_zh.xlsx')
    if not os.path.exists(template_path):
        return jsonify({'error': '模板文件 muban_zh.xlsx 不存在'}), 500

    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    tmp.close()
    shutil.copy(template_path, tmp.name)

    wb = load_workbook(tmp.name)
    ws = wb.active
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
        for cell in row:
            cell.value = None

    def cap(v):
        return v[:_XLSX_MAX_LEN] if isinstance(v, str) else v

    row_idx = 4
    seq = 0
    for q in questions:
        if q.question_id in skip_ids:
            continue
        seq += 1
        q_type  = q.question_type
        options = json.loads(q.options) if q.options else []
        stem    = _xlsx_strip_html(q.content)
        answer  = _xlsx_convert_answer(q_type, q.answer, q.reference_answer)
        answer  = answer.replace('\n', ' ').replace('\r', '')
        explanation = _xlsx_strip_html(q.explanation or "")
        tag_parts = []
        if q.knowledge_point:
            tag_parts.append(q.knowledge_point.strip())
        if q.tags:
            for t in q.tags.split(","):
                t = t.strip()
                if t and t not in tag_parts:
                    tag_parts.append(t)
        tags_val = "".join(f"#{p}" for p in tag_parts[:3])

        ws.cell(row=row_idx, column=1).value  = str(seq)
        ws.cell(row=row_idx, column=2).value  = _XLSX_TYPE_MAP.get(q_type, "简答题")
        ws.cell(row=row_idx, column=3).value  = _XLSX_SCORE_MAP.get(q_type, 2)
        ws.cell(row=row_idx, column=4).value  = _XLSX_DIFFICULTY_MAP.get(q.difficulty, 3)
        ws.cell(row=row_idx, column=5).value  = "仅自己"
        ws.cell(row=row_idx, column=6).value  = tags_val
        ws.cell(row=row_idx, column=8).value  = cap(stem)
        ws.cell(row=row_idx, column=9).value  = cap(answer)
        ws.cell(row=row_idx, column=10).value = cap(explanation)
        for i, opt in enumerate(options[:15]):
            ws.cell(row=row_idx, column=11+i).value = cap(_xlsx_strip_html(opt))
        row_idx += 1

    wb.save(tmp.name)
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@bp.route('/api/questions/import', methods=['POST'])
@login_required
@guest_readonly
def import_questions():
    """Import questions from a file (Word or CSV)"""
    _import_user = get_current_user()
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file and allowed_file(file.filename):
        try:
            # Save the uploaded file temporarily
            temp_filename = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
            file_path = os.path.join('temp', temp_filename)

            # Create temp directory if it doesn't exist
            os.makedirs('temp', exist_ok=True)

            file.save(file_path)

            # Read subject from form field
            import_subject = request.form.get('subject') or None

            # Build a set of existing content for deduplication (trimmed)
            # 只对当前用户自己的题目去重，避免跨用户误判重复
            _user_q = db.session.query(QuestionModel.content).filter_by(owner_id=_import_user.id)
            existing_contents = set(
                row[0].strip()
                for row in _user_q.all()
                if row[0]
            )

            # 新增：构建库内题目的 n-gram 列表，用于相似度查重（仅取前200字）
            existing_ngrams = [
                _ngram_set((row[0] or '')[:200])
                for row in _user_q.all()
                if row[0]
            ]

            questions_data = []
            models = []
            skipped = 0

            # Parse .docx using rich-content importer (supports images + tables)
            if file.filename.lower().endswith('.docx'):
                from app.docx_importer import parse_docx_with_rich_content

                # Collect known question type names for marker validation（内置 + 当前用户）
                known_types = {
                    qt.name for qt in QuestionTypeModel.query.filter(
                        db.or_(
                            QuestionTypeModel.owner_id.is_(None),
                            QuestionTypeModel.owner_id == _import_user.id,
                        )
                    ).all()
                }

                # Wrapper: save_image_fn(bytes, content_type) -> image_id
                def _save_img_fn(image_bytes, content_type):
                    return save_image_file(image_bytes, content_type, question_id=None)

                questions_data = parse_docx_with_rich_content(
                    file_path, _save_img_fn, known_types
                )

                now = datetime.now()
                for i, q_data in enumerate(questions_data):
                    content_text = (q_data.get('content') or '').strip()
                    if content_text in existing_contents:
                        skipped += 1
                        continue
                    if _is_similar(content_text[:200], existing_ngrams):
                        skipped += 1
                        continue
                    existing_contents.add(content_text)  # prevent duplicates within this batch
                    existing_ngrams.append(_ngram_set(content_text[:200]))
                    question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_{i}"
                    content_en = q_data.get('content_en') or None
                    options_en = q_data.get('options_en') or []
                    lang = _detect_language(q_data.get('content', ''), content_en)
                    model = QuestionModel(
                        question_id=question_id,
                        question_type=q_data['type'],
                        content=q_data['content'],
                        options=json.dumps(q_data.get('options', []), ensure_ascii=False),
                        answer=q_data.get('answer'),
                        reference_answer=q_data.get('reference_answer', ''),
                        explanation=q_data.get('explanation', ''),
                        content_en=content_en,
                        options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
                        subject=import_subject or q_data.get('subject') or None,
                        knowledge_point=q_data.get('knowledge_point') or None,
                        tags=q_data.get('tags') or None,
                        difficulty=q_data.get('difficulty') or None,
                        language=lang,
                        metadata_json='{}',
                        imported_at=now,
                        created_at=now,
                        updated_at=now,
                        owner_id=_import_user.id,
                        visibility='private',
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

                # Associate any images embedded during parsing with their question IDs
                for model in models:
                    for field in ('content', 'reference_answer', 'explanation'):
                        html_val = getattr(model, field) or ''
                        if '/api/images/' in html_val:
                            _associate_images_in_html(html_val, model.question_id)
                db.session.commit()

            elif file.filename.lower().endswith('.txt'):
                from app.utils import parse_question_template
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                questions_data = parse_question_template(content)

                now = datetime.now()
                for i, q_data in enumerate(questions_data):
                    content_text = (q_data.get('content') or '').strip()
                    if content_text in existing_contents:
                        skipped += 1
                        continue
                    if _is_similar(content_text[:200], existing_ngrams):
                        skipped += 1
                        continue
                    existing_contents.add(content_text)  # prevent duplicates within this batch
                    existing_ngrams.append(_ngram_set(content_text[:200]))
                    question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_txt_{i}"
                    content_en = q_data.get('content_en') or None
                    options_en = q_data.get('options_en') or []
                    lang = _detect_language(q_data.get('content', ''), content_en)
                    model = QuestionModel(
                        question_id=question_id,
                        question_type=q_data['type'],
                        content=q_data['content'],
                        options=json.dumps(q_data.get('options', []), ensure_ascii=False),
                        answer=q_data.get('answer'),
                        reference_answer=q_data.get('reference_answer', ''),
                        explanation=q_data.get('explanation', ''),
                        content_en=content_en,
                        options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
                        subject=import_subject or q_data.get('subject') or None,
                        knowledge_point=q_data.get('knowledge_point') or None,
                        tags=q_data.get('tags') or None,
                        difficulty=q_data.get('difficulty') or None,
                        language=lang,
                        metadata_json='{}',
                        imported_at=now,
                        created_at=now,
                        updated_at=now,
                        owner_id=_import_user.id,
                        visibility='private',
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

            elif file.filename.lower().endswith('.xlsx'):
                questions_data, parse_errors, created_types = _parse_xlsx_questions(file_path, _import_user)
                failed = len(parse_errors)

                now = datetime.now()
                for i, q_data in enumerate(questions_data):
                    content_text = (q_data.get('content') or '').strip()
                    if content_text in existing_contents:
                        skipped += 1
                        continue
                    if _is_similar(content_text[:200], existing_ngrams):
                        skipped += 1
                        continue
                    existing_contents.add(content_text)
                    existing_ngrams.append(_ngram_set(content_text[:200]))
                    question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_xlsx_{i}"
                    model = QuestionModel(
                        question_id=question_id,
                        question_type=q_data['type'],
                        content=q_data['content'],
                        options=json.dumps(q_data.get('options', []), ensure_ascii=False),
                        answer=q_data.get('answer'),
                        reference_answer=q_data.get('reference_answer', ''),
                        explanation=q_data.get('explanation', ''),
                        content_en=None,
                        options_en=None,
                        subject=import_subject or None,
                        knowledge_point=q_data.get('knowledge_point') or None,
                        tags=q_data.get('tags') or None,
                        difficulty=q_data.get('difficulty') or None,
                        language=_detect_language(q_data.get('content', ''), None),
                        metadata_json='{}',
                        imported_at=now,
                        created_at=now,
                        updated_at=now,
                        owner_id=_import_user.id,
                        visibility='private',
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

                imported = len(models)
                os.remove(file_path) if os.path.exists(file_path) else None
                
                # 构建返回消息
                msg_parts = [f'成功导入 {imported} 题，跳过重复 {skipped} 题（含相似题）']
                if created_types:
                    msg_parts.append('，自动创建 {} 个新题型：{}'.format(len(created_types), '、'.join(created_types)))
                
                return jsonify({
                    'message': ''.join(msg_parts),
                    'imported': imported,
                    'count': imported,
                    'skipped': skipped,
                    'failed': failed,
                    'created_types': created_types,
                    'parse_errors': parse_errors[:10],  # 最多返回10条解析错误
                })

            # Clean up temporary files
            if os.path.exists(file_path):
                os.remove(file_path)

            imported = len(models)
            return jsonify({
                'message': f'成功导入 {imported} 题，跳过重复 {skipped} 题（含相似题）',
                'imported': imported,
                'count': imported,   # backward compat alias
                'skipped': skipped,
                'failed': 0,
            })
        except Exception as e:
            db.session.rollback()
            try:
                temp_filename = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                file_path = os.path.join('temp', temp_filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                csv_path = file_path.rsplit('.', 1)[0] + '.csv'
                if os.path.exists(csv_path):
                    os.remove(csv_path)
            except:
                pass

            return jsonify({'error': f'Import failed: {str(e)}'}), 500
    else:
        return jsonify({'error': 'Invalid file type'}), 400


@bp.route('/api/questions/import-text', methods=['POST'])
@login_required
@guest_readonly
def import_questions_from_text():
    """直接从文本导入题目（粘贴框功能）"""
    _import_user = get_current_user()
    data = request.json
    
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400
    
    text_content = data.get('text', '').strip()
    if not text_content:
        return jsonify({'error': 'Text content is empty'}), 400
    
    import_subject = data.get('subject') or None
    
    try:
        from app.utils import parse_question_template
        
        # Build a set of existing content for deduplication
        _user_q = db.session.query(QuestionModel.content).filter_by(owner_id=_import_user.id)
        existing_contents = set(
            row[0].strip()
            for row in _user_q.all()
            if row[0]
        )
        
        # Build n-gram list for similarity check
        existing_ngrams = [
            _ngram_set((row[0] or '')[:200])
            for row in _user_q.all()
            if row[0]
        ]
        
        questions_data = parse_question_template(text_content)
        models = []
        skipped = 0
        
        now = datetime.now()
        for i, q_data in enumerate(questions_data):
            content_text = (q_data.get('content') or '').strip()
            if not content_text:
                continue
            if content_text in existing_contents:
                skipped += 1
                continue
            if _is_similar(content_text[:200], existing_ngrams):
                skipped += 1
                continue
            existing_contents.add(content_text)
            existing_ngrams.append(_ngram_set(content_text[:200]))
            
            question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_txt_{i}"
            content_en = q_data.get('content_en') or None
            options_en = q_data.get('options_en') or []
            lang = _detect_language(q_data.get('content', ''), content_en)
            
            model = QuestionModel(
                question_id=question_id,
                question_type=q_data['type'],
                content=q_data['content'],
                options=json.dumps(q_data.get('options', []), ensure_ascii=False),
                answer=q_data.get('answer'),
                reference_answer=q_data.get('reference_answer', ''),
                explanation=q_data.get('explanation', ''),
                content_en=content_en,
                options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
                subject=import_subject or q_data.get('subject') or None,
                knowledge_point=q_data.get('knowledge_point') or None,
                tags=q_data.get('tags') or None,
                difficulty=q_data.get('difficulty') or None,
                language=lang,
                metadata_json='{}',
                imported_at=now,
                created_at=now,
                updated_at=now,
                owner_id=_import_user.id,
                visibility='private',
            )
            models.append(model)
        
        db.session.add_all(models)
        db.session.commit()
        
        # Associate any images with their question IDs
        for model in models:
            for field in ('content', 'reference_answer', 'explanation'):
                html_val = getattr(model, field) or ''
                if '/api/images/' in html_val:
                    _associate_images_in_html(html_val, model.question_id)
        db.session.commit()
        
        imported = len(models)
        return jsonify({
            'message': f'成功导入 {imported} 题，跳过重复 {skipped} 题（含相似题）',
            'imported': imported,
            'count': imported,
            'skipped': skipped,
            'failed': 0,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Import failed: {str(e)}'}), 500


@bp.route('/api/questions/export', methods=['GET'])
@login_required
def export_questions():
    """Export questions to JSON or CSV"""
    export_format = request.args.get('format', 'json')

    questions = QuestionModel.query.all()

    if export_format == 'json':
        filename = f"question_bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'exports', filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        data = {
            'questions': [q.to_dict() for q in questions],
            'exported_at': datetime.now().isoformat()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return send_file(filepath, as_attachment=True)

    elif export_format == 'csv':
        filename = f"question_bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'exports', filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("ID,Type,Content,Options,Answer,Reference Answer,Explanation,Language\n")
            for q in questions:
                options_list = json.loads(q.options) if q.options else []
                options_str = "|".join(options_list)
                f.write(f"{q.question_id},{q.question_type},{q.content},{options_str},{q.answer},{q.reference_answer},{q.explanation},{q.language}\n")

        return send_file(filepath, as_attachment=True)

    else:
        return jsonify({'error': 'Invalid export format. Use json or csv.'}), 400


@bp.route('/api/export/full-xlsx', methods=['GET'])
@login_required
def export_full_xlsx():
    """将当前用户的全部题目、试卷、自定义题型导出为多 Sheet Excel"""
    try:
        import openpyxl
        from io import BytesIO
    except ImportError:
        return jsonify({'error': '缺少 openpyxl 依赖'}), 500

    user = get_current_user()
    wb = openpyxl.Workbook()

    # ── Sheet1：题目 ──────────────────────────────────────────────────────────
    ws_q = wb.active
    ws_q.title = '题目'
    q_headers = ['question_id', '题型', '科目', '难度', '语言', '题干', '选项(JSON)',
                 '答案', '参考答案', '解析', '英文题干', '英文选项(JSON)',
                 '知识点', '标签', '是否已用', '创建时间']
    ws_q.append(q_headers)
    questions = QuestionModel.query.filter_by(owner_id=user.id).order_by(QuestionModel.created_at).all()
    for q in questions:
        ws_q.append([
            q.question_id, q.question_type, q.subject or '', q.difficulty or '',
            q.language or 'zh', q.content or '',
            q.options or '[]',
            q.answer or '', q.reference_answer or '', q.explanation or '',
            q.content_en or '', q.options_en or '[]',
            q.knowledge_point or '', q.tags or '',
            '是' if q.is_used else '否',
            q.created_at.strftime('%Y-%m-%d %H:%M') if q.created_at else '',
        ])
    # 列宽
    for col, width in zip(['A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P'],
                          [20, 10, 12, 8, 6, 60, 20, 30, 40, 40, 60, 20, 20, 15, 6, 16]):
        ws_q.column_dimensions[col].width = width

    # ── Sheet2：试卷 ──────────────────────────────────────────────────────────
    ws_e = wb.create_sheet('试卷')
    e_headers = ['exam_id', '试卷名称', '科目', '是否已确认', '创建时间', '题目ID列表(逗号分隔)']
    ws_e.append(e_headers)
    exams = ExamModel.query.filter_by(owner_id=user.id).order_by(ExamModel.created_at).all()
    for e in exams:
        ordered_qs = e.get_ordered_questions()
        qids = ','.join(q.question_id for q in ordered_qs)
        ws_e.append([
            e.exam_id, e.name, e.subject or '',
            '是' if e.is_confirmed else '否',
            e.created_at.strftime('%Y-%m-%d %H:%M') if e.created_at else '',
            qids,
        ])
    for col, width in zip(['A','B','C','D','E','F'], [24, 40, 14, 8, 16, 80]):
        ws_e.column_dimensions[col].width = width

    # ── Sheet3：自定义题型 ────────────────────────────────────────────────────
    ws_t = wb.create_sheet('自定义题型')
    ws_t.append(['题型名称', '显示标签', '是否有选项', '创建时间'])
    custom_types = QuestionTypeModel.query.filter_by(owner_id=user.id).order_by(QuestionTypeModel.created_at).all()
    for t in custom_types:
        ws_t.append([
            t.name, t.label, '是' if t.has_options else '否',
            t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
        ])
    for col, width in zip(['A','B','C','D'], [20, 20, 8, 16]):
        ws_t.column_dimensions[col].width = width

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'数据库备份_{user.username}_{date_str}.xlsx',
    )


@bp.route('/api/export/full-json', methods=['GET'])
@login_required
def export_full_json():
    """将当前用户的全部数据导出为 JSON 备份（可用于导入其他账号）"""
    import sqlite3 as _sqlite3
    from io import BytesIO
    user = get_current_user()

    questions = QuestionModel.query.filter_by(owner_id=user.id).order_by(QuestionModel.created_at).all()
    exams = ExamModel.query.filter_by(owner_id=user.id).order_by(ExamModel.created_at).all()
    custom_types = QuestionTypeModel.query.filter_by(owner_id=user.id).order_by(QuestionTypeModel.created_at).all()

    exam_list = []
    for e in exams:
        ordered_qs = e.get_ordered_questions()
        exam_list.append({
            'exam_id': e.exam_id,
            'name': e.name,
            'subject': e.subject or '',
            'config': json.loads(e.config) if e.config else {},
            'is_confirmed': bool(e.is_confirmed),
            'confirmed_at': e.confirmed_at.isoformat() if e.confirmed_at else None,
            'created_at': e.created_at.isoformat() if e.created_at else None,
            'question_ids': [q.question_id for q in ordered_qs],
        })

    # ── 知识图谱（ds_knowledge.db）────────────────────────────────────────────
    kg_data = {'docs': [], 'chapters': [], 'kps': [], 'doc_refs': []}
    try:
        from app.rag_routes import _ds_db_path
        _db_path = _ds_db_path()
        if _db_path.exists():
            _conn_ds = _sqlite3.connect(str(_db_path))
            _conn_ds.row_factory = _sqlite3.Row
            try:
                _docs = _conn_ds.execute(
                    "SELECT doc_id, filename, subject, status, display_name, architecture_json "
                    "FROM ds_docs WHERE owner_id=?", (user.id,)
                ).fetchall()
                _doc_ids = [d['doc_id'] for d in _docs]
                kg_data['docs'] = [dict(d) for d in _docs]
                for _doc_id in _doc_ids:
                    for _ch in _conn_ds.execute(
                        "SELECT chapter_num, chapter_name, parent_chapter_num, parent_chapter_name, "
                        "section_name, raw_text FROM ds_chapters WHERE doc_id=?", (_doc_id,)
                    ).fetchall():
                        kg_data['chapters'].append({'doc_id': _doc_id, **dict(_ch)})
                    for _kp in _conn_ds.execute(
                        "SELECT chapter_name, chapter_num, kp_name, kp_content, relations_json, "
                        "teaching_focus, knowledge_type, cognitive_dimension, "
                        "section_name, sub_section_name FROM ds_kps WHERE doc_id=?", (_doc_id,)
                    ).fetchall():
                        kg_data['kps'].append({'doc_id': _doc_id, **dict(_kp)})
                    for _ref in _conn_ds.execute(
                        "SELECT chapter_num, ref_text FROM ds_doc_refs WHERE doc_id=?", (_doc_id,)
                    ).fetchall():
                        kg_data['doc_refs'].append({'doc_id': _doc_id, **dict(_ref)})
            finally:
                _conn_ds.close()
    except Exception:
        pass

    # ── 面试题库（主数据库）──────────────────────────────────────────────────────
    interview_data = {'pools': [], 'pool_questions': [], 'configs': [], 'sessions': [], 'sets': []}
    try:
        from sqlalchemy import text as _sa_text
        with db.engine.connect() as _conn_sql:
            _pool_rows = _conn_sql.execute(_sa_text(
                "SELECT id, pool_name, description, created_at FROM interview_pools WHERE owner_id=:uid"
            ), {'uid': user.id}).fetchall()
            _pool_ids = [r[0] for r in _pool_rows]
            interview_data['pools'] = [
                {'id': r[0], 'pool_name': r[1], 'description': r[2] or '', 'created_at': str(r[3] or '')}
                for r in _pool_rows
            ]

            _sess_rows = _conn_sql.execute(_sa_text(
                "SELECT id, pool_id, config_id, session_name, interview_count, sets_multiplier, "
                "score_per_slot_json, created_at FROM interview_sessions WHERE owner_id=:uid"
            ), {'uid': user.id}).fetchall()
            _session_ids = [r[0] for r in _sess_rows]
            interview_data['sessions'] = [
                {'id': r[0], 'pool_id': r[1], 'config_id': r[2], 'session_name': r[3],
                 'interview_count': r[4], 'sets_multiplier': r[5],
                 'score_per_slot_json': r[6] or '{}', 'created_at': str(r[7] or '')}
                for r in _sess_rows
            ]

            if _pool_ids:
                _pid_list = ','.join(str(p) for p in _pool_ids)
                interview_data['pool_questions'] = [
                    {'pool_id': r[0], 'question_id': r[1], 'drawn': bool(r[2]),
                     'drawn_at': str(r[3] or ''), 'added_at': str(r[4] or '')}
                    for r in _conn_sql.execute(_sa_text(
                        f"SELECT pool_id, question_id, drawn, drawn_at, added_at "
                        f"FROM interview_pool_questions WHERE pool_id IN ({_pid_list})"
                    )).fetchall()
                ]
                interview_data['configs'] = [
                    {'id': r[0], 'pool_id': r[1], 'config_name': r[2] or 'default',
                     'slots_json': r[3] or '[]', 'created_at': str(r[4] or ''),
                     'updated_at': str(r[5] or '')}
                    for r in _conn_sql.execute(_sa_text(
                        f"SELECT id, pool_id, config_name, slots_json, created_at, updated_at "
                        f"FROM interview_configs WHERE pool_id IN ({_pid_list})"
                    )).fetchall()
                ]

            if _session_ids:
                _sid_list = ','.join(str(s) for s in _session_ids)
                interview_data['sets'] = [
                    {'id': r[0], 'session_id': r[1], 'set_code': r[2],
                     'question_ids_json': r[3] or '[]', 'is_used': bool(r[4]),
                     'used_at': str(r[5] or ''), 'created_at': str(r[6] or '')}
                    for r in _conn_sql.execute(_sa_text(
                        f"SELECT id, session_id, set_code, question_ids_json, is_used, used_at, created_at "
                        f"FROM interview_sets WHERE session_id IN ({_sid_list})"
                    )).fetchall()
                ]
    except Exception:
        pass

    payload = {
        'version': '2.0',
        'exported_by': user.username,
        'exported_at': datetime.now().isoformat(),
        'question_count': len(questions),
        'exam_count': len(exams),
        'question_types': [
            {'name': t.name, 'label': t.label, 'has_options': t.has_options}
            for t in custom_types
        ],
        'questions': [q.to_dict() for q in questions],
        'exams': exam_list,
        'knowledge_graph': kg_data,
        'interview': interview_data,
    }

    buf = BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buf,
        mimetype='application/json',
        as_attachment=True,
        download_name='数据库备份_{}_{}.json'.format(user.username, date_str),
    )


@bp.route('/api/import/full-json', methods=['POST'])
@login_required
@guest_readonly
def import_full_json():
    """
    从 JSON 备份文件导入全部数据到当前账号。
    支持 v1.0（题目+试卷+自定义题型）和 v2.0（+知识图谱+面试题库）格式。
    - 自定义题型：按名称匹配，不存在则创建
    - 题目：question_id 冲突时自动生成新 ID，建立旧→新映射
    - 试卷：用映射更新题目列表，exam_id 冲突时自动生成新 ID
    - 知识图谱：文档生成新 doc_id，章节/知识点跟随新 doc_id 写入
    - 面试题库：题库/场次/套题生成新 ID，题目引用用旧→新映射更新
    """
    import sqlite3 as _sqlite3
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename.endswith('.json'):
        return jsonify({'error': '只支持 .json 格式'}), 400

    try:
        payload = json.loads(f.read().decode('utf-8'))
    except Exception:
        return jsonify({'error': '文件解析失败，请确认是有效的 JSON 备份'}), 400

    version = payload.get('version', '1.0')
    if version not in ('1.0', '2.0'):
        return jsonify({'error': '不支持的备份版本'}), 400

    user = get_current_user()
    now_dt = datetime.now()
    ts = now_dt.strftime('%Y%m%d%H%M%S')
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    stats = {
        'types_created': 0,
        'questions_imported': 0, 'questions_updated': 0, 'questions_skipped': 0,
        'exams_imported': 0, 'exams_updated': 0, 'exams_skipped': 0,
        'kg_docs_imported': 0, 'kps_imported': 0,
        'pools_imported': 0, 'sessions_imported': 0,
    }

    # ── 1. 导入自定义题型 ─────────────────────────────────────────────────────
    existing_type_names = {
        qt.name for qt in QuestionTypeModel.query.filter(
            db.or_(QuestionTypeModel.owner_id.is_(None),
                   QuestionTypeModel.owner_id == user.id)
        ).all()
    }
    for t in payload.get('question_types', []):
        name = (t.get('name') or '').strip()
        if not name or name in existing_type_names:
            continue
        db.session.add(QuestionTypeModel(
            name=name,
            label=t.get('label') or name,
            has_options=bool(t.get('has_options', False)),
            is_builtin=False,
            owner_id=user.id,
            created_at=now_dt,
        ))
        existing_type_names.add(name)
        stats['types_created'] += 1

    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        return jsonify({'error': '题型导入失败'}), 500

    # ── 2. 导入题目，建立旧ID→新ID映射 ───────────────────────────────────────
    # 三分支：同用户已存在→覆盖；他人ID冲突→生成新ID；不存在→沿用原ID
    id_map = {}   # {old_question_id: new_question_id}
    for idx, q_data in enumerate(payload.get('questions', [])):
        old_id = (q_data.get('question_id') or '').strip()
        content = (q_data.get('content') or '').strip()
        if not content:
            stats['questions_skipped'] += 1
            continue

        options_raw = q_data.get('options', [])
        options_str = json.dumps(options_raw if isinstance(options_raw, list) else [], ensure_ascii=False)
        options_en_raw = q_data.get('options_en', [])
        options_en_str = json.dumps(options_en_raw if isinstance(options_en_raw, list) else [], ensure_ascii=False)
        meta_str = json.dumps(q_data.get('metadata') or {}, ensure_ascii=False)

        existing_q = QuestionModel.query.filter_by(question_id=old_id).first() if old_id else None

        if existing_q is not None and existing_q.owner_id == user.id:
            # 同一用户已有此题 → 覆盖更新，保留原 ID
            new_id = old_id
            existing_q.question_type = q_data.get('question_type') or '简答'
            existing_q.content = content
            existing_q.options = options_str
            existing_q.answer = q_data.get('answer') or ''
            existing_q.reference_answer = q_data.get('reference_answer') or ''
            existing_q.explanation = q_data.get('explanation') or ''
            existing_q.content_en = q_data.get('content_en') or None
            existing_q.options_en = options_en_str if options_en_raw else None
            existing_q.subject = q_data.get('subject') or None
            existing_q.knowledge_point = q_data.get('knowledge_point') or None
            existing_q.tags = q_data.get('tags') or None
            existing_q.difficulty = q_data.get('difficulty') or None
            existing_q.language = q_data.get('language') or 'zh'
            existing_q.metadata_json = meta_str
            existing_q.is_used = bool(q_data.get('is_used', False))
            existing_q.updated_at = now_dt
            stats['questions_updated'] += 1
        else:
            # ID 冲突（他人）或不存在 → INSERT
            new_id = old_id if (old_id and existing_q is None) else 'q_imp_{}_{}'.format(ts, idx)
            db.session.add(QuestionModel(
                question_id=new_id,
                question_type=q_data.get('question_type') or '简答',
                content=content, options=options_str,
                answer=q_data.get('answer') or '',
                reference_answer=q_data.get('reference_answer') or '',
                explanation=q_data.get('explanation') or '',
                content_en=q_data.get('content_en') or None,
                options_en=options_en_str if options_en_raw else None,
                subject=q_data.get('subject') or None,
                knowledge_point=q_data.get('knowledge_point') or None,
                tags=q_data.get('tags') or None,
                difficulty=q_data.get('difficulty') or None,
                language=q_data.get('language') or 'zh',
                metadata_json=meta_str,
                is_used=bool(q_data.get('is_used', False)),
                owner_id=user.id, visibility='private',
                created_at=now_dt, updated_at=now_dt,
            ))
            stats['questions_imported'] += 1

        id_map[old_id] = new_id

    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        return jsonify({'error': '题目导入失败'}), 500

    # ── 3. 导入试卷 ───────────────────────────────────────────────────────────
    # 三分支：同用户已存在→覆盖；他人ID冲突→生成新ID；不存在→沿用原ID
    for eidx, e_data in enumerate(payload.get('exams', [])):
        old_exam_id = (e_data.get('exam_id') or '').strip()
        name = (e_data.get('name') or '').strip()
        if not name:
            stats['exams_skipped'] += 1
            continue

        existing_e = ExamModel.query.filter_by(exam_id=old_exam_id).first() if old_exam_id else None

        if existing_e is not None and existing_e.owner_id == user.id:
            # 同一用户已有此试卷 → 覆盖更新
            new_exam_id = old_exam_id
            existing_e.name = name
            existing_e.subject = e_data.get('subject') or None
            existing_e.config = json.dumps(e_data.get('config') or {}, ensure_ascii=False)
            existing_e.is_confirmed = bool(e_data.get('is_confirmed', False))
            existing_e.updated_at = now_dt
            db.session.flush()
            # 清空旧题目关联，重新写入
            db.session.execute(
                exam_questions.delete().where(exam_questions.c.exam_id == new_exam_id)
            )
            stats['exams_updated'] += 1
        else:
            # ID 冲突（他人）或不存在 → INSERT
            new_exam_id = old_exam_id if (old_exam_id and existing_e is None) else 'exam_imp_{}_{}'.format(ts, eidx)
            db.session.add(ExamModel(
                exam_id=new_exam_id, name=name,
                subject=e_data.get('subject') or None,
                config=json.dumps(e_data.get('config') or {}, ensure_ascii=False),
                is_confirmed=bool(e_data.get('is_confirmed', False)),
                owner_id=user.id, visibility='private',
                created_at=now_dt, updated_at=now_dt,
            ))
            db.session.flush()
            stats['exams_imported'] += 1

        for pos, old_qid in enumerate(e_data.get('question_ids', []), start=1):
            new_qid = id_map.get(old_qid)
            if not new_qid:
                continue
            db.session.execute(
                exam_questions.insert().values(
                    exam_id=new_exam_id, question_id=new_qid, position=pos
                )
            )

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': '试卷导入失败：' + str(exc)}), 500

    # ── 4. 导入知识图谱（v2.0，ds_knowledge.db）──────────────────────────────
    if version == '2.0':
        kg_data = payload.get('knowledge_graph', {})
        if kg_data.get('docs'):
            try:
                import uuid as _uuid
                from app.rag_routes import _ds_db_path, _init_ds_db
                _init_ds_db()
                _conn_ds = _sqlite3.connect(str(_ds_db_path()))
                _conn_ds.row_factory = _sqlite3.Row
                try:
                    _doc_id_map = {}  # old_doc_id → new_doc_id
                    for _doc in kg_data['docs']:
                        _old_doc_id = _doc.get('doc_id', '')
                        _new_doc_id = 'doc_imp_' + _uuid.uuid4().hex[:12]
                        _doc_id_map[_old_doc_id] = _new_doc_id
                        _conn_ds.execute(
                            "INSERT OR IGNORE INTO ds_docs "
                            "(doc_id, filename, subject, status, display_name, architecture_json, owner_id) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (_new_doc_id, _doc.get('filename') or '',
                             _doc.get('subject') or '', _doc.get('status') or 'uploaded',
                             _doc.get('display_name') or '', _doc.get('architecture_json') or '{}',
                             user.id)
                        )
                        stats['kg_docs_imported'] += 1

                    for _ch in kg_data.get('chapters', []):
                        _new_doc_id = _doc_id_map.get(_ch.get('doc_id'))
                        if not _new_doc_id:
                            continue
                        _conn_ds.execute(
                            "INSERT INTO ds_chapters "
                            "(doc_id, chapter_num, chapter_name, parent_chapter_num, "
                            "parent_chapter_name, section_name, raw_text) VALUES (?,?,?,?,?,?,?)",
                            (_new_doc_id, _ch.get('chapter_num') or 0,
                             _ch.get('chapter_name') or '',
                             _ch.get('parent_chapter_num') or 0,
                             _ch.get('parent_chapter_name') or '',
                             _ch.get('section_name') or '',
                             _ch.get('raw_text') or '')
                        )

                    for _kp in kg_data.get('kps', []):
                        _new_doc_id = _doc_id_map.get(_kp.get('doc_id'))
                        if not _new_doc_id:
                            continue
                        _conn_ds.execute(
                            "INSERT INTO ds_kps "
                            "(doc_id, chapter_name, chapter_num, kp_name, kp_content, relations_json, "
                            "teaching_focus, knowledge_type, cognitive_dimension, "
                            "section_name, sub_section_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (_new_doc_id, _kp.get('chapter_name') or '',
                             _kp.get('chapter_num') or 0, _kp.get('kp_name') or '',
                             _kp.get('kp_content') or '', _kp.get('relations_json') or '[]',
                             _kp.get('teaching_focus') or '', _kp.get('knowledge_type') or '',
                             _kp.get('cognitive_dimension') or '',
                             _kp.get('section_name') or '', _kp.get('sub_section_name') or '')
                        )
                        stats['kps_imported'] += 1

                    for _ref in kg_data.get('doc_refs', []):
                        _new_doc_id = _doc_id_map.get(_ref.get('doc_id'))
                        if not _new_doc_id:
                            continue
                        _conn_ds.execute(
                            "INSERT INTO ds_doc_refs (doc_id, chapter_num, ref_text) VALUES (?,?,?)",
                            (_new_doc_id, _ref.get('chapter_num') or 0, _ref.get('ref_text') or '')
                        )

                    _conn_ds.commit()
                finally:
                    _conn_ds.close()
            except Exception:
                pass  # 知识图谱导入失败不中断整体流程

        # ── 5. 导入面试题库（v2.0）────────────────────────────────────────────
        interview_data = payload.get('interview', {})
        if interview_data.get('pools'):
            try:
                from sqlalchemy import text as _sa_text
                _pool_id_map = {}    # old_pool_id → new_pool_id
                _config_id_map = {}  # old_config_id → new_config_id
                _session_id_map = {} # old_session_id → new_session_id

                with db.engine.begin() as _conn_sql:
                    for _pool in interview_data['pools']:
                        _conn_sql.execute(_sa_text(
                            "INSERT INTO interview_pools (pool_name, description, created_at, owner_id) "
                            "VALUES (:name,:desc,:cat,:uid)"
                        ), {'name': _pool['pool_name'], 'desc': _pool.get('description') or '',
                            'cat': _pool.get('created_at') or now_str, 'uid': user.id})
                        _new_pid = _conn_sql.execute(_sa_text(
                            "SELECT last_insert_rowid()"
                        )).scalar()
                        _pool_id_map[_pool['id']] = _new_pid
                        stats['pools_imported'] += 1

                    for _cfg in interview_data.get('configs', []):
                        _new_pid = _pool_id_map.get(_cfg['pool_id'])
                        if not _new_pid:
                            continue
                        _conn_sql.execute(_sa_text(
                            "INSERT INTO interview_configs "
                            "(pool_id, config_name, slots_json, created_at, updated_at) "
                            "VALUES (:pid,:name,:slots,:cat,:uat)"
                        ), {'pid': _new_pid, 'name': _cfg.get('config_name') or 'default',
                            'slots': _cfg.get('slots_json') or '[]',
                            'cat': _cfg.get('created_at') or now_str,
                            'uat': _cfg.get('updated_at') or now_str})
                        _new_cid = _conn_sql.execute(_sa_text(
                            "SELECT last_insert_rowid()"
                        )).scalar()
                        _config_id_map[_cfg['id']] = _new_cid

                    for _sess in interview_data.get('sessions', []):
                        _new_pid = _pool_id_map.get(_sess['pool_id'])
                        if not _new_pid:
                            continue
                        _new_cid = _config_id_map.get(_sess.get('config_id'))
                        _conn_sql.execute(_sa_text(
                            "INSERT INTO interview_sessions "
                            "(pool_id, config_id, session_name, interview_count, sets_multiplier, "
                            "score_per_slot_json, created_at, owner_id) "
                            "VALUES (:pid,:cid,:name,:ic,:sm,:sp,:cat,:uid)"
                        ), {'pid': _new_pid, 'cid': _new_cid,
                            'name': _sess['session_name'],
                            'ic': _sess.get('interview_count') or 1,
                            'sm': _sess.get('sets_multiplier') or 3,
                            'sp': _sess.get('score_per_slot_json') or '{}',
                            'cat': _sess.get('created_at') or now_str, 'uid': user.id})
                        _new_sid = _conn_sql.execute(_sa_text(
                            "SELECT last_insert_rowid()"
                        )).scalar()
                        _session_id_map[_sess['id']] = _new_sid
                        stats['sessions_imported'] += 1

                    for _pq in interview_data.get('pool_questions', []):
                        _new_pid = _pool_id_map.get(_pq['pool_id'])
                        _new_qid = id_map.get(_pq['question_id'], _pq['question_id'])
                        if not _new_pid or not _new_qid:
                            continue
                        try:
                            _conn_sql.execute(_sa_text(
                                "INSERT OR IGNORE INTO interview_pool_questions "
                                "(pool_id, question_id, drawn, drawn_at, added_at) "
                                "VALUES (:pid,:qid,:drawn,:dat,:aat)"
                            ), {'pid': _new_pid, 'qid': _new_qid,
                                'drawn': 1 if _pq.get('drawn') else 0,
                                'dat': _pq.get('drawn_at') or None,
                                'aat': _pq.get('added_at') or now_str})
                        except Exception:
                            pass

                    for _s in interview_data.get('sets', []):
                        _new_sid = _session_id_map.get(_s['session_id'])
                        if not _new_sid:
                            continue
                        try:
                            _old_qids = json.loads(_s.get('question_ids_json') or '[]')
                        except Exception:
                            _old_qids = []
                        _new_qids = [id_map.get(_qid, _qid) for _qid in _old_qids if _qid]
                        _conn_sql.execute(_sa_text(
                            "INSERT INTO interview_sets "
                            "(session_id, set_code, question_ids_json, is_used, used_at, created_at) "
                            "VALUES (:sid,:code,:qids,:used,:uat,:cat)"
                        ), {'sid': _new_sid, 'code': _s.get('set_code') or '',
                            'qids': json.dumps(_new_qids, ensure_ascii=False),
                            'used': 1 if _s.get('is_used') else 0,
                            'uat': _s.get('used_at') or None,
                            'cat': _s.get('created_at') or now_str})
            except Exception:
                pass  # 面试题库导入失败不中断整体流程

    return jsonify({
        'ok': True,
        'types_created': stats['types_created'],
        'questions_imported': stats['questions_imported'],
        'questions_updated': stats['questions_updated'],
        'questions_skipped': stats['questions_skipped'],
        'exams_imported': stats['exams_imported'],
        'exams_updated': stats['exams_updated'],
        'exams_skipped': stats['exams_skipped'],
        'kg_docs_imported': stats['kg_docs_imported'],
        'kps_imported': stats['kps_imported'],
        'pools_imported': stats['pools_imported'],
        'sessions_imported': stats['sessions_imported'],
    })


# Exam Generation Routes
@bp.route('/api/exams', methods=['GET'])
@login_required
def get_exams():
    """Get all exams"""
    user = get_current_user()
    exams = ExamModel.query.filter(_visible_e_filter(user)).all()
    return jsonify([e.to_dict() for e in exams])


@bp.route('/api/exams', methods=['POST'])
@login_required
@guest_readonly
def create_exam():
    """Create a new exam"""
    user = get_current_user()
    data = request.json
    now = datetime.now()
    exam = ExamModel(
        exam_id=data.get('exam_id') or f"exam_{uuid.uuid4().hex[:8]}",
        name=data.get('name'),
        config=json.dumps(data.get('config', {}), ensure_ascii=False),
        owner_id=user.id,
        visibility='private',
        created_at=now,
        updated_at=now,
    )
    db.session.add(exam)
    db.session.commit()
    return jsonify(exam.to_dict()), 201


@bp.route('/api/exams/<exam_id>', methods=['GET'])
@login_required
def get_exam(exam_id):
    """Get a specific exam by ID"""
    user = get_current_user()
    exam = ExamModel.query.filter(
        ExamModel.exam_id == exam_id,
        _visible_e_filter(user)
    ).first()
    if exam:
        return jsonify(exam.to_dict())
    return jsonify({'error': 'Exam not found'}), 404


@bp.route('/api/exams/<exam_id>', methods=['PUT'])
@login_required
@guest_readonly
def update_exam(exam_id):
    """Update a specific exam"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权编辑他人试卷'}), 403

    data = request.json
    exam.name = data.get('name', exam.name)
    if 'config' in data:
        exam.config = json.dumps(data['config'], ensure_ascii=False)
    exam.updated_at = datetime.now()

    db.session.commit()
    return jsonify(exam.to_dict())


@bp.route('/api/exams/<exam_id>', methods=['DELETE'])
@login_required
@guest_readonly
def delete_exam(exam_id):
    """Delete a specific exam"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权删除他人试卷'}), 403

    db.session.execute(exam_questions.delete().where(exam_questions.c.exam_id == exam_id))
    db.session.delete(exam)
    db.session.commit()
    return jsonify({'message': 'Exam deleted successfully'})


@bp.route('/api/exams/<exam_id>/add_question', methods=['POST'])
@login_required
@guest_readonly
def add_question_to_exam(exam_id):
    """Add a question to an exam"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权编辑他人试卷'}), 403
    if exam.is_confirmed:
        return jsonify({'error': '试卷已最终确认，无法添加题目'}), 403

    data = request.json
    question_id = data.get('question_id')
    question = db.session.get(QuestionModel, question_id)

    if not question:
        return jsonify({'error': 'Question not found'}), 404

    # Get current max position
    max_pos = db.session.query(db.func.max(exam_questions.c.position)).filter(
        exam_questions.c.exam_id == exam_id
    ).scalar() or -1

    db.session.execute(exam_questions.insert().values(
        exam_id=exam_id,
        question_id=question_id,
        position=max_pos + 1
    ))
    db.session.commit()

    return jsonify(exam.to_dict())


@bp.route('/api/exams/<exam_id>/remove_question/<question_id>', methods=['DELETE'])
@login_required
@guest_readonly
def remove_question_from_exam(exam_id, question_id):
    """Remove a question from an exam"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权编辑他人试卷'}), 403
    if exam.is_confirmed:
        return jsonify({'error': '试卷已最终确认，无法删除题目'}), 403

    db.session.execute(
        exam_questions.delete().where(
            (exam_questions.c.exam_id == exam_id) &
            (exam_questions.c.question_id == question_id)
        )
    )
    db.session.commit()

    return jsonify(exam.to_dict())


@bp.route('/api/exams/generate', methods=['POST'])
@login_required
@guest_readonly
def generate_exam():
    """Generate an exam based on configuration"""
    user = get_current_user()
    data = request.json
    name = data.get('name', f"Exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    config = data.get('config', {})
    subject_filter = data.get('subject') or None
    difficulty_filter = (data.get('difficulty') or '').strip()
    kp_filter = (data.get('knowledge_point') or '').strip()
    tags_filter = [t.strip() for t in (data.get('tags') or []) if str(t).strip()]
    is_used_filter = data.get('is_used_filter', 'unused')
    language_filter = (data.get('language') or '').strip()
    now = datetime.now()

    exam = ExamModel(
        exam_id=data.get('exam_id') or f"exam_{uuid.uuid4().hex[:8]}",
        name=name,
        config=json.dumps(config, ensure_ascii=False),
        subject=subject_filter or None,
        owner_id=user.id,
        visibility='private',
        created_at=now,
        updated_at=now,
    )
    db.session.add(exam)
    db.session.flush()

    position = 0
    shortages = []   # 记录题目不足的题型
    for question_type, settings in config.items():
        count = settings.get('count', 0)
        if count <= 0:
            continue

        q_query = QuestionModel.query.filter(
            db.func.trim(QuestionModel.question_type) == question_type.strip(),
            _visible_q_filter(user),
        )
        # 已用/未用筛选（默认只取未使用题目）
        if is_used_filter == 'unused':
            q_query = q_query.filter(QuestionModel.is_used == False)
        elif is_used_filter == 'used':
            q_query = q_query.filter(QuestionModel.is_used == True)
        # is_used_filter == '' → 不限制
        if subject_filter:
            q_query = q_query.filter(QuestionModel.subject == subject_filter)
        if difficulty_filter:
            q_query = q_query.filter(QuestionModel.difficulty == difficulty_filter)
        if kp_filter:
            q_query = q_query.filter(QuestionModel.knowledge_point.contains(kp_filter))
        if tags_filter:
            q_query = q_query.filter(
                db.or_(*[QuestionModel.tags.contains(t) for t in tags_filter])
            )
        if language_filter:
            q_query = q_query.filter(QuestionModel.language == language_filter)

        available = q_query.order_by(db.func.random()).limit(count).all()

        if len(available) < count:
            shortages.append({
                'type': question_type,
                'requested': count,
                'available': len(available),
            })

        for q in available:
            db.session.execute(exam_questions.insert().values(
                exam_id=exam.exam_id,
                question_id=q.question_id,
                position=position,
            ))
            position += 1

    db.session.commit()
    result = exam.to_dict()
    result['shortages'] = shortages
    return jsonify(result)


@bp.route('/api/exams/<exam_id>/export', methods=['GET'])
@login_required
def export_exam(exam_id):
    """Export an exam to Word document"""
    user = get_current_user()
    exam = ExamModel.query.filter(
        ExamModel.exam_id == exam_id, _visible_e_filter(user)
    ).first()
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    try:
        filename = f"{exam.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'exports', filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        mode = request.args.get('mode', 'zh')
        if mode not in ('zh', 'en', 'both'):
            mode = 'zh'
        show_answer = request.args.get('show_answer', '1') != '0'
        export_exam_to_word(exam, filepath, mode=mode, show_answer=show_answer)

        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


# Template Download Routes
@bp.route('/api/templates/download', methods=['GET'])
def download_template():
    """Download the question bank template"""
    try:
        stream = generate_word_template()
        return send_file(
            stream,
            as_attachment=True,
            download_name='question_template.docx',
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    except Exception as e:
        return jsonify({'error': f'Template generation failed: {str(e)}'}), 500


@bp.route('/api/templates/download-xlsx', methods=['GET'])
def download_xlsx_template():
    """下载 Excel 题库模板"""
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'muban_zh.xlsx')
    if not os.path.exists(template_path):
        return jsonify({'error': '模板文件 muban_zh.xlsx 不存在'}), 500
    return send_file(
        template_path,
        as_attachment=True,
        download_name='muban_zh.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# Question Type Management Routes
@bp.route('/api/question-types', methods=['GET'])
@login_required
def get_question_types():
    """返回内置题型 + 当前用户自定义题型"""
    user = get_current_user()
    types = QuestionTypeModel.query.filter(
        db.or_(
            QuestionTypeModel.owner_id.is_(None),          # 内置
            QuestionTypeModel.owner_id == user.id,         # 当前用户自定义
        )
    ).order_by(QuestionTypeModel.id).all()
    return jsonify([t.to_dict() for t in types])


@bp.route('/api/question-types', methods=['POST'])
@login_required
@guest_readonly
def create_question_type():
    """新增自定义题型（归属当前用户）"""
    user = get_current_user()
    data = request.json
    name = (data.get('name') or '').strip()
    label = (data.get('label') or '').strip()
    has_options = data.get('has_options', False)

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not label:
        label = name

    # 检查内置类型 + 当前用户已有类型是否重名
    conflict = QuestionTypeModel.query.filter(
        QuestionTypeModel.name == name,
        db.or_(
            QuestionTypeModel.owner_id.is_(None),
            QuestionTypeModel.owner_id == user.id,
        )
    ).first()
    if conflict:
        return jsonify({'error': f'题型 "{name}" 已存在'}), 400

    qt = QuestionTypeModel(
        name=name,
        label=label,
        has_options=has_options,
        is_builtin=False,
        owner_id=user.id,
        created_at=datetime.now(),
    )
    db.session.add(qt)
    db.session.commit()
    return jsonify(qt.to_dict()), 201


@bp.route('/api/question-types/<int:type_id>', methods=['PUT'])
@login_required
@guest_readonly
def update_question_type(type_id):
    """修改题型（只能修改自己的自定义题型）"""
    user = get_current_user()
    qt = db.session.get(QuestionTypeModel, type_id)
    if not qt:
        return jsonify({'error': 'Question type not found'}), 404
    if qt.is_builtin:
        return jsonify({'error': '内置题型不可修改'}), 400
    if qt.owner_id != user.id and user.role != 'admin':
        return jsonify({'error': '无权修改他人题型'}), 403

    data = request.json
    new_name = (data.get('name') or '').strip()
    if new_name and new_name != qt.name:
        conflict = QuestionTypeModel.query.filter(
            QuestionTypeModel.name == new_name,
            db.or_(
                QuestionTypeModel.owner_id.is_(None),
                QuestionTypeModel.owner_id == user.id,
            )
        ).first()
        if conflict:
            return jsonify({'error': f'题型 "{new_name}" 已存在'}), 400
        qt.name = new_name
    if 'label' in data:
        qt.label = (data['label'] or '').strip() or qt.label
    if 'has_options' in data:
        qt.has_options = data['has_options']

    db.session.commit()
    return jsonify(qt.to_dict())


@bp.route('/api/question-types/<int:type_id>', methods=['DELETE'])
@login_required
@guest_readonly
def delete_question_type(type_id):
    """删除题型（只能删除自己的自定义题型）"""
    user = get_current_user()
    qt = db.session.get(QuestionTypeModel, type_id)
    if not qt:
        return jsonify({'error': 'Question type not found'}), 404
    if qt.is_builtin:
        return jsonify({'error': 'Cannot delete built-in question type'}), 400
    if qt.owner_id != user.id and user.role != 'admin':
        return jsonify({'error': '无权删除他人题型'}), 403

    # 只检查当前用户题目引用此题型
    ref_count = QuestionModel.query.filter_by(question_type=qt.name, owner_id=user.id).count()
    if ref_count > 0:
        return jsonify({'error': f'Cannot delete: {ref_count} questions use this type'}), 400

    db.session.delete(qt)
    db.session.commit()
    return jsonify({'message': 'Question type deleted successfully'})


# Question Replacement Routes
@bp.route('/api/exams/<exam_id>/replace_question', methods=['POST'])
@login_required
@guest_readonly
def replace_question_in_exam(exam_id):
    """Replace a question in an exam with another question of the same type"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权编辑他人试卷'}), 403

    data = request.json
    old_question_id = data.get('old_question_id')
    new_question_id = data.get('new_question_id')

    # Find the old question in the exam's association
    assoc = db.session.query(exam_questions).filter(
        exam_questions.c.exam_id == exam_id,
        exam_questions.c.question_id == old_question_id
    ).first()

    if not assoc:
        return jsonify({'error': 'Old question not found in exam'}), 404

    if exam.is_confirmed:
        return jsonify({'error': '试卷已最终确认，无法替换题目'}), 403

    old_question = db.session.get(QuestionModel, old_question_id)
    new_question = db.session.get(QuestionModel, new_question_id)

    if not new_question:
        return jsonify({'error': 'New question not found'}), 404

    if old_question.question_type != new_question.question_type:
        return jsonify({'error': 'New question must be of the same type as the old question'}), 400

    # Replace in association table (keep same position)
    # Note: is_used is NOT changed here — only confirm/revert manages that
    position = assoc.position
    db.session.execute(
        exam_questions.delete().where(
            (exam_questions.c.exam_id == exam_id) &
            (exam_questions.c.question_id == old_question_id)
        )
    )
    db.session.execute(exam_questions.insert().values(
        exam_id=exam_id,
        question_id=new_question_id,
        position=position,
    ))
    db.session.commit()

    return jsonify(exam.to_dict())


# Final Exam Confirmation Routes
@bp.route('/api/exams/<exam_id>/confirm', methods=['POST'])
@login_required
@guest_readonly
def confirm_exam(exam_id):
    """Confirm the exam and mark all questions as permanently used"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权操作他人试卷'}), 403

    now = datetime.now()
    for q in exam.get_ordered_questions():
        q.is_used = True
        q.used_date = now

    exam.is_confirmed = True
    exam.confirmed_at = now
    exam.updated_at = now
    db.session.commit()

    return jsonify({'message': 'Exam confirmed successfully', 'exam': exam.to_dict()})


@bp.route('/api/exams/<exam_id>/revert_confirmation', methods=['POST'])
@login_required
@guest_readonly
def revert_exam_confirmation(exam_id):
    """Revert exam confirmation and mark questions as unused"""
    user = get_current_user()
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    if not _can_write_exam(exam, user):
        return jsonify({'error': '无权操作他人试卷'}), 403

    for q in exam.get_ordered_questions():
        q.is_used = False
        q.used_date = None

    exam.is_confirmed = False
    exam.confirmed_at = None
    exam.updated_at = datetime.now()
    db.session.commit()

    return jsonify({'message': 'Exam confirmation reverted successfully', 'exam': exam.to_dict()})


# Usage Management Routes
@bp.route('/api/questions/batch-release', methods=['POST'])
@login_required
@guest_readonly
def batch_release_questions():
    """Release (mark as unused) multiple questions at once"""
    data = request.json
    question_ids = data.get('question_ids', [])

    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400

    released = 0
    for qid in question_ids:
        q = db.session.get(QuestionModel, qid)
        if q and q.is_used:
            q.is_used = False
            q.used_date = None
            released += 1

    db.session.commit()
    return jsonify({'message': f'{released} questions released', 'released_count': released})


# Course Settings Routes
def _get_or_create_course_settings():
    """Get the single course settings row, creating it if needed."""
    settings = CourseSettingsModel.query.first()
    if not settings:
        settings = CourseSettingsModel(updated_at=datetime.now())
        db.session.add(settings)
        db.session.commit()
    return settings


@bp.route('/api/course-settings', methods=['GET'])
def get_course_settings():
    """Get course settings"""
    settings = _get_or_create_course_settings()
    return jsonify(settings.to_dict())


@bp.route('/api/course-settings', methods=['PUT'])
def update_course_settings():
    """Update course settings"""
    settings = _get_or_create_course_settings()
    data = request.json

    if 'course_name' in data:
        settings.course_name = data['course_name']
    if 'course_code' in data:
        settings.course_code = data['course_code']
    if 'exam_format' in data:
        settings.exam_format = data['exam_format']
    if 'exam_method' in data:
        settings.exam_method = data['exam_method']
    if 'target_audience' in data:
        settings.target_audience = data['target_audience']
    if 'institution_name' in data:
        settings.institution_name = data['institution_name']
    if 'semester_info' in data:
        settings.semester_info = data['semester_info']
    if 'exam_title' in data:
        settings.exam_title = data['exam_title']
    if 'paper_label' in data:
        settings.paper_label = data['paper_label']
    settings.updated_at = datetime.now()

    db.session.commit()
    return jsonify(settings.to_dict())


# ─── Review Notes Parser ─────────────────────────────────────────────────────

@bp.route('/api/parse-review-notes', methods=['POST'])
def parse_review_notes():
    """Parse a review notes document (.docx or .txt) and return its plain text content.

    Used by the frontend to embed key review points directly into AI prompts,
    so users can send the combined prompt to an AI without needing to upload a file.
    """
    if 'file' not in request.files:
        return jsonify({'error': '请选择文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '请选择文件'}), 400

    filename = file.filename.lower()

    if filename.endswith('.docx'):
        os.makedirs('temp', exist_ok=True)
        temp_path = os.path.join('temp', f"review_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.docx")
        file.save(temp_path)
        try:
            from docx import Document
            doc = Document(temp_path)
            lines = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    lines.append(text)
            text_content = '\n'.join(lines)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    elif filename.endswith('.txt'):
        try:
            text_content = file.read().decode('utf-8', errors='replace').strip()
        except Exception as e:
            return jsonify({'error': f'文件读取失败: {str(e)}'}), 400

    else:
        return jsonify({'error': '仅支持 .docx 和 .txt 文件'}), 400

    if not text_content.strip():
        return jsonify({'error': '文件内容为空，请检查文件'}), 400

    return jsonify({'text': text_content})
