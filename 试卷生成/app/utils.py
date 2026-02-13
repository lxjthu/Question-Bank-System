import os
import json
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
import csv
import re


def allowed_file(filename):
    """Check if the uploaded file is allowed"""
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'csv'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS




def generate_word_template():
    """Generate a standard Word template for question bank import.

    Reads question types from the database so that newly added custom types
    automatically appear in the template.
    """
    from app.db_models import QuestionTypeModel

    doc = Document()

    # Add title
    title = doc.add_heading('试题库导入模板', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Add instructions
    doc.add_paragraph('使用说明：')
    doc.add_paragraph('1. 每道题以 [题型] 开头，题型标识符用方括号包围')
    doc.add_paragraph('2. 题型后可跟答案标识符（如 [A]、[ABD] 等）')
    doc.add_paragraph('3. 选择题答案紧跟在题型标识后，用方括号包围')
    doc.add_paragraph('4. 选择题选项格式：[选项字母] + 选项内容')
    doc.add_paragraph('5. 解析可选，用 <解析>...</解析> 包围')
    doc.add_paragraph('6. 参考答案用 <参考答案>...</参考答案> 包围')
    doc.add_paragraph('7. 中文内容用 （中文） 标注，英文内容用 （英文） 标注')
    doc.add_paragraph('8. 英文选项格式：[A_en]English option（紧跟中文选项后）')
    doc.add_paragraph('9. 解析区段内可包含元数据行：知识点:xxx / 标签:xxx / 英文题目:xxx / 难度:easy|medium|hard')

    # Query all question types from DB
    question_types = QuestionTypeModel.query.order_by(QuestionTypeModel.id).all()

    for qt in question_types:
        doc.add_heading(f'{qt.label}示例：', level=1)
        if qt.has_options:
            example_text = (f"[{qt.name}][A]\n示例题目内容？\n"
                          f"[A]选项A\n[B]选项B\n[C]选项C\n[D]选项D\n"
                          f"[A_en]Option A\n[B_en]Option B\n[C_en]Option C\n[D_en]Option D\n"
                          f"<解析>\n这是一段解析\n知识点:林业经济\n标签:基础,概念\n"
                          f"英文题目:Example question content?\n难度:medium\n</解析>")
        else:
            example_text = (f"[{qt.name}]\n示例题目内容？\n<参考答案>\n这是一段参考答案\n</参考答案>\n"
                          f"<解析>\n这是一段解析\n知识点:林业经济\n标签:基础,概念\n"
                          f"英文题目:Example question content?\n难度:medium\n</解析>")
        doc.add_paragraph(example_text)

    # Create temp directory
    template_dir = os.path.join(os.getcwd(), 'temp')
    os.makedirs(template_dir, exist_ok=True)
    template_path = os.path.join(template_dir, 'question_template.docx')

    doc.save(template_path)
    return template_path


def export_exam_to_word(exam, filepath: str, mode: str = 'zh', show_answer: bool = True):
    """Export an exam to a Word document with proper formatting.

    Accepts an ExamModel instance (SQLAlchemy model).
    mode: 'zh' (Chinese only), 'en' (English only), 'both' (bilingual side-by-side)
    show_answer: True = include answers/explanations, False = questions only
    """
    doc = Document()

    # Add exam title
    title = doc.add_heading(f'{exam.name}', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Add exam info
    created_str = exam.created_at.strftime("%Y-%m-%d %H:%M:%S") if exam.created_at else ''
    doc.add_paragraph(f'考试名称: {exam.name}')
    doc.add_paragraph(f'生成时间: {created_str}')
    doc.add_paragraph(f'总分: {exam.calculate_total_score()} 分')
    doc.add_paragraph()

    # Get ordered questions from the exam
    questions = exam.get_ordered_questions()

    # Group questions by type
    question_types = {}
    for question in questions:
        if question.question_type not in question_types:
            question_types[question.question_type] = []
        question_types[question.question_type].append(question)

    # Add questions by type
    for q_type, type_questions in question_types.items():
        doc.add_heading(f'{q_type}', level=1)

        for i, question in enumerate(type_questions, 1):
            options_zh = json.loads(question.options) if question.options else []
            options_en = json.loads(question.options_en) if question.options_en else []
            content_en = question.content_en or ''

            # Add question number and content based on mode
            p = doc.add_paragraph()
            if mode == 'zh':
                p.add_run(f'{i}. {question.content}').bold = True
            elif mode == 'en':
                display_content = content_en if content_en else question.content
                p.add_run(f'{i}. {display_content}').bold = True
            else:  # both
                p.add_run(f'{i}. {question.content}').bold = True
                if content_en:
                    p.add_run(f'\n    {content_en}')

            # Add options based on mode
            if mode == 'zh':
                for j, option in enumerate(options_zh):
                    doc.add_paragraph(f'   {chr(65+j)}. {option}')
            elif mode == 'en':
                display_options = options_en if options_en else options_zh
                for j, option in enumerate(display_options):
                    doc.add_paragraph(f'   {chr(65+j)}. {option}')
            else:  # both
                max_len = max(len(options_zh), len(options_en))
                for j in range(max_len):
                    zh_opt = options_zh[j] if j < len(options_zh) else ''
                    en_opt = options_en[j] if j < len(options_en) else ''
                    if en_opt:
                        doc.add_paragraph(f'   {chr(65+j)}. {zh_opt} / {en_opt}')
                    else:
                        doc.add_paragraph(f'   {chr(65+j)}. {zh_opt}')

            if show_answer:
                # Add answer if available
                if question.answer:
                    doc.add_paragraph(f'   答案: {question.answer}')

                # Add reference answer if available
                if question.reference_answer:
                    doc.add_paragraph(f'   参考答案: {question.reference_answer}')

                # Add explanation if available
                if question.explanation:
                    doc.add_paragraph(f'   解析: {question.explanation}')

            doc.add_paragraph()  # Add spacing between questions

    # Save the document
    doc.save(filepath)


def parse_question_template(content: str) -> list:
    """Parse questions from the template format"""
    questions = []
    
    # Split content by question markers
    # This is a simplified parser - a full implementation would be more complex
    lines = content.split('\n')
    
    current_question = None
    current_section = None  # 'question', 'options', 'answer', 'explanation', 'reference_answer'
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith('[') and ']' in line[:20] and not (len(line) >= 3 and line[1].isalpha() and line[2] == ']') and not re.match(r'^\[[A-Z]_en\]', line):
            # Found a new question
            if current_question:
                questions.append(current_question)
            
            # Parse question type and answer
            bracket_end = line.find(']')
            question_info = line[1:bracket_end]
            
            if '>' in question_info:
                q_type, specific_type = question_info.split('>', 1)
            else:
                q_type = question_info
                specific_type = ''
            
            # Determine if there's an answer in the bracket
            answer = None
            if len(line) > bracket_end + 1:
                # Look for answer after the bracket
                remaining = line[bracket_end + 1:].strip()
                if remaining.startswith('[') and ']' in remaining:
                    answer_end = remaining.find(']')
                    answer = remaining[1:answer_end]
            
            current_question = {
                'type': q_type,
                'specific_type': specific_type,
                'content': '',
                'options': [],
                'options_en': [],
                'content_en': '',
                'knowledge_point': '',
                'tags': '',
                'difficulty': '',
                'answer': answer,
                'reference_answer': '',
                'explanation': ''
            }
            
            # The next line should be the question content
            if bracket_end + 1 < len(line):
                current_question['content'] = line[bracket_end + 1:].strip()
            else:
                i += 1
                if i < len(lines):
                    current_question['content'] = lines[i].strip()
        
        elif current_question and re.match(r'^\[[A-Z]_en\]', line):
            # English option line like [A_en] option text
            option_text = re.sub(r'^\[[A-Z]_en\]\s*', '', line)
            current_question['options_en'].append(option_text)

        elif current_question and line.startswith('[') and len(line) >= 3 and line[1].isalpha() and line[2] == ']':
            # Option line like [A] option text
            option_letter = line[1]
            option_text = line[3:].strip()
            current_question['options'].append(option_text)
        
        elif line.startswith('<参考答案>'):
            current_section = 'reference_answer'
            current_question['reference_answer'] = ''
            # Check if the content is on the same line
            content_start = line.find('<参考答案>') + len('<参考答案>')
            if content_start < len(line):
                current_question['reference_answer'] = line[content_start:]
        
        elif line.startswith('<解析>'):
            current_section = 'explanation'
            current_question['explanation'] = ''
            # Check if the content is on the same line
            content_start = line.find('<解析>') + len('<解析>')
            if content_start < len(line):
                current_question['explanation'] = line[content_start:]
        
        elif line.startswith('</参考答案>') or line.startswith('</解析>'):
            current_section = None
        
        elif current_section == 'reference_answer':
            current_question['reference_answer'] += '\n' + line
        
        elif current_section == 'explanation':
            if re.match(r'^知识点[:：]', line):
                current_question['knowledge_point'] = re.sub(r'^知识点[:：]\s*', '', line)
            elif re.match(r'^标签[:：]', line):
                current_question['tags'] = re.sub(r'^标签[:：]\s*', '', line)
            elif re.match(r'^英文题目[:：]', line):
                current_question['content_en'] = re.sub(r'^英文题目[:：]\s*', '', line)
            elif re.match(r'^难度[:：]', line):
                current_question['difficulty'] = re.sub(r'^难度[:：]\s*', '', line)
            else:
                current_question['explanation'] += '\n' + line
        
        elif current_question and current_section is None and not line.startswith('[') and not line.startswith('<') and not line.startswith('('):
            # Additional content for the question
            if not current_question['content']:
                current_question['content'] = line
            else:
                current_question['content'] += '\n' + line
        
        i += 1
    
    # Add the last question if it exists
    if current_question:
        questions.append(current_question)
    
    return questions