"""
测试Word导入功能的完整流程
"""
from word_to_csv_converter import WordToCsvConverter

def test_complete_import():
    print("测试完整的Word导入功能...")
    
    # 创建转换器实例
    converter = WordToCsvConverter()
    
    # 解析测试文档
    questions = converter.parse_questions_from_word_doc("D:\\code\\试卷\\test_questions_proper.docx")
    
    print(f"成功解析到 {len(questions)} 道题目:")
    
    for i, question in enumerate(questions, 1):
        print(f"\n第 {i} 道题:")
        print(f"  ID: {question.get('id', 'N/A')}")
        print(f"  类型: {question.get('type', 'N/A')}")
        print(f"  知识点: {question.get('knowledge_point', 'N/A')}")
        print(f"  标签: {question.get('tags', 'N/A')}")
        
        qtype = question.get('type')
        if qtype == 'single_choice':
            print(f"  难度: {question.get('difficulty', 'N/A')}")
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')[:50]}...")
            print(f"  英文题干: {question.get('english_stem', 'N/A')[:50]}...")
            options = question.get('options', {})
            print(f"  选项A: {options.get('A', 'N/A')[:30]}...")
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
        elif qtype == 'true_false':
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')[:50]}...")
            print(f"  正确答案: {question.get('correct_answer', 'N/A')}")
            print(f"  解释: {question.get('explanation', 'N/A')[:50]}...")
        elif qtype == 'essay':
            print(f"  中文题干: {question.get('chinese_stem', 'N/A')[:50]}...")
            print(f"  评分标准: {question.get('scoring_guide', 'N/A')}")
        elif qtype == 'calculation':
            context = question.get('context', {})
            print(f"  中文背景: {context.get('chinese', 'N/A')[:50]}...")
            print(f"  参数: {question.get('parameters', 'N/A')}")
            reqs = question.get('requirements', {})
            print(f"  中文要求: {reqs.get('chinese', 'N/A')}")
    
    # 验证数据结构是否符合前端要求
    print("\n验证数据结构...")
    all_valid = True
    for i, question in enumerate(questions, 1):
        qtype = question.get('type')
        if qtype == 'single_choice':
            required_fields = ['id', 'type', 'difficulty', 'chinese_stem', 'english_stem', 'options', 'correct_answer', 'knowledge_point', 'tags']
            for field in required_fields:
                if field not in question:
                    print(f"  错误: 单选题第{i}缺少字段: {field}")
                    all_valid = False
        elif qtype == 'true_false':
            required_fields = ['id', 'type', 'chinese_stem', 'english_stem', 'correct_answer', 'explanation', 'explanation_en', 'knowledge_point', 'tags']
            for field in required_fields:
                if field not in question:
                    print(f"  错误: 是非题第{i}缺少字段: {field}")
                    all_valid = False
        elif qtype == 'essay':
            required_fields = ['id', 'type', 'chinese_stem', 'english_stem', 'scoring_guide', 'scoring_guide_en', 'knowledge_point', 'tags']
            for field in required_fields:
                if field not in question:
                    print(f"  错误: 论述题第{i}缺少字段: {field}")
                    all_valid = False
        elif qtype == 'calculation':
            required_fields = ['id', 'type', 'context', 'parameters', 'requirements', 'knowledge_point', 'tags']
            for field in required_fields:
                if field not in question:
                    print(f"  错误: 计算题第{i}缺少字段: {field}")
                    all_valid = False
    
    if all_valid:
        print("  √ 所有题目数据结构完整")
    else:
        print("  X 存在数据结构问题")

    print("\n测试完成！")

if __name__ == "__main__":
    test_complete_import()