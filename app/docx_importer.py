"""docx_importer.py — Rich-content Word document importer.

Replaces word_to_csv_converter.py for .docx files.
Iterates doc.element.body directly to capture:
  - Inline images (<w:drawing> elements)
  - Tables (<w:tbl> elements)
  - Soft line-break–separated logical lines within a single <w:p>

Returns a list of question dicts compatible with the existing import route.
"""
import re
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph as DocxParagraph

# XML namespace for DrawingML blip (image reference)
_A_BLIP = '{http://schemas.openxmlformats.org/drawingml/2006/main}blip'
_R_EMBED = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed'


def _local_tag(element):
    tag = element.tag
    return tag.split('}')[-1] if '}' in tag else tag


def _para_logical_lines(p_element):
    """Split a <w:p> element into logical lines at every <w:br>.

    python-docx's Paragraph.text concatenates all <w:t> text BUT does NOT
    include newlines for soft breaks.  We need to split manually so that a
    single paragraph like "[简答>材料分析]\\n题目正文" is correctly parsed.

    Returns list[str] — one entry per logical line (may be empty strings).
    """
    lines = []
    current = []

    for run in p_element.iter(qn('w:r')):
        for child in run:
            ctag = _local_tag(child)
            if ctag == 't':
                current.append(child.text or '')
            elif ctag == 'br':
                lines.append(''.join(current))
                current = []
            # drawings are handled separately by _extract_images
    lines.append(''.join(current))
    return lines


def _extract_images(p_element, doc, save_image_fn):
    """Return an HTML string of <img> tags for every inline image in the paragraph."""
    parts = []
    for drawing in p_element.iter(qn('w:drawing')):
        for blip in drawing.iter(_A_BLIP):
            r_id = blip.get(_R_EMBED)
            if r_id and r_id in doc.part.rels:
                try:
                    img_part = doc.part.related_parts[r_id]
                    image_id = save_image_fn(
                        img_part.blob,
                        img_part.content_type or 'image/png',
                    )
                    parts.append(
                        f'<img src="/api/images/{image_id}" '
                        f'style="max-width:100%;display:block;" />'
                    )
                except Exception:
                    pass
    return '\n'.join(parts)


def _tbl_to_html(tbl_element):
    """Convert a <w:tbl> element to a compact HTML <table> string."""
    html = '<table border="1" style="border-collapse:collapse;width:100%;">'
    for tr in tbl_element:
        if _local_tag(tr) != 'tr':
            continue
        html += '<tr>'
        for tc in tr:
            if _local_tag(tc) != 'tc':
                continue
            cell_text = ''.join(
                t.text or '' for t in tc.iter(qn('w:t'))
            )
            html += f'<td style="padding:4px;">{cell_text}</td>'
        html += '</tr>'
    html += '</table>'
    return html


def _parse_question_marker(line, known_types=None):
    """Detect a question-type marker like [单选][A] or [简答>材料分析].

    Returns (q_type, answer, is_marker).
    """
    line = line.strip()
    if not line.startswith('['):
        return None, None, False

    bracket_end = line.find(']')
    if bracket_end < 1:
        return None, None, False

    q_type = line[1:bracket_end]

    # Reject single uppercase letter (option) or all-uppercase (multi-letter answer)
    if not q_type:
        return None, None, False
    if q_type in ('正确', '错误'):
        return None, None, False
    if q_type.isalpha() and q_type.isupper():
        return None, None, False

    # Validate against known types if provided
    if known_types:
        if q_type not in known_types:
            return None, None, False
    else:
        # Heuristic: question types contain Chinese characters
        if not any('\u4e00' <= c <= '\u9fff' for c in q_type):
            return None, None, False

    # Parse optional answer bracket after the type bracket
    remaining = line[bracket_end + 1:].strip()
    answer = None
    if remaining.startswith('[') and ']' in remaining:
        ans_end = remaining.find(']')
        ans_candidate = remaining[1:ans_end]
        if (ans_candidate.isalpha() and ans_candidate.isupper()) or \
                ans_candidate in ('正确', '错误'):
            answer = ans_candidate

    return q_type, answer, True


def _new_question(q_type, answer):
    return {
        'type': q_type,
        'content': '',
        'options': [],
        'options_en': [],
        'content_en': '',
        'knowledge_point': '',
        'tags': '',
        'difficulty': '',
        'answer': answer,
        'reference_answer': '',
        'explanation': '',
    }


