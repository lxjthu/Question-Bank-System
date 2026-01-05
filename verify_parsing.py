from word_to_csv_converter import WordToCsvConverter

def verify_all_questions():
    converter = WordToCsvConverter()
    questions = converter.parse_questions_from_word_doc(r'D:\code\试卷\林业经济学题库.docx')
    
    # Group questions by type
    by_type = {}
    for q in questions:
        qtype = q.get("type")
        if qtype not in by_type:
            by_type[qtype] = []
        by_type[qtype].append(q)
    
    print("Verification Results:")
    print("="*50)
    
    for qtype, qlist in by_type.items():
        print(f"\n{qtype.upper()} QUESTIONS ({len(qlist)} total):")
        
        # Extract and sort IDs
        ids = []
        for q in qlist:
            id_str = q.get("id", "")
            # Extract the numeric part for proper sorting
            if id_str:
                num_part = ''.join(filter(str.isdigit, id_str))
                ids.append((int(num_part), id_str))
        
        ids.sort()
        
        # Print first few and last few to verify range
        if len(ids) <= 10:
            for _, qid in ids:
                print(f"  - {qid}")
        else:
            # Print first 5 and last 5
            for _, qid in ids[:5]:
                print(f"  - {qid}")
            print("  ...")
            for _, qid in ids[-5:]:
                print(f"  - {qid}")
    
    print(f"\nSUMMARY:")
    total = sum(len(qlist) for qlist in by_type.values())
    print(f"  Total questions parsed: {total}")
    for qtype, qlist in by_type.items():
        print(f"  {qtype}: {len(qlist)}")
    
    # Verify we have the expected ranges
    print(f"\nVALIDATION:")
    sc_ids = []
    for q in by_type.get("single_choice", []):
        id_str = q.get("id", "")
        num_part = ''.join(filter(str.isdigit, id_str))
        if num_part:
            sc_ids.append(int(num_part))

    tf_ids = []
    for q in by_type.get("true_false", []):
        id_str = q.get("id", "")
        num_part = ''.join(filter(str.isdigit, id_str))
        if num_part:
            tf_ids.append(int(num_part))

    es_ids = []
    for q in by_type.get("essay", []):
        id_str = q.get("id", "")
        num_part = ''.join(filter(str.isdigit, id_str))
        if num_part:
            es_ids.append(int(num_part))

    calc_ids = []
    for q in by_type.get("calculation", []):
        id_str = q.get("id", "")
        num_part = ''.join(filter(str.isdigit, id_str))
        if num_part:
            calc_ids.append(int(num_part))
    
    print(f"  Single choice IDs: {len(sc_ids)} questions (expected 30)")
    print(f"  True/false IDs: {len(tf_ids)} questions (expected 20)")
    print(f"  Essay IDs: {len(es_ids)} questions (expected 20)") 
    print(f"  Calculation IDs: {len(calc_ids)} questions (expected 16)")
    
    if sc_ids:
        print(f"  Single choice range: {min(sc_ids)} to {max(sc_ids)}")
    if tf_ids:
        print(f"  True/false range: {min(tf_ids)} to {max(tf_ids)}")
    if es_ids:
        print(f"  Essay range: {min(es_ids)} to {max(es_ids)}")
    if calc_ids:
        print(f"  Calculation range: {min(calc_ids)} to {max(calc_ids)}")

if __name__ == "__main__":
    verify_all_questions()