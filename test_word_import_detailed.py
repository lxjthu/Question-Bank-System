"""
测试Word文档导入功能
"""
from word_to_csv_converter import WordToCsvConverter

def test_word_import():
    print("测试Word文档导入功能...")
    
    # 创建转换器实例
    converter = WordToCsvConverter()
    
    # 解析测试文档
    questions = converter.parse_questions_from_word_doc("D:\\code\\试卷\\test_questions_proper.docx")
    
    print(f"成功解析到 {len(questions)} 道题目:")
    
    for i, question in enumerate(questions, 1):
        print(f"\n第 {i} 题:")
        print(f"  ID: {question.get('id', 'N/A')}")
        print(f"  类型: {question.get('type', 'N/A')}")
        print(f"  keys: {list(question.keys())}")
        
        if 'chinese_stem' in question:
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')[:50]}...")
        if 'english_stem' in question:
            print(f"  英文题干: {question.get('english_stem', 'N/A')[:50]}...")
        
        if question.get('type') == 'single_choice':
            options = question.get('options', {})
            print(f"  选项: {options}")
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
        elif question.get('type') == 'true_false':
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
            print(f"  解释: {question.get('explanation', 'N/A')}")
        elif question.get('type') == 'essay':
            print(f"  评分标准: {question.get('scoring_guide', 'N/A')}")
        elif question.get('type') == 'calculation':
            print(f"  中文背景: {question['context'].get('chinese', 'N/A')[:50]}...")
            print(f"  参数: {question.get('parameters', 'N/A')}")
    
    # 测试导出为CSV
    if questions:
        converter.save_questions_to_csv(questions, "test_output.csv")
        print(f"\n成功导出 {len(questions)} 道题目到 test_output.csv")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_word_import()