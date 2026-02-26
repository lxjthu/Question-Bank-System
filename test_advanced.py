# 试卷生成器高级功能测试脚本

import requests
import json
import os

BASE_URL = "http://127.0.0.1:5000"

def test_import_questions():
    """测试导入题目功能"""
    print("\n=== 测试导入题目功能 ===")
    
    # 检查是否有测试用的Word文件
    test_files = [
        "题库导入模板.txt"
    ]
    
    results = []
    for test_file in test_files:
        if not os.path.exists(test_file):
            print(f"[SKIP] {test_file}: 文件不存在")
            results.append({"test": f"导入{test_file}", "status": "SKIP"})
            continue
        
        try:
            with open(test_file, 'rb') as f:
                files = {'file': (test_file, f, 'text/plain')}
                response = requests.post(f"{BASE_URL}/api/questions/import", files=files)
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"[PASS] 导入{test_file}: 成功，导入 {result.get('count', 0)} 道题")
                    results.append({"test": f"导入{test_file}", "status": "PASS", "count": result.get('count', 0)})
                else:
                    print(f"[FAIL] 导入{test_file}: 失败 - {response.status_code} - {response.text}")
                    results.append({"test": f"导入{test_file}", "status": "FAIL", "error": response.text})
        except Exception as e:
            print(f"[ERROR] 导入{test_file}: 异常 - {str(e)}")
            results.append({"test": f"导入{test_file}", "status": "ERROR", "error": str(e)})
    
    return results

