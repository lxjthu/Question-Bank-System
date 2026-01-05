from word_to_csv_converter import WordToCsvConverter

def detailed_test_parsing():
    converter = WordToCsvConverter()
    questions = converter.parse_questions_from_word_doc(r'D:\code\试卷\林业经济学题库.docx')
    print(f'解析到 {len(questions)} 道题目')
    
    # 统计各类型题目数量
    type_counts = {}
    for q in questions:
        qtype = q.get("type", "unknown")
        type_counts[qtype] = type_counts.get(qtype, 0) + 1
    
    print("各类型题目数量:")
    for qtype, count in type_counts.items():
        print(f"  {qtype}: {count}")
    
    # Show some examples from each type
    print("\n示例题目:")
    
    single_choices = [q for q in questions if q.get("type") == "single_choice"]
    true_falses = [q for q in questions if q.get("type") == "true_false"]
    essays = [q for q in questions if q.get("type") == "essay"]
    calculations = [q for q in questions if q.get("type") == "calculation"]
    
    print(f"\n单选题示例 (前3个):")
    for i, q in enumerate(single_choices[:3], 1):
        print(f"  {i}. {q.get('id')}: {q.get('chinese_stem', '')[:60]}...")
    
    print(f"\n是非题示例 (前3个):")
    for i, q in enumerate(true_falses[:3], 1):
        print(f"  {i}. {q.get('id')}: {q.get('chinese_stem', '')[:60]}...")
    
    print(f"\n论述题示例 (前3个):")
    for i, q in enumerate(essays[:3], 1):
        print(f"  {i}. {q.get('id')}: {q.get('chinese_stem', '')[:60]}...")
    
    print(f"\n计算题示例 (前3个):")
    for i, q in enumerate(calculations[:3], 1):
        print(f"  {i}. {q.get('id')}: {q.get('context', {}).get('chinese', '')[:60]}...")

if __name__ == "__main__":
    detailed_test_parsing()