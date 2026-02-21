from flask import Blueprint, request, jsonify, render_template, send_file
from app.db_models import db, QuestionModel, ExamModel, QuestionTypeModel, CourseSettingsModel, exam_questions
from app.utils import allowed_file, generate_word_template, export_exam_to_word
import os
import json
import uuid
from datetime import datetime

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Main page route"""
    return render_template('index.html')


# Question Bank Management Routes
@bp.route('/api/questions', methods=['GET'])
def get_questions():
    """Get all questions or search questions"""
    keyword = request.args.get('keyword', '')
    question_type = request.args.get('type', '')
    language = request.args.get('language', '')
    difficulty = request.args.get('difficulty', '')
    knowledge_point = request.args.get('knowledge_point', '')
    is_used = request.args.get('is_used', '')
    subject = request.args.get('subject', '')

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

    questions = query.all()
    return jsonify([q.to_dict() for q in questions])


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
    return jsonify(question.to_dict())


@bp.route('/api/questions/<question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a specific question"""
    question = db.session.get(QuestionModel, question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

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

            # Convert Word to CSV if needed
            if file.filename.lower().endswith('.docx'):
                from app.utils import parse_question_template
                import sys
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)
                from word_to_csv_converter import convert_word_to_csv as actual_convert_word_to_csv, parse_csv_to_questions

                csv_path = actual_convert_word_to_csv(file_path)
                questions_data = parse_csv_to_questions(csv_path)

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
                        options=json.dumps(q_data['options'], ensure_ascii=False),
                        answer=q_data['answer'],
                        reference_answer=q_data['reference_answer'],
                        explanation=q_data['explanation'],
                        content_en=content_en,
                        options_en=json.dumps(options_en, ensure_ascii=False) if options_en else None,
                        subject=import_subject or q_data.get('subject') or None,
                        knowledge_point=q_data.get('knowledge_point') or None,
                        tags=q_data.get('tags') or None,
                        difficulty=q_data.get('difficulty') or None,
                        language=lang,
                        metadata_json='{}',
                        created_at=now,
                        updated_at=now,
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

                if os.path.exists(csv_path):
                    os.remove(csv_path)

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
                        created_at=now,
                        updated_at=now,
                    )
                    models.append(model)
                db.session.add_all(models)
                db.session.commit()

            # Clean up temporary files
            if os.path.exists(file_path):
                os.remove(file_path)

            imported = len(models)
            return jsonify({
                'message': 'Questions imported successfully',
                'count': imported,
                'skipped': skipped,
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
    now = datetime.now()

    # Create a new exam
    exam = ExamModel(
        exam_id=data.get('exam_id') or f"exam_{uuid.uuid4().hex[:8]}",
        name=name,
        config=json.dumps(config, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    db.session.add(exam)
    db.session.flush()

    position = 0
    for question_type, settings in config.items():
        count = settings.get('count', 0)

        # Get unused questions of this type (strip whitespace for comparison)
        q_query = QuestionModel.query.filter(
            db.func.trim(QuestionModel.question_type) == question_type.strip(),
            QuestionModel.is_used == False
        )
        if subject_filter:
            q_query = q_query.filter(QuestionModel.subject == subject_filter)
        available = q_query.limit(count).all()

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
