import os
import json
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Inches, Pt, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
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
    doc.add_paragraph('2. 选择题答案紧跟在题型标识后，用方括号包围，如 [单选][A]、[多选][ABD]')
    doc.add_paragraph('3. 是非题答案只能是 [正确] 或 [错误]，无需列选项')
    doc.add_paragraph('4. 选择题选项格式：[A]选项内容（字母大写，紧跟内容，无空格）')
    doc.add_paragraph('5. 解析可选，用 <解析>...</解析> 包围')
    doc.add_paragraph('6. 参考答案用 <参考答案>...</参考答案> 包围')
    doc.add_paragraph('7. 双语出题：在 <解析> 区段内写 "英文题目:English question?" 提供英文题干')
    doc.add_paragraph('8. 双语选项：先列全部中文选项 [A][B][C][D]，再在其后统一列英文选项 [A_en][B_en][C_en][D_en]')
    doc.add_paragraph('9. 解析区段内可包含元数据行：知识点:xxx / 标签:xxx / 英文题目:xxx / 难度:easy|medium|hard')

    # Query all question types from DB
    question_types = QuestionTypeModel.query.order_by(QuestionTypeModel.id).all()

    for qt in question_types:
        doc.add_heading(f'{qt.label}示例：', level=1)

        # 是非题 special case: no options, answer is [正确] or [错误]
        if qt.name == '是非':
            example_text = (
                f"[{qt.name}][正确]\n"
                f"示例陈述句，此句表述正确。\n"
                f"<解析>\n这是一段解析\n知识点:学科知识\n标签:基础,概念\n"
                f"英文题目:Example statement that is true.\n难度:medium\n</解析>"
            )
        elif qt.has_options:
            # 多选题 shows multi-letter answer; 单选题 shows single letter
            sample_answer = 'ABD' if qt.name == '多选' else 'A'
            example_text = (
                f"[{qt.name}][{sample_answer}]\n示例题目内容？\n"
                f"[A]选项A\n[B]选项B\n[C]选项C\n[D]选项D\n"
                f"[A_en]Option A\n[B_en]Option B\n[C_en]Option C\n[D_en]Option D\n"
                f"<解析>\n这是一段解析\n知识点:学科知识\n标签:基础,概念\n"
                f"英文题目:Example question content?\n难度:medium\n</解析>"
            )
        else:
            example_text = (
                f"[{qt.name}]\n示例题目内容？\n<参考答案>\n这是一段参考答案\n</参考答案>\n"
                f"<解析>\n这是一段解析\n知识点:学科知识\n标签:基础,概念\n"
                f"英文题目:Example question content?\n难度:medium\n</解析>"
            )
        doc.add_paragraph(example_text)

    # Save to in-memory stream to avoid file-lock conflicts on Windows
    import io as _io
    stream = _io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream


CHINESE_NUMBERS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                   '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']


def _set_run_font(run, size_pt, bold=False, cn_font='宋体', en_font='Times New Roman'):
    """Set font properties on a run: size, bold, Chinese font, English font."""
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.font.name = en_font
    run.element.rPr.rFonts.set(qn('w:eastAsia'), cn_font)


def _add_styled_paragraph(doc, text, size_pt, bold=False, alignment=None,
                          cn_font='宋体', en_font='Times New Roman',
                          space_before=None, space_after=None, line_spacing=None):
    """Add a paragraph with consistent font styling."""
    p = doc.add_paragraph()
    if alignment is not None:
        p.alignment = alignment
    run = p.add_run(text)
    _set_run_font(run, size_pt, bold=bold, cn_font=cn_font, en_font=en_font)
    pf = p.paragraph_format
    if space_before is not None:
        pf.space_before = Pt(space_before)
    if space_after is not None:
        pf.space_after = Pt(space_after)
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    return p


def _add_page_number_footer(doc):
    """Add '第 X 页（共 Y 页）' footer using PAGE/NUMPAGES field codes."""
    section = doc.sections[0]
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    run_pre = p.add_run('第 ')
    _set_run_font(run_pre, 9)

    # PAGE field
    fld_page = parse_xml(
        '<w:fldSimple {} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'.format(nsdecls('w'))
    )
    p._element.append(fld_page)

    run_mid = p.add_run(' 页（共 ')
    _set_run_font(run_mid, 9)

    # NUMPAGES field
    fld_total = parse_xml(
        '<w:fldSimple {} w:instr=" NUMPAGES "><w:r><w:t>1</w:t></w:r></w:fldSimple>'.format(nsdecls('w'))
    )
    p._element.append(fld_total)

    run_end = p.add_run(' 页）')
    _set_run_font(run_end, 9)


