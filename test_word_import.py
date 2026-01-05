"""
测试Word文档导入功能
"""
from word_to_csv_converter import WordToCsvConverter

def test_word_import():
    print("测试Word文档导入功能...")
    
    # 创建转换器实例
    converter = WordToCsvConverter()
    
    # 解析测试文档
    questions = converter.parse_questions_from_word_doc("test_questions.docx")
    
    print(f"成功解析到 {len(questions)} 道题目:")
    
    for i, question in enumerate(questions, 1):
        print(f"\n第 {i} 题:")
        print(f"  ID: {question.get('id', 'N/A')}")
        print(f"  类型: {question.get('type', 'N/A')}")
        print(f"  难度: {question.get('difficulty', 'N/A')}")
        print(f"  知识点: {question.get('knowledge_point', 'N/A')}")
        print(f"  标签: {question.get('tags', 'N/A')}")
        print(f"  中文题干: {question.get('chinese_stem', 'N/A')}")
        print(f"  英文题干: {question.get('english_stem', 'N/A')}")
        
        if question.get('type') == 'single_choice':
            options = question.get('options', {})
            print(f"  选项A: {options.get('A', 'N/A')} | {options.get('A_en', 'N/A')}")
            print(f"  选项B: {options.get('B', 'N/A')} | {options.get('B_en', 'N/A')}")
            print(f"  选项C: {options.get('C', 'N/A')} | {options.get('C_en', 'N/A')}")
            print(f"  选项D: {options.get('D', 'N/A')} | {options.get('D_en', 'N/A')}")
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
        elif question.get('type') == 'true_false':
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
            print(f"  解释: {question.get('explanation', 'N/A')}")
            print(f"  英文解释: {question.get('explanation_en', 'N/A')}")
        elif question.get('type') == 'essay':
            print(f"  评分标准: {question.get('scoring_guide', 'N/A')}")
            print(f"  英文评分标准: {question.get('scoring_guide_en', 'N/A')}")
        elif question.get('type') == 'calculation':
            print(f"  中文背景: {question['context'].get('chinese', 'N/A')}")
            print(f"  英文背景: {question['context'].get('english', 'N/A')}")
            print(f"  参数: {question.get('parameters', 'N/A')}")
            print(f"  中文要求: {question['requirements'].get('chinese', 'N/A')}")
            print(f"  英文要求: {question['requirements'].get('english', 'N/A')}")
    
    # 测试导出为CSV
    if questions:
        converter.save_questions_to_csv(questions, "test_output.csv")
        print(f"\n成功导出 {len(questions)} 道题目到 test_output.csv")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_word_import()