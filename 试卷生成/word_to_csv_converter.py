import os
import re
import csv
from docx import Document
from io import StringIO


def convert_word_to_csv(filepath):
    """Convert a Word document to CSV format based on the template specification"""
    # Create a new CSV file path
    csv_path = filepath.rsplit('.', 1)[0] + '.csv'
    
    # Open the Word document
    doc = Document(filepath)
    
    # Prepare to collect questions data
    questions_data = []
    
    # Parse the document content
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    
    # Process the content to extract questions
    current_question = None
    i = 0
    
    while i < len(paragraphs):
        para = paragraphs[i]
        
        # Check if this paragraph starts with a question type marker
        if para.startswith('[') and (']' in para):
            bracket_end = para.find(']')
            question_info = para[1:bracket_end]
            
            # Check if this is a question type (单选, 多选, 是非, 简答, etc.)
            if any(qt in question_info for qt in ['单选', '多选', '是非', '简答']):
                # If we have a previous question, save it
                if current_question is not None:
                    questions_data.append(current_question)
                
                # Use the full identifier as the type (e.g. '简答>材料分析', not just '简答')
                q_type = question_info
                
                # Check if there's an answer in the same line after the bracket
                remaining_after_bracket = para[bracket_end + 1:].strip()
                answer = None
                content = ''
                
                # If there's content after the bracket, check if it contains an answer
                if remaining_after_bracket.startswith('[') and ']' in remaining_after_bracket and len(remaining_after_bracket) >= 3 and remaining_after_bracket[1].isalpha():
                    answer_end = remaining_after_bracket.find(']')
                    answer = remaining_after_bracket[1:answer_end]
                    content = remaining_after_bracket[answer_end + 1:].strip()
                else:
                    content = remaining_after_bracket
                
                current_question = {
                    'type': q_type,
                    'content': content,
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
            # Check if this is an English option line [A_en], [B_en], etc.
            elif current_question is not None and re.match(r'^\[[A-Z]_en\]', para):
                option_text = re.sub(r'^\[[A-Z]_en\]\s*', '', para)
                current_question['options_en'].append(option_text)
            # Check if this is an option line [A], [B], etc.
            elif len(para) >= 3 and para[1].isalpha() and para[2] == ']':
                if current_question is not None:
                    option_text = para[3:].strip()
                    current_question['options'].append(option_text)
        
        # Check if this is a reference answer section
        elif para.startswith('<参考答案>'):
            if current_question is not None:
                ref_answer_content = para[len('<参考答案>'):]
                if '</参考答案>' in ref_answer_content:
                    end_idx = ref_answer_content.find('</参考答案>')
                    ref_answer_content = ref_answer_content[:end_idx]
                    current_question['reference_answer'] = ref_answer_content.strip()
                else:
                    # Collect content until we find the closing tag
                    i += 1
                    ref_answer_content_lines = []
                    if ref_answer_content.strip():
                        ref_answer_content_lines.append(ref_answer_content.strip())
                    while i < len(paragraphs):
                        # Closing tag: </参考答案> or <参考答案> (same tag used as closer)
                        if paragraphs[i].startswith('</参考答案>') or paragraphs[i].strip() == '<参考答案>':
                            break
                        # If we encounter a new question, we need to break and process it in the next iteration
                        elif paragraphs[i].startswith('[') and any(qt in paragraphs[i][1:paragraphs[i].find(']')] if ']' in paragraphs[i] else '' for qt in ['单选', '多选', '是非', '简答']):
                            i -= 1  # Go back to process this as a new question
                            break
                        else:
                            ref_answer_content_lines.append(paragraphs[i])
                            i += 1
                    current_question['reference_answer'] = '\n'.join(ref_answer_content_lines)
        
        # Check if this is an explanation section
        elif para.startswith('<解析>'):
            if current_question is not None:
                explanation_content = para[len('<解析>'):]
                if '</解析>' in explanation_content:
                    end_idx = explanation_content.find('</解析>')
                    explanation_content = explanation_content[:end_idx]
                    current_question['explanation'] = explanation_content.strip()
                else:
                    # Collect content until we find the closing tag
                    i += 1
                    explanation_content_lines = []
                    if explanation_content.strip():
                        explanation_content_lines.append(explanation_content.strip())
                    while i < len(paragraphs):
                        # Closing tag: </解析> or <解析> (same tag used as closer)
                        if paragraphs[i].startswith('</解析>') or paragraphs[i].strip() == '<解析>':
                            break
                        # If we encounter a new question, we need to break and process it in the next iteration
                        elif paragraphs[i].startswith('[') and any(qt in paragraphs[i][1:paragraphs[i].find(']')] if ']' in paragraphs[i] else '' for qt in ['单选', '多选', '是非', '简答']):
                            i -= 1  # Go back to process this as a new question
                            break
                        else:
                            explanation_content_lines.append(paragraphs[i])
                            i += 1
                    # Extract metadata lines from explanation
                    filtered_lines = []
                    for eline in explanation_content_lines:
                        if re.match(r'^知识点[:：]', eline):
                            current_question['knowledge_point'] = re.sub(r'^知识点[:：]\s*', '', eline)
                        elif re.match(r'^标签[:：]', eline):
                            current_question['tags'] = re.sub(r'^标签[:：]\s*', '', eline)
                        elif re.match(r'^英文题目[:：]', eline):
                            current_question['content_en'] = re.sub(r'^英文题目[:：]\s*', '', eline)
                        elif re.match(r'^难度[:：]', eline):
                            current_question['difficulty'] = re.sub(r'^难度[:：]\s*', '', eline)
                        else:
                            filtered_lines.append(eline)
                    current_question['explanation'] = '\n'.join(filtered_lines)

        # If we have a current question and this is content for it (not a new question marker)
        elif current_question is not None and not para.startswith('[') and not para.startswith('<'):
            # Accumulate all content paragraphs (needed for multi-paragraph questions like 材料分析)
            if not current_question['content']:
                current_question['content'] = para
            else:
                current_question['content'] += '\n' + para
        
        i += 1
    
    # Don't forget to add the last question if it exists
    if current_question is not None:
        questions_data.append(current_question)
    
    # Write the questions data to CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['type', 'content', 'options', 'answer', 'reference_answer', 'explanation',
                      'content_en', 'options_en', 'knowledge_point', 'tags', 'difficulty']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for question in questions_data:
            # Convert options list to a string representation
            options_str = '|'.join(question['options']) if question['options'] else ''
            options_en_str = '|'.join(question.get('options_en', [])) if question.get('options_en') else ''
            writer.writerow({
                'type': question['type'],
                'content': question['content'],
                'options': options_str,
                'answer': question['answer'] or '',
                'reference_answer': question['reference_answer'],
                'explanation': question['explanation'],
                'content_en': question.get('content_en', ''),
                'options_en': options_en_str,
                'knowledge_point': question.get('knowledge_point', ''),
                'tags': question.get('tags', ''),
                'difficulty': question.get('difficulty', ''),
            })
    
    return csv_path


def parse_csv_to_questions(csv_path):
    """Parse the CSV file and return a list of question dictionaries"""
    questions = []
    with open(csv_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Convert options string back to a list
            options = row['options'].split('|') if row['options'] else []
            if options == ['']:  # Handle empty options
                options = []
                
            options_en_str = row.get('options_en', '')
            options_en = options_en_str.split('|') if options_en_str else []
            if options_en == ['']:
                options_en = []

            question = {
                'type': row['type'],
                'content': row['content'],
                'options': options,
                'answer': row['answer'] or None,
                'reference_answer': row['reference_answer'] or None,
                'explanation': row['explanation'] or None,
                'content_en': row.get('content_en', '') or None,
                'options_en': options_en,
                'knowledge_point': row.get('knowledge_point', '') or None,
                'tags': row.get('tags', '') or None,
                'difficulty': row.get('difficulty', '') or None,
            }
            questions.append(question)
    
    return questions