def export_exam_to_word(exam, filepath: str, mode: str = 'zh', show_answer: bool = True):
    """Export an exam to a Word document matching formal exam paper formatting.

    Accepts an ExamModel instance (SQLAlchemy model).
    mode: 'zh' (Chinese only), 'en' (English only), 'both' (bilingual, English first)
    show_answer: True = include answers/explanations, False = questions only
    """
    from app.db_models import CourseSettingsModel

    doc = Document()

    # --- Page setup: A4, standard margins ---
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2)

    # --- Set default document font ---
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    style.paragraph_format.line_spacing = 1.15

    # --- Load course settings ---
    course_settings = CourseSettingsModel.query.first()
    cs = course_settings  # shorthand

    # --- Header section ---
    # Line 1: institution + semester (centered, 18pt bold)
    header_line1_parts = []
    if cs and cs.institution_name:
        header_line1_parts.append(cs.institution_name)
    if cs and cs.semester_info:
        header_line1_parts.append(cs.semester_info)
    if header_line1_parts:
        _add_styled_paragraph(doc, ' '.join(header_line1_parts), 18, bold=True,
                              alignment=WD_ALIGN_PARAGRAPH.CENTER,
                              cn_font='黑体', space_after=0)

    # Line 2: exam title (centered, 18pt bold)
    exam_title = (cs.exam_title if cs and cs.exam_title else '期末考试试卷')
    _add_styled_paragraph(doc, exam_title, 18, bold=True,
                          alignment=WD_ALIGN_PARAGRAPH.CENTER,
                          cn_font='黑体', space_before=0, space_after=6)

    # Empty line
    _add_styled_paragraph(doc, '', 10.5, space_before=0, space_after=0)

    # Course info lines (14pt)
    course_name = (cs.course_name if cs else '') or ''
    paper_label = (cs.paper_label if cs else 'A') or 'A'
    if course_name:
        _add_styled_paragraph(doc, f'课程名称：《{course_name}》（{paper_label}）卷', 14,
                              space_before=0, space_after=2)
    course_code = (cs.course_code if cs else '') or ''
    if course_code:
        _add_styled_paragraph(doc, f'课程代号：{course_code}', 14,
                              space_before=0, space_after=2)

    # Exam format + method on same line
    fmt_parts = []
    if cs and cs.exam_format:
        fmt_parts.append(f'考试形式：{cs.exam_format}')
    if cs and cs.exam_method:
        fmt_parts.append(f'考试方式：{cs.exam_method}')
    if fmt_parts:
        _add_styled_paragraph(doc, '    '.join(fmt_parts), 14,
                              space_before=0, space_after=2)

    if cs and cs.target_audience:
        _add_styled_paragraph(doc, f'使用对象：{cs.target_audience}', 14,
                              space_before=0, space_after=2)

    # Total score line
    total_score = exam.calculate_total_score()
    if total_score > 0:
        _add_styled_paragraph(doc, f'满分：{total_score} 分', 14,
                              space_before=0, space_after=2)

    # Separator line
    _add_styled_paragraph(doc, '━' * 50, 12,
                          alignment=WD_ALIGN_PARAGRAPH.CENTER,
                          space_before=6, space_after=6)

    # --- Questions ---
    questions = exam.get_ordered_questions()
    config = json.loads(exam.config) if exam.config else {}

    # Group questions by type (preserving order)
    question_groups = {}
    group_order = []
    for question in questions:
        if question.question_type not in question_groups:
            question_groups[question.question_type] = []
            group_order.append(question.question_type)
        question_groups[question.question_type].append(question)

    # Render each question type section
    for section_idx, q_type in enumerate(group_order):
        type_questions = question_groups[q_type]
        cn_num = CHINESE_NUMBERS[section_idx] if section_idx < len(CHINESE_NUMBERS) else str(section_idx + 1)

        # Build section title with stats
        count = len(type_questions)
        type_config = config.get(q_type, {})
        points = type_config.get('points', 0)
        # Display only the sub-type for hierarchical types (e.g. '简答>材料分析' → '材料分析')
        type_label = q_type.split('>')[-1] if '>' in q_type else q_type
        if points > 0:
            section_title = f'{cn_num}、{type_label}（共{count}题，每题{points}分，共计{count * points}分）'
        else:
            section_title = f'{cn_num}、{type_label}（共{count}题）'

        _add_styled_paragraph(doc, section_title, 12, bold=True,
                              space_before=12, space_after=6)

        for i, question in enumerate(type_questions, 1):
            options_zh = json.loads(question.options) if question.options else []
            options_en = json.loads(question.options_en) if question.options_en else []
            content_en = question.content_en or ''

            # --- Question content ---
            if mode == 'both' and content_en:
                # English first, then Chinese
                p_en = doc.add_paragraph()
                p_en.paragraph_format.space_before = Pt(3)
                p_en.paragraph_format.space_after = Pt(1)
                p_en.paragraph_format.line_spacing = 1.15
                run_en = p_en.add_run(f'{i}. {content_en}')
                _set_run_font(run_en, 10.5)

                p_zh = doc.add_paragraph()
                p_zh.paragraph_format.space_before = Pt(0)
                p_zh.paragraph_format.space_after = Pt(3)
                p_zh.paragraph_format.line_spacing = 1.15
                run_zh = p_zh.add_run(f'   {question.content}')
                _set_run_font(run_zh, 10.5)
            elif mode == 'en':
                display = content_en if content_en else question.content
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(3)
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(f'{i}. {display}')
                _set_run_font(run, 10.5)
            else:  # zh or both without English content
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(3)
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(f'{i}. {question.content}')
                _set_run_font(run, 10.5)

            # --- Options ---
            if mode == 'both' and options_en:
                # English options first
                for j, opt in enumerate(options_en):
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.left_indent = Cm(0.5)
                    run = p.add_run(f'[{chr(65+j)}] {opt}')
                    _set_run_font(run, 10.5)
                # Chinese options
                for j, opt in enumerate(options_zh):
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.left_indent = Cm(0.5)
                    run = p.add_run(f'[{chr(65+j)}] {opt}')
                    _set_run_font(run, 10.5)
            elif mode == 'en':
                display_opts = options_en if options_en else options_zh
                for j, opt in enumerate(display_opts):
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.left_indent = Cm(0.5)
                    run = p.add_run(f'[{chr(65+j)}] {opt}')
                    _set_run_font(run, 10.5)
            else:  # zh
                for j, opt in enumerate(options_zh):
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.left_indent = Cm(0.5)
                    run = p.add_run(f'[{chr(65+j)}] {opt}')
                    _set_run_font(run, 10.5)

            # --- Answers ---
            if show_answer:
                if question.answer:
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.left_indent = Cm(0.5)
                    run = p.add_run(f'答案：{question.answer}')
                    _set_run_font(run, 10.5, bold=True)

                if question.reference_answer:
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.left_indent = Cm(0.5)
                    run_label = p.add_run('参考答案：')
                    _set_run_font(run_label, 10.5, bold=True)
                    run_text = p.add_run(question.reference_answer)
                    _set_run_font(run_text, 10.5)

                if question.explanation:
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.left_indent = Cm(0.5)
                    run_label = p.add_run('解析：')
                    _set_run_font(run_label, 10.5, bold=True)
                    run_text = p.add_run(question.explanation)
                    _set_run_font(run_text, 10.5)

    # --- Page footer with page numbers ---
    _add_page_number_footer(doc)

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
            
            # Use the full identifier as the type (e.g. '简答>材料分析', not just '简答')
            q_type = question_info

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
                'content': '',
                'options': [],
                'options_en': [],
                'content_en': '',
                'subject': '',
                'knowledge_point': '',
                'tags': '',
                'difficulty': '',
                'answer': answer,
                'reference_answer': '',
                'explanation': ''
            }
            
            # The next line should be the question content.
            # After the type bracket, there may be an answer bracket like [B] or [ABD].
            # We must skip that bracket and only capture actual text content.
            rest_of_line = line[bracket_end + 1:].strip()
            # If rest_of_line is solely an answer bracket (e.g. "[B]", "[ABD]", "[正确]", "[错误]"),
            # the actual question content is on the next line.
            _answer_only = re.match(r'^\[([A-Z]{1,4}|正确|错误)\]$', rest_of_line)
            _answer_prefix = re.match(r'^\[([A-Z]{1,4}|正确|错误)\]', rest_of_line)
            if rest_of_line and _answer_only:
                # Only an answer bracket remains — read content from the next line
                i += 1
                if i < len(lines):
                    current_question['content'] = lines[i].strip()
            elif rest_of_line and _answer_prefix:
                # Answer bracket followed by inline content — strip the bracket
                current_question['content'] = re.sub(r'^\[([A-Z]{1,4}|正确|错误)\]\s*', '', rest_of_line)
            elif rest_of_line:
                current_question['content'] = rest_of_line
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
            if re.match(r'^科目[:：]', line):
                current_question['subject'] = re.sub(r'^科目[:：]\s*', '', line)
            elif re.match(r'^知识点[:：]', line):
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