def test_replace_question():
    """测试题目替换功能"""
    print("\n=== 测试题目替换功能 ===")
    
    try:
        # 先创建一个试卷
        exam_data = {
            "exam_id": "test_replace_exam",
            "name": "测试替换试卷",
            "config": {
                "单选": {"count": 2, "points": 2}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=exam_data)
        if response.status_code != 200:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "题目替换", "status": "SKIP"}
        
        exam = response.json()
        if len(exam['questions']) == 0:
            print(f"[SKIP] 试卷中没有题目")
            return {"test": "题目替换", "status": "SKIP"}
        
        # 获取第一道题的ID
        old_question_id = exam['questions'][0]['question_id']
        
        # 获取同类型的其他题目
        response = requests.get(f"{BASE_URL}/api/questions", params={"type": "单选"})
        if response.status_code != 200:
            print(f"[SKIP] 获取题目列表失败")
            return {"test": "题目替换", "status": "SKIP"}
        
        questions = response.json()
        # 找一个不在试卷中的题目
        new_question = None
        for q in questions:
            if q['question_id'] != old_question_id:
                new_question = q
                break
        
        if not new_question:
            print(f"[SKIP] 没有可替换的题目")
            return {"test": "题目替换", "status": "SKIP"}
        
        # 替换题目
        replace_data = {
            "old_question_id": old_question_id,
            "new_question_id": new_question['question_id']
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/test_replace_exam/replace_question", json=replace_data)
        if response.status_code == 200:
            print(f"[PASS] 题目替换成功")
            return {"test": "题目替换", "status": "PASS"}
        else:
            print(f"[FAIL] 题目替换失败 - {response.status_code} - {response.text}")
            return {"test": "题目替换", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 题目替换异常 - {str(e)}")
        return {"test": "题目替换", "status": "ERROR", "error": str(e)}

def test_confirm_exam():
    """测试试卷最终决定功能"""
    print("\n=== 测试试卷最终决定功能 ===")
    
    try:
        # 先创建一个试卷
        exam_data = {
            "exam_id": "test_confirm_exam",
            "name": "测试确认试卷",
            "config": {
                "单选": {"count": 1, "points": 2}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=exam_data)
        if response.status_code != 200:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "试卷确认", "status": "SKIP"}
        
        exam = response.json()
        if len(exam['questions']) == 0:
            print(f"[SKIP] 试卷中没有题目")
            return {"test": "试卷确认", "status": "SKIP"}
        
        question_id = exam['questions'][0]['question_id']
        
        # 确认试卷
        response = requests.post(f"{BASE_URL}/api/exams/test_confirm_exam/confirm")
        if response.status_code == 200:
            print(f"[PASS] 试卷确认成功")
            
            # 检查题目是否被标记为已使用
            response = requests.get(f"{BASE_URL}/api/questions")
            questions = response.json()
            question = next((q for q in questions if q['question_id'] == question_id), None)
            
            if question and question.get('is_used'):
                print(f"[PASS] 题目已正确标记为已使用")
            else:
                print(f"[FAIL] 题目未被标记为已使用")
                return {"test": "试卷确认", "status": "FAIL", "error": "题目未被标记"}
            
            # 测试撤销功能
            response = requests.post(f"{BASE_URL}/api/exams/test_confirm_exam/revert_confirmation")
            if response.status_code == 200:
                print(f"[PASS] 撤销确认成功")
                
                # 检查题目是否被取消标记
                response = requests.get(f"{BASE_URL}/api/questions")
                questions = response.json()
                question = next((q for q in questions if q['question_id'] == question_id), None)
                
                if question and not question.get('is_used'):
                    print(f"[PASS] 题目已正确取消标记")
                    return {"test": "试卷确认", "status": "PASS"}
                else:
                    print(f"[FAIL] 题目未被取消标记")
                    return {"test": "试卷确认", "status": "FAIL", "error": "题目未被取消标记"}
            else:
                print(f"[FAIL] 撤销确认失败 - {response.status_code}")
                return {"test": "试卷确认", "status": "FAIL", "error": "撤销失败"}
        else:
            print(f"[FAIL] 试卷确认失败 - {response.status_code} - {response.text}")
            return {"test": "试卷确认", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 试卷确认异常 - {str(e)}")
        return {"test": "试卷确认", "status": "ERROR", "error": str(e)}

def test_prevent_duplicate():
    """测试防重复功能"""
    print("\n=== 测试防重复功能 ===")
    
    try:
        # 先创建一个试卷并确认
        exam_data = {
            "exam_id": "test_duplicate_exam",
            "name": "测试防重复试卷",
            "config": {
                "单选": {"count": 1, "points": 2}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=exam_data)
        if response.status_code != 200:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "防重复", "status": "SKIP"}
        
        exam = response.json()
        if len(exam['questions']) == 0:
            print(f"[SKIP] 试卷中没有题目")
            return {"test": "防重复", "status": "SKIP"}
        
        # 确认试卷
        response = requests.post(f"{BASE_URL}/api/exams/test_duplicate_exam/confirm")
        if response.status_code != 200:
            print(f"[SKIP] 确认试卷失败")
            return {"test": "防重复", "status": "SKIP"}
        
        # 尝试再次生成试卷，应该不会选择已使用的题目
        # 只请求1道题，因为只有1道未使用的单选题
        response = requests.post(f"{BASE_URL}/api/exams/generate", json={
            "exam_id": "test_duplicate_exam_2",
            "name": "测试防重复试卷2",
            "config": {
                "单选": {"count": 1, "points": 2}
            }
        })

        if response.status_code == 200:
            exam2 = response.json()
            # 检查新试卷是否包含已使用的题目
            used_question_ids = {q['question_id'] for q in exam['questions']}
            new_question_ids = {q['question_id'] for q in exam2['questions']}

            overlap = used_question_ids & new_question_ids

            if len(overlap) == 0:
                print(f"[PASS] 防重复功能正常，新试卷未使用已采用的题目")
                return {"test": "防重复", "status": "PASS"}
            else:
                print(f"[FAIL] 防重复功能失效，新试卷使用了已采用的题目: {overlap}")
                return {"test": "防重复", "status": "FAIL", "error": "发现重复题目"}
        else:
            print(f"[FAIL] 生成第二份试卷失败 - {response.status_code}")
            return {"test": "防重复", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 防重复测试异常 - {str(e)}")
        return {"test": "防重复", "status": "ERROR", "error": str(e)}

def test_export_exam_to_word():
    """测试导出试卷为Word功能"""
    print("\n=== 测试导出试卷为Word功能 ===")
    
    try:
        # 先创建一个试卷
        exam_data = {
            "exam_id": "test_export_exam",
            "name": "测试导出试卷",
            "config": {
                "单选": {"count": 1, "points": 2},
                "是非": {"count": 1, "points": 1}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=exam_data)
        if response.status_code != 200:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "导出Word", "status": "SKIP"}
        
        # 导出试卷
        response = requests.get(f"{BASE_URL}/api/exams/test_export_exam/export")
        if response.status_code == 200:
            print(f"[PASS] 导出试卷为Word成功")
            return {"test": "导出Word", "status": "PASS"}
        else:
            print(f"[FAIL] 导出试卷为Word失败 - {response.status_code} - {response.text}")
            return {"test": "导出Word", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 导出Word异常 - {str(e)}")
        return {"test": "导出Word", "status": "ERROR", "error": str(e)}

def test_add_question_to_exam():
    """测试手动添加题目到试卷"""
    print("\n=== 测试手动添加题目到试卷 ===")
    
    try:
        # 创建一个空试卷
        exam_data = {
            "exam_id": "test_manual_exam",
            "name": "测试手动添加试卷",
            "config": {}
        }
        
        response = requests.post(f"{BASE_URL}/api/exams", json=exam_data)
        if response.status_code != 201:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "手动添加题目", "status": "SKIP"}
        
        # 获取一道题
        response = requests.get(f"{BASE_URL}/api/questions")
        if response.status_code != 200 or len(response.json()) == 0:
            print(f"[SKIP] 没有可用的题目")
            return {"test": "手动添加题目", "status": "SKIP"}
        
        question_id = response.json()[0]['question_id']
        
        # 添加题目到试卷
        add_data = {"question_id": question_id}
        response = requests.post(f"{BASE_URL}/api/exams/test_manual_exam/add_question", json=add_data)
        
        if response.status_code == 200:
            exam = response.json()
            if len(exam['questions']) > 0:
                print(f"[PASS] 手动添加题目成功")
                return {"test": "手动添加题目", "status": "PASS"}
            else:
                print(f"[FAIL] 题目未添加到试卷")
                return {"test": "手动添加题目", "status": "FAIL", "error": "题目未添加"}
        else:
            print(f"[FAIL] 手动添加题目失败 - {response.status_code} - {response.text}")
            return {"test": "手动添加题目", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 手动添加题目异常 - {str(e)}")
        return {"test": "手动添加题目", "status": "ERROR", "error": str(e)}

def test_remove_question_from_exam():
    """测试从试卷中移除题目"""
    print("\n=== 测试从试卷中移除题目 ===")
    
    try:
        # 创建一个试卷
        exam_data = {
            "exam_id": "test_remove_exam",
            "name": "测试移除题目试卷",
            "config": {
                "单选": {"count": 2, "points": 2}
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/exams/generate", json=exam_data)
        if response.status_code != 200:
            print(f"[SKIP] 创建测试试卷失败")
            return {"test": "移除题目", "status": "SKIP"}
        
        exam = response.json()
        if len(exam['questions']) == 0:
            print(f"[SKIP] 试卷中没有题目")
            return {"test": "移除题目", "status": "SKIP"}
        
        question_id = exam['questions'][0]['question_id']
        
        # 移除题目
        response = requests.delete(f"{BASE_URL}/api/exams/test_remove_exam/remove_question/{question_id}")

        if response.status_code == 200:
            exam = response.json()
            if len(exam['questions']) == 0:  # 应该剩0道题（因为原来只有1道）
                print(f"[PASS] 移除题目成功")
                return {"test": "移除题目", "status": "PASS"}
            else:
                print(f"[FAIL] 题目数量不正确，期望0道，实际{len(exam['questions'])}道")
                return {"test": "移除题目", "status": "FAIL", "error": "题目数量不正确"}
        else:
            print(f"[FAIL] 移除题目失败 - {response.status_code} - {response.text}")
            return {"test": "移除题目", "status": "FAIL", "error": response.text}
    except Exception as e:
        print(f"[ERROR] 移除题目异常 - {str(e)}")
        return {"test": "移除题目", "status": "ERROR", "error": str(e)}

def run_advanced_tests():
    """运行所有高级测试"""
    print("=" * 60)
    print("开始测试试卷生成器高级功能")
    print("=" * 60)
    
    all_results = []
    
    # 测试导入功能
    all_results.extend(test_import_questions())
    
    # 测试题目替换功能
    all_results.append(test_replace_question())
    
    # 测试试卷确认功能
    all_results.append(test_confirm_exam())
    
    # 测试防重复功能
    all_results.append(test_prevent_duplicate())
    
    # 测试导出Word功能
    all_results.append(test_export_exam_to_word())
    
    # 测试手动添加题目
    all_results.append(test_add_question_to_exam())
    
    # 测试移除题目
    all_results.append(test_remove_question_from_exam())
    
    # 统计结果
    print("\n" + "=" * 60)
    print("高级功能测试结果统计")
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
    if total > 0:
        print(f"通过率: {passed/total*100:.1f}%")
    
    # 保存测试结果
    with open("test_advanced_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print("\n测试结果已保存到 test_advanced_results.json")
    
    return all_results

if __name__ == "__main__":
    run_advanced_tests()
