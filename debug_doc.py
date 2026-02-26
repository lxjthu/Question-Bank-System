from docx import Document

# Open the test document and print all paragraphs to see the exact structure
doc = Document('temp/test_questions.docx')
print("Document paragraphs:")
for i, para in enumerate(doc.paragraphs):
    print(f"{i}: '{para.text.strip()}'")