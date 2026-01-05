"""
创建测试用的Word文档，包含缺失元素
"""
from docx import Document

def create_test_doc_with_missing_elements():
    # 创建一个新的Word文档
    doc = Document()
    
    # 添加内容，故意省略一些元素
    content = """单选题ID: sc_002
难度: medium
知识点: test
标签: test
中文题干: 这是一道缺少英文题干的测试题
A. 选项A
B. 选项B
C. 选项C
D. 选项D
正确答案: A

是非题ID: tf_002
知识点: test
中文题干: 这是一道没有英文题干的是非题
答案: T

论述题ID: es_002
知识点: test
中文题干: 这是一道缺少英文题干和评分标准的论述题

计算题ID: calc_002
知识点: test
中文背景: 这是一道缺少英文背景的计算题"""

    # 添加段落
    for line in content.split('\n'):
        doc.add_paragraph(line)
    
    # 保存文档
    doc.save('D:\\code\\试卷\\test_missing_elements.docx')
    print("已创建测试文档: test_missing_elements.docx，包含缺失元素")

if __name__ == "__main__":
    create_test_doc_with_missing_elements()