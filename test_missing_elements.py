"""
测试包含缺失元素的Word文档导入
"""
from word_to_csv_converter import WordToCsvConverter

def test_missing_elements():
    print("测试包含缺失元素的Word文档导入...")
    
    # 创建转换器实例
    converter = WordToCsvConverter()
    
    # 解析包含缺失元素的测试文档
    questions = converter.parse_questions_from_word_doc("D:\\code\\试卷\\test_missing_elements.docx")
    
    print(f"成功解析到 {len(questions)} 道题目:")
    
    for i, question in enumerate(questions, 1):
        print(f"\n第 {i} 道题:")
        print(f"  ID: {question.get('id', 'N/A')}")
        print(f"  类型: {question.get('type', 'N/A')}")
        print(f"  知识点: {question.get('knowledge_point', 'N/A')}")
        
        qtype = question.get('type')
        if qtype == 'single_choice':
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')}")
            print(f"  英文题干: {question.get('english_stem', 'N/A')}")
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
        elif qtype == 'true_false':
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')}")
            print(f"  英文题干: {question.get('english_stem', 'N/A')}")
        elif qtype == 'essay':
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')}")
            print(f"  英文题干: {question.get('english_stem', 'N/A')}")
        elif qtype == 'calculation':
            context = question.get('context', {})
            print(f"  中文背景: {context.get('chinese', 'N/A')}")
            print(f"  英文背景: {context.get('english', 'N/A')}")
    
    print(f"\n检测到 {len(converter.warnings)} 个警告:")
    for warning in converter.warnings:
        print(f"  - {warning}")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_missing_elements()