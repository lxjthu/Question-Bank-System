from flask import Blueprint, request, jsonify, render_template, send_file
from app.db_models import db, QuestionModel, ExamModel, QuestionTypeModel, CourseSettingsModel, exam_questions, QuestionImageModel
from app.utils import allowed_file, generate_word_template, export_exam_to_word, save_image_file, delete_question_images, _IMAGES_DIR, _associate_images_in_html
import os
import json
import uuid
from datetime import datetime

bp = Blueprint('main', __name__)


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
def get_questions():
    """Get all questions or search questions"""
    from datetime import timedelta
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

    query = QuestionModel.query

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
def count_questions():
    """返回满足筛选条件的题目数量（用于组卷预估）。"""
    from datetime import timedelta
    subject = request.args.get('subject', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    kp = request.args.get('knowledge_point', '').strip()
    tags_str = request.args.get('tags', '').strip()
    is_used = request.args.get('is_used', '')

    q = QuestionModel.query
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
    return jsonify({'count': q.count()})


@bp.route('/api/questions/subjects', methods=['GET'])
def get_subjects():
    """Get all distinct subject values from the question bank"""
    rows = db.session.query(QuestionModel.subject).filter(
        QuestionModel.subject.isnot(None),
        QuestionModel.subject != ''
    ).distinct().all()
    subjects = sorted([r[0] for r in rows if r[0]])
    return jsonify(subjects)


@bp.route('/api/questions', methods=['POST'])
def add_question():
    """Add a new question"""
    data = request.json
    now = datetime.now()

    content_en = data.get('content_en')
    options_en = data.get('options_en')
    language = data.get('language', 'zh')
    # Auto-detect bilingual
    if content_en and language == 'zh':
        language = 'both'

    question = QuestionModel(
        question_id=data.get('question_id'),
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
def get_question(question_id):
    """Get a specific question by ID"""
    question = db.session.get(QuestionModel, question_id)
    if question:
        return jsonify(question.to_dict())
    return jsonify({'error': 'Question not found'}), 404


@bp.route('/api/questions/<question_id>', methods=['PUT'])
def update_question(question_id):
    """Update a specific question"""
    question = db.session.get(QuestionModel, question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

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
    # Auto-upgrade language to 'both' if content_en is provided
    if question.content_en and question.language == 'zh':
        question.language = 'both'
    question.updated_at = datetime.now()

    db.session.commit()
    # Associate any newly uploaded images in updated fields
    for html in [question.content, question.reference_answer, question.explanation]:
        _associate_images_in_html(html, question.question_id)
    db.session.commit()
    return jsonify(question.to_dict())


@bp.route('/api/questions/<question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a specific question"""
    question = db.session.get(QuestionModel, question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    delete_question_images(question_id)
    db.session.delete(question)
    db.session.commit()
    return jsonify({'message': 'Question deleted successfully'})


@bp.route('/api/questions/batch-delete', methods=['POST'])
def batch_delete_questions():
    """Delete multiple questions at once"""
    data = request.json
    question_ids = data.get('question_ids', [])

    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400

    # Cascade delete images for all questions
    for qid in question_ids:
        delete_question_images(qid)

    # Remove exam_questions associations first
    db.session.execute(
        exam_questions.delete().where(exam_questions.c.question_id.in_(question_ids))
    )

    # Delete the questions
    deleted = QuestionModel.query.filter(QuestionModel.question_id.in_(question_ids)).delete(
        synchronize_session=False
    )
    db.session.commit()

    return jsonify({'message': f'{deleted} questions deleted successfully', 'deleted_count': deleted})


@bp.route('/api/questions/batch-update-type', methods=['POST'])
def batch_update_question_type():
    """Change question_type for multiple questions at once"""
    data = request.json
    question_ids = data.get('question_ids', [])
    new_type = data.get('question_type', '')

    if not question_ids:
        return jsonify({'error': 'No question IDs provided'}), 400
    if not new_type:
        return jsonify({'error': 'No question_type provided'}), 400

    # Verify the target type exists
    qt = QuestionTypeModel.query.filter_by(name=new_type).first()
    if not qt:
        return jsonify({'error': f'Question type "{new_type}" not found'}), 400

    now = datetime.now()
    updated = QuestionModel.query.filter(
        QuestionModel.question_id.in_(question_ids)
    ).update({
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


def _parse_xlsx_questions(file_path):
    """
    解析 xlsx 题库文件，兼容两种格式：
    - muban_zh.xlsx 导出格式（标题行在第3行，数据从第4行）
    - 外部题库格式（标题行在第1行，数据从第2行）
    返回: (questions_list, errors_list)
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

    for row_idx, row in enumerate(
        ws.iter_rows(min_row=data_start, values_only=True), data_start
    ):
        stem = str(row[7] or '').strip() if len(row) > 7 else ''
        if not stem:
            continue

        raw_type = str(row[1] or '').strip()
        q_type = _XLSX_TYPE_REVERSE.get(raw_type)
        if not q_type:
            errors.append(f"第{row_idx}行：未知题型 '{raw_type}'，已跳过")
            continue

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

    return questions, errors


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
def import_questions():
    """Import questions from a file (Word or CSV)"""
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
            existing_contents = set(
                row[0].strip()
                for row in db.session.query(QuestionModel.content).all()
                if row[0]
            )

            questions_data = []
            models = []
            skipped = 0

            # Parse .docx using rich-content importer (supports images + tables)
            if file.filename.lower().endswith('.docx'):
                from app.docx_importer import parse_docx_with_rich_content

                # Collect known question type names for marker validation
                known_types = {
                    qt.name for qt in QuestionTypeModel.query.all()
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
                    existing_contents.add(content_text)  # prevent duplicates within this batch
                    question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_{i}"
                    content_en = q_data.get('content_en') or None
                    options_en = q_data.get('options_en') or []
                    lang = 'both' if content_en else 'zh'
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
                    existing_contents.add(content_text)  # prevent duplicates within this batch
                    question_id = f"q_{now.strftime('%Y%m%d_%H%M%S')}_txt_{i}"
                    content_en = q_data.get('content_en') or None
                    options_en = q_data.get('options_en') or []
                    lang = 'both' if content_en else 'zh'
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
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

            elif file.filename.lower().endswith('.xlsx'):
                questions_data, parse_errors = _parse_xlsx_questions(file_path)
                failed = len(parse_errors)

                now = datetime.now()
                for i, q_data in enumerate(questions_data):
                    content_text = (q_data.get('content') or '').strip()
                    if content_text in existing_contents:
                        skipped += 1
                        continue
                    existing_contents.add(content_text)
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
                        language='zh',
                        metadata_json='{}',
                        imported_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

                imported = len(models)
                os.remove(file_path) if os.path.exists(file_path) else None
                return jsonify({
                    'message': 'Questions imported successfully',
                    'imported': imported,
                    'count': imported,
                    'skipped': skipped,
                    'failed': failed,
                    'parse_errors': parse_errors[:10],  # 最多返回10条解析错误
                })

            # Clean up temporary files
            if os.path.exists(file_path):
                os.remove(file_path)

            imported = len(models)
            return jsonify({
                'message': 'Questions imported successfully',
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


@bp.route('/api/questions/export', methods=['GET'])
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


# Exam Generation Routes
@bp.route('/api/exams', methods=['GET'])
def get_exams():
    """Get all exams"""
    exams = ExamModel.query.all()
    return jsonify([e.to_dict() for e in exams])


@bp.route('/api/exams', methods=['POST'])
def create_exam():
    """Create a new exam"""
    data = request.json
    now = datetime.now()
    exam = ExamModel(
        exam_id=data.get('exam_id') or f"exam_{uuid.uuid4().hex[:8]}",
        name=data.get('name'),
        config=json.dumps(data.get('config', {}), ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    db.session.add(exam)
    db.session.commit()
    return jsonify(exam.to_dict()), 201


@bp.route('/api/exams/<exam_id>', methods=['GET'])
def get_exam(exam_id):
    """Get a specific exam by ID"""
    exam = db.session.get(ExamModel, exam_id)
    if exam:
        return jsonify(exam.to_dict())
    return jsonify({'error': 'Exam not found'}), 404


@bp.route('/api/exams/<exam_id>', methods=['PUT'])
def update_exam(exam_id):
    """Update a specific exam"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    data = request.json
    exam.name = data.get('name', exam.name)
    if 'config' in data:
        exam.config = json.dumps(data['config'], ensure_ascii=False)
    exam.updated_at = datetime.now()

    db.session.commit()
    return jsonify(exam.to_dict())


@bp.route('/api/exams/<exam_id>', methods=['DELETE'])
def delete_exam(exam_id):
    """Delete a specific exam"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    # Remove all exam-question associations first
    db.session.execute(exam_questions.delete().where(exam_questions.c.exam_id == exam_id))
    db.session.delete(exam)
    db.session.commit()
    return jsonify({'message': 'Exam deleted successfully'})


@bp.route('/api/exams/<exam_id>/add_question', methods=['POST'])
def add_question_to_exam(exam_id):
    """Add a question to an exam"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
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
def remove_question_from_exam(exam_id, question_id):
    """Remove a question from an exam"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
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
def generate_exam():
    """Generate an exam based on configuration"""
    data = request.json
    name = data.get('name', f"Exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    config = data.get('config', {})
    subject_filter = data.get('subject') or None
    difficulty_filter = (data.get('difficulty') or '').strip()
    kp_filter = (data.get('knowledge_point') or '').strip()
    tags_filter = [t.strip() for t in (data.get('tags') or []) if str(t).strip()]
    is_used_filter = data.get('is_used_filter', 'unused')
    now = datetime.now()

    # Create a new exam
    exam = ExamModel(
        exam_id=data.get('exam_id') or f"exam_{uuid.uuid4().hex[:8]}",
        name=name,
        config=json.dumps(config, ensure_ascii=False),
        subject=subject_filter or None,
        created_at=now,
        updated_at=now,
    )
    db.session.add(exam)
    db.session.flush()

    position = 0
    for question_type, settings in config.items():
        count = settings.get('count', 0)

        q_query = QuestionModel.query.filter(
            db.func.trim(QuestionModel.question_type) == question_type.strip(),
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
        available = q_query.order_by(db.func.random()).limit(count).all()

        for q in available:
            db.session.execute(exam_questions.insert().values(
                exam_id=exam.exam_id,
                question_id=q.question_id,
                position=position,
            ))
            position += 1

    db.session.commit()
    return jsonify(exam.to_dict())


@bp.route('/api/exams/<exam_id>/export', methods=['GET'])
def export_exam(exam_id):
    """Export an exam to Word document"""
    exam = db.session.get(ExamModel, exam_id)
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


# Question Type Management Routes
@bp.route('/api/question-types', methods=['GET'])
def get_question_types():
    """Get all question types ordered by id"""
    types = QuestionTypeModel.query.order_by(QuestionTypeModel.id).all()
    return jsonify([t.to_dict() for t in types])


@bp.route('/api/question-types', methods=['POST'])
def create_question_type():
    """Create a custom question type"""
    data = request.json
    name = (data.get('name') or '').strip()
    label = (data.get('label') or '').strip()
    has_options = data.get('has_options', False)

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not label:
        label = name

    if QuestionTypeModel.query.filter_by(name=name).first():
        return jsonify({'error': f'Question type "{name}" already exists'}), 400

    qt = QuestionTypeModel(
        name=name,
        label=label,
        has_options=has_options,
        is_builtin=False,
        created_at=datetime.now(),
    )
    db.session.add(qt)
    db.session.commit()
    return jsonify(qt.to_dict()), 201


@bp.route('/api/question-types/<int:type_id>', methods=['PUT'])
def update_question_type(type_id):
    """Update a question type"""
    qt = db.session.get(QuestionTypeModel, type_id)
    if not qt:
        return jsonify({'error': 'Question type not found'}), 404

    data = request.json
    new_name = (data.get('name') or '').strip()
    if new_name and new_name != qt.name:
        existing = QuestionTypeModel.query.filter_by(name=new_name).first()
        if existing:
            return jsonify({'error': f'Question type "{new_name}" already exists'}), 400
        qt.name = new_name
    if 'label' in data:
        qt.label = (data['label'] or '').strip() or qt.label
    if 'has_options' in data:
        qt.has_options = data['has_options']

    db.session.commit()
    return jsonify(qt.to_dict())


@bp.route('/api/question-types/<int:type_id>', methods=['DELETE'])
def delete_question_type(type_id):
    """Delete a question type (only custom types with no references)"""
    qt = db.session.get(QuestionTypeModel, type_id)
    if not qt:
        return jsonify({'error': 'Question type not found'}), 404

    if qt.is_builtin:
        return jsonify({'error': 'Cannot delete built-in question type'}), 400

    # Check if any questions reference this type
    ref_count = QuestionModel.query.filter_by(question_type=qt.name).count()
    if ref_count > 0:
        return jsonify({'error': f'Cannot delete: {ref_count} questions use this type'}), 400

    db.session.delete(qt)
    db.session.commit()
    return jsonify({'message': 'Question type deleted successfully'})


# Question Replacement Routes
@bp.route('/api/exams/<exam_id>/replace_question', methods=['POST'])
def replace_question_in_exam(exam_id):
    """Replace a question in an exam with another question of the same type"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

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
def confirm_exam(exam_id):
    """Confirm the exam and mark all questions as permanently used"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

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
def revert_exam_confirmation(exam_id):
    """Revert exam confirmation and mark questions as unused"""
    exam = db.session.get(ExamModel, exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

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
