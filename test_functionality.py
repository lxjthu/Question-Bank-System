# 试卷生成器功能测试脚本

import requests
import json
import time
import os

BASE_URL = "http://127.0.0.1:5000"

def test_add_question():
    """测试添加题目功能"""
    print("\n=== 测试添加题目功能 ===")
    
    test_cases = [
        {
            "name": "添加单选题",
            "data": {
                "question_id": "test_single_001",
                "question_type": "单选",
                "content": "Python是什么类型的语言？",
                "options": ["编译型", "解释型", "汇编型", "机器语言"],
                "answer": "B",
                "explanation": "Python是解释型语言",
                "language": "zh"
            }
        },
        {
            "name": "添加多选题",
            "data": {
                "question_id": "test_multi_001",
                "question_type": "多选",
                "content": "以下哪些是Python的特点？",
                "options": ["简洁易读", "面向对象", "跨平台", "编译执行"],
                "answer": "ABC",
                "explanation": "Python是解释型语言，不是编译执行",
                "language": "zh"
            }
        },
        {
            "name": "添加是非题",
            "data": {
                "question_id": "test_tf_001",
                "question_type": "是非",
                "content": "Python中的列表是可变的",
                "options": ["是", "否"],
                "answer": "A",
                "explanation": "Python列表是可变序列",
                "language": "zh"
            }
        },
        {
            "name": "添加简答题",
            "data": {
                "question_id": "test_essay_001",
                "question_type": "简答",
                "content": "请简述Python中列表和元组的区别",
                "reference_answer": "列表是可变的，元组是不可变的",
                "explanation": "这是基础概念题",
                "language": "zh"
            }
        },
        {
            "name": "添加计算题",
            "data": {
                "question_id": "test_calc_001",
                "question_type": "简答>计算",
                "content": "计算 2 + 3 * 4 的结果",
                "reference_answer": "14",
                "explanation": "先乘除后加减：3*4=12，2+12=14",
                "language": "zh"
            }
        },
        {
            "name": "添加论述题",
            "data": {
                "question_id": "test_discuss_001",
                "question_type": "简答>论述",
                "content": "论述Python在人工智能领域的应用",
                "reference_answer": "Python在AI领域有广泛应用，包括机器学习、深度学习等",
                "explanation": "开放性题目",
                "language": "zh"
            }
        }
    ]
    
    results = []
    for test_case in test_cases:
        try:
            response = requests.post(f"{BASE_URL}/api/questions", json=test_case["data"])
            if response.status_code == 201:
                print(f"[PASS] {test_case['name']}: 成功")
                results.append({"test": test_case["name"], "status": "PASS"})
            else:
                print(f"[FAIL] {test_case['name']}: 失败 - {response.status_code} - {response.text}")
                results.append({"test": test_case["name"], "status": "FAIL", "error": response.text})
        except Exception as e:
            print(f"[ERROR] {test_case['name']}: 异常 - {str(e)}")
            results.append({"test": test_case["name"], "status": "ERROR", "error": str(e)})
    
    return results

