from docx import Document

def analyze_document_structure():
    """Analyze the structure of the document to understand the parsing issue"""
    doc = Document(r'D:\code\试卷\林业经济学题库.docx')
    
    # Extract all text
    all_text = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            all_text.append(text)
    
    print("Document structure analysis:")
    print("="*50)
    
    # Find all question IDs and their positions
    question_positions = []
    for i, line in enumerate(all_text):
        if "单选题ID:" in line or "是非题ID:" in line or "论述题ID:" in line or "计算题ID:" in line:
            question_positions.append((i, line))
    
    print(f"Found {len(question_positions)} question markers:")
    for pos, line in question_positions[:20]:  # Show first 20
        print(f"  Line {pos}: {line}")
    
    if len(question_positions) > 20:
        print(f"  ... and {len(question_positions) - 20} more")
    
    print("\nSample of text around first true/false question:")
    for i in range(len(all_text)):
        if "是非题ID: tf_001" in all_text[i]:
            start = max(0, i-2)
            end = min(len(all_text), i+10)
            for j in range(start, end):
                marker = ">>> " if j == i else "    "
                print(f"{marker}Line {j}: {all_text[j]}")
            break
    
    print("\nSample of text around first essay question:")
    for i in range(len(all_text)):
        if "论述题ID: es_001" in all_text[i]:
            start = max(0, i-2)
            end = min(len(all_text), i+10)
            for j in range(start, end):
                marker = ">>> " if j == i else "    "
                print(f"{marker}Line {j}: {all_text[j]}")
            break

if __name__ == "__main__":
    analyze_document_structure()