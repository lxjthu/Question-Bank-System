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

    # Query all question types from DB
    question_types = QuestionTypeModel.query.order_by(QuestionTypeModel.id).all()

    for qt in question_types:
        doc.add_heading(f'{qt.label}示例：', level=1)
        if qt.has_options:
            example_text = f"[{qt.name}][A]\n示例题目内容？\n[A]选项A\n[B]选项B\n[C]选项C\n[D]选项D\n<解析>\n这是一段解析\n<解析>"
        else:
            example_text = f"[{qt.name}]\n示例题目内容？\n<参考答案>\n这是一段参考答案\n<参考答案>\n<解析>\n这是一段解析\n<解析>"
        doc.add_paragraph(example_text)

    # Create temp directory
    template_dir = os.path.join(os.getcwd(), 'temp')
    os.makedirs(template_dir, exist_ok=True)
    template_path = os.path.join(template_dir, 'question_template.docx')

    doc.save(template_path)
    return template_path


def export_exam_to_word(exam, filepath: str):
    """Export an exam to a Word document with proper formatting.

    Accepts an ExamModel instance (SQLAlchemy model).
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
            # Add question number and content
            p = doc.add_paragraph()
            p.add_run(f'{i}. {question.content}').bold = True

            # Add options if it's a choice question
            options = json.loads(question.options) if question.options else []
            if options:
                for j, option in enumerate(options):
                    doc.add_paragraph(f'   {chr(65+j)}. {option}')

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
        
        if line.startswith('[') and ']' in line[:20] and not (len(line) >= 3 and line[1].isalpha() and line[2] == ']'):
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