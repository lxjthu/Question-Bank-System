from word_to_csv_converter import convert_word_to_csv, parse_csv_to_questions

# Test the conversion function
test_file_path = 'temp/test_questions.docx'
csv_path = convert_word_to_csv(test_file_path)

print(f"Word document converted to CSV: {csv_path}")

# Parse the CSV to check the results
questions_data = parse_csv_to_questions(csv_path)
print(f"Number of questions parsed: {len(questions_data)}")

for i, q in enumerate(questions_data):
    print(f"\nQuestion {i+1}:")
    print(f"  Type: {q['type']}")
    print(f"  Content: {q['content']}")
    print(f"  Options: {q['options']}")
    print(f"  Answer: {q['answer']}")
    print(f"  Reference Answer: {q['reference_answer']}")
    print(f"  Explanation: {q['explanation']}")