def test_get_questions():
    """测试获取题目列表"""
    print("\n=== 测试获取题目列表 ===")
    
    try:
        response = requests.get(f"{BASE_URL}/api/questions")
        if response.status_code == 200:
            questions = response.json()
            print(f"[PASS] 获取题目列表成功，共 {len(questions)} 道题")
            return {"test": "获取题目列表", "status": "PASS", "count": len(questions)}
        else:
            print(f"[FAIL] 获取题目列表失败 - {response.status_code}")
            return {"test": "获取题目列表", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 获取题目列表异常 - {str(e)}")
        return {"test": "获取题目列表", "status": "ERROR", "error": str(e)}

def test_search_questions():
    """测试搜索题目功能"""
    print("\n=== 测试搜索题目功能 ===")
    
    test_cases = [
        {
            "name": "关键词搜索",
            "params": {"keyword": "Python"}
        },
        {
            "name": "题型搜索",
            "params": {"type": "单选"}
        },
        {
            "name": "组合搜索",
            "params": {"keyword": "Python", "type": "单选"}
        }
    ]
    
    results = []
    for test_case in test_cases:
        try:
            response = requests.get(f"{BASE_URL}/api/questions", params=test_case["params"])
            if response.status_code == 200:
                questions = response.json()
                print(f"[PASS] {test_case['name']}: 成功，找到 {len(questions)} 道题")
                results.append({"test": test_case["name"], "status": "PASS", "count": len(questions)})
            else:
                print(f"[FAIL] {test_case['name']}: 失败 - {response.status_code}")
                results.append({"test": test_case["name"], "status": "FAIL", "error": response.text})
        except Exception as e:
            print(f"[ERROR] {test_case['name']}: 异常 - {str(e)}")
            results.append({"test": test_case["name"], "status": "ERROR", "error": str(e)})
    
    return results

def test_update_question():
    """测试编辑题目功能"""
    print("\n=== 测试编辑题目功能 ===")
    
    try:
        # 先获取一道题
        response = requests.get(f"{BASE_URL}/api/questions")
        if response.status_code != 200 or len(response.json()) == 0:
            print("[SKIP] 没有可用的题目进行编辑测试")
            return {"test": "编辑题目", "status": "SKIP"}

        question_id = response.json()[0]["question_id"]

        # 更新题目
        update_data = {
            "content": "【已修改】Python是什么类型的语言？",
            "answer": "B"
        }

        response = requests.put(f"{BASE_URL}/api/questions/{question_id}", json=update_data)
        if response.status_code == 200:
            print(f"[PASS] 编辑题目成功: {question_id}")
            return {"test": "编辑题目", "status": "PASS"}
        else:
            print(f"[FAIL] 编辑题目失败 - {response.status_code} - {response.text}")
            return {"test": "编辑题目", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 编辑题目异常 - {str(e)}")
        return {"test": "编辑题目", "status": "ERROR", "error": str(e)}

def test_delete_question():
    """测试删除题目功能"""
    print("\n=== 测试删除题目功能 ===")
    
    try:
        # 先添加一道测试题
        test_question = {
            "question_id": "test_delete_001",
            "question_type": "单选",
            "content": "这是一道待删除的测试题",
            "options": ["A", "B", "C", "D"],
            "answer": "A",
            "language": "zh"
        }
        
        response = requests.post(f"{BASE_URL}/api/questions", json=test_question)
        if response.status_code != 201:
            print("[SKIP] 创建测试题失败，无法测试删除功能")
            return {"test": "删除题目", "status": "SKIP"}

        # 删除题目
        response = requests.delete(f"{BASE_URL}/api/questions/test_delete_001")
        if response.status_code == 200:
            print("[PASS] 删除题目成功")
            return {"test": "删除题目", "status": "PASS"}
        else:
            print(f"[FAIL] 删除题目失败 - {response.status_code} - {response.text}")
            return {"test": "删除题目", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 删除题目异常 - {str(e)}")
        return {"test": "删除题目", "status": "ERROR", "error": str(e)}

def test_export_questions():
    """测试导出题库功能"""
    print("\n=== 测试导出题库功能 ===")
    
    test_cases = [
        {
            "name": "导出为JSON",
            "params": {"format": "json"}
        },
        {
            "name": "导出为CSV",
            "params": {"format": "csv"}
        }
    ]
    
    results = []
    for test_case in test_cases:
        try:
            response = requests.get(f"{BASE_URL}/api/questions/export", params=test_case["params"])
            if response.status_code == 200:
                print(f"[PASS] {test_case['name']}: 成功")
                results.append({"test": test_case["name"], "status": "PASS"})
            else:
                print(f"[FAIL] {test_case['name']}: 失败 - {response.status_code}")
                results.append({"test": test_case["name"], "status": "FAIL", "error": response.text})
        except Exception as e:
            print(f"[ERROR] {test_case['name']}: 异常 - {str(e)}")
            results.append({"test": test_case["name"], "status": "ERROR", "error": str(e)})
    
    return results

def test_create_exam():
    """测试创建试卷功能"""
    print("\n=== 测试创建试卷功能 ===")
    
    try:
        exam_data = {
            "exam_id": "test_exam_001",
            "name": "测试试卷",
            "config": {
                "单选": {"count": 2, "points": 2},
                "是非": {"count": 2, "points": 1}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams", json=exam_data)
        if response.status_code == 201:
            print("[PASS] 创建试卷成功")
            return {"test": "创建试卷", "status": "PASS"}
        else:
            print(f"[FAIL] 创建试卷失败 - {response.status_code} - {response.text}")
            return {"test": "创建试卷", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 创建试卷异常 - {str(e)}")
        return {"test": "创建试卷", "status": "ERROR", "error": str(e)}

def test_generate_exam():
    """测试自动组卷功能"""
    print("\n=== 测试自动组卷功能 ===")
    
    try:
        generate_data = {
            "exam_id": "auto_exam_001",
            "name": "自动组卷测试",
            "config": {
                "单选": {"count": 1, "points": 2},
                "是非": {"count": 1, "points": 1}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=generate_data)
        if response.status_code == 200:
            exam = response.json()
            print(f"[PASS] 自动组卷成功，生成试卷包含 {len(exam['questions'])} 道题")
            return {"test": "自动组卷", "status": "PASS", "question_count": len(exam['questions'])}
        else:
            print(f"[FAIL] 自动组卷失败 - {response.status_code} - {response.text}")
            return {"test": "自动组卷", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 自动组卷异常 - {str(e)}")
        return {"test": "自动组卷", "status": "ERROR", "error": str(e)}

def test_download_template():
    """测试下载模板功能"""
    print("\n=== 测试下载模板功能 ===")
    
    try:
        response = requests.get(f"{BASE_URL}/api/templates/download")
        if response.status_code == 200:
            print("[PASS] 下载模板成功")
            return {"test": "下载模板", "status": "PASS"}
        else:
            print(f"[FAIL] 下载模板失败 - {response.status_code}")
            return {"test": "下载模板", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 下载模板异常 - {str(e)}")
        return {"test": "下载模板", "status": "ERROR", "error": str(e)}

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("开始测试试卷生成器功能")
    print("=" * 60)
    
    all_results = []
    
    # 测试题库管理功能
    all_results.extend(test_add_question())
    all_results.append(test_get_questions())
    all_results.extend(test_search_questions())
    all_results.append(test_update_question())
    all_results.append(test_delete_question())
    all_results.extend(test_export_questions())
    
    # 测试试卷生成功能
    all_results.append(test_create_exam())
    all_results.append(test_generate_exam())
    
    # 测试模板下载功能
    all_results.append(test_download_template())
    
    # 统计结果
    print("\n" + "=" * 60)
    print("测试结果统计")
    print("=" * 60)
    
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("status") == "PASS")
    failed = sum(1 for r in all_results if r.get("status") == "FAIL")
    error = sum(1 for r in all_results if r.get("status") == "ERROR")
    skipped = sum(1 for r in all_results if r.get("status") == "SKIP")
    
    print(f"总计: {total} 个测试")
    print(f"通过: {passed} 个")
    print(f"失败: {failed} 个")
    print(f"错误: {error} 个")
    print(f"跳过: {skipped} 个")
    print(f"通过率: {passed/total*100:.1f}%")
    
    # 保存测试结果
    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print("\n测试结果已保存到 test_results.json")
    
    return all_results

if __name__ == "__main__":
    run_all_tests()