def parse_docx_with_rich_content(filepath: str, save_image_fn, known_types=None) -> list:
    """Parse a .docx file and return a list of question dicts with HTML content.

    Args:
        filepath: Path to the .docx file.
        save_image_fn: callable(image_bytes: bytes, content_type: str) -> image_id: str
            Called for each embedded image; should persist the image and return its ID.
        known_types: Optional set/list of valid question type names for validation.
                     If None, falls back to a Chinese-character heuristic.

    Returns:
        List of dicts with keys: type, content, options, options_en, content_en,
        knowledge_point, tags, difficulty, answer, reference_answer, explanation.
        'content' (and reference_answer/explanation) may contain HTML with
        <img src="/api/images/..."> and <table>...</table> elements.
    """
    doc = Document(filepath)
    body = doc.element.body

    questions = []
    current_q = None
    current_field = None   # 'content' | 'reference_answer' | 'explanation' | None
    field_parts = []       # accumulates HTML fragments for current_field

    def flush_field():
        nonlocal field_parts
        if current_q is None or current_field is None:
            field_parts = []
            return
        text = '\n'.join(p for p in field_parts if p).strip()
        current_q[current_field] = text
        field_parts = []

    def finalize_question():
        if current_q is None:
            return
        flush_field()
        questions.append(dict(current_q))

    def process_text_line(line: str):
        """Handle one logical text line in the context of the current field."""
        nonlocal current_field, field_parts

        line = line.strip()
        if not line:
            return

        # ── Section markers ────────────────────────────────────────────────
        if line.startswith('<参考答案>'):
            flush_field()
            current_field = 'reference_answer'
            inline = line[len('<参考答案>'):].strip()
            if inline and not inline.startswith('</'):
                field_parts.append(inline)
            return

        if line.startswith('</参考答案>'):
            flush_field()
            current_field = None
            return

        if line.startswith('<解析>'):
            flush_field()
            current_field = 'explanation'
            inline = line[len('<解析>'):].strip()
            if inline and not inline.startswith('</'):
                field_parts.append(inline)
            return

        if line.startswith('</解析>'):
            flush_field()
            current_field = None
            return

        # ── Field-specific handling ────────────────────────────────────────
        if current_field == 'reference_answer':
            field_parts.append(line)

        elif current_field == 'explanation':
            if re.match(r'^知识点[:：]', line):
                current_q['knowledge_point'] = re.sub(r'^知识点[:：]\s*', '', line)
            elif re.match(r'^标签[:：]', line):
                current_q['tags'] = re.sub(r'^标签[:：]\s*', '', line)
            elif re.match(r'^英文题目[:：]', line):
                current_q['content_en'] = re.sub(r'^英文题目[:：]\s*', '', line)
            elif re.match(r'^难度[:：]', line):
                current_q['difficulty'] = re.sub(r'^难度[:：]\s*', '', line)
            else:
                field_parts.append(line)

        elif current_field == 'content':
            # English option: [A_en] text
            if re.match(r'^\[[A-Z]_en\]', line):
                current_q['options_en'].append(
                    re.sub(r'^\[[A-Z]_en\]\s*', '', line)
                )
            # Chinese option: [A] text  (single uppercase letter)
            elif re.match(r'^\[([A-Z])\]', line) and len(line) >= 3:
                current_q['options'].append(line[3:].strip())
            else:
                field_parts.append(line)

    # ── Main body iteration ───────────────────────────────────────────────
    for child in body:
        tag = _local_tag(child)

        if tag == 'sectPr':
            continue

        if tag == 'p':
            # Wrap with DocxParagraph to access .text cleanly
            para = DocxParagraph(child, doc)
            logical_lines = _para_logical_lines(child)
            first_line = logical_lines[0].strip() if logical_lines else ''

            q_type, answer, is_marker = _parse_question_marker(first_line, known_types)

            if is_marker:
                # Finalize previous question before starting a new one
                if current_q is not None:
                    finalize_question()
                current_q = _new_question(q_type, answer)
                current_field = 'content'
                field_parts = []
                # Process any lines that follow the type marker in this paragraph
                for line in logical_lines[1:]:
                    process_text_line(line)

            elif current_q is not None:
                # Extract any embedded images in this paragraph
                images_html = _extract_images(child, doc, save_image_fn)

                # Process text lines
                for line in logical_lines:
                    process_text_line(line)

                # Append image HTML after text (preserve document order)
                if images_html and current_field == 'content':
                    field_parts.append(images_html)

        elif tag == 'tbl' and current_q is not None:
            # Embed table as HTML in the current field (usually 'content')
            if current_field == 'content':
                field_parts.append(_tbl_to_html(child))

    # Finalize the last question
    if current_q is not None:
        finalize_question()

    return questions
