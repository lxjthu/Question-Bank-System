from word_to_csv_converter import WordToCsvConverter

def test_parsing():
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
    
    print("\n前10道题详情:")
    for i, q in enumerate(questions[:10], 1):
        print(f'{i}. {q.get("type", "未知类型")}: {q.get("id", "无ID")} - {q.get("chinese_stem", "无题干")[:50]}...')

if __name__ == "__main__":
    test_parsing()