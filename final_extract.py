"""
最终版本 - 提取并保存完整试卷内容
处理所有编码问题
"""

import zipfile
import re
import html
import os

def extract_and_save_complete_content(file_path):
    """
    提取并保存完整的文档内容，处理所有编码问题
    """
    print(f"正在从 {file_path} 中提取完整内容...")
    print("="*60)
    
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
        return
    
    try:
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            content = docx_zip.read('word/document.xml').decode('utf-8', errors='ignore')
            
            # 查找 <w:t> 和 </w:t> 之间的内容
            text_matches = re.findall(r'<w:t[^>]*>(.*?)</w:t>', content, re.DOTALL)
            
            # 处理HTML实体和XML标签
            extracted_text = []
            for match in text_matches:
                decoded = html.unescape(match)
                clean_text = re.sub(r'<[^>]+>', '', decoded)
                if clean_text.strip():
                    # 安全处理编码问题
                    clean_safe = clean_text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    extracted_text.append(clean_safe)
            
            print(f"成功提取到 {len(extracted_text)} 个文本片段")
            print("-" * 30)
            
            # 将内容组织成可读格式
            organized_content = []
            
            # 识别试卷结构（标题、题目等）
            current_section = "header"
            for text in extracted_text:
                # 如果文本包含数字开头（如题目），则归类为题目
                if re.match(r'^[\d]+[.、"]', text.strip()):
                    current_section = "questions"
                    organized_content.append(f"\n【题目】{text}")
                # 如果是选项（A. B. C. D.）
                elif re.match(r'^[A-D][.、]', text.strip()):
                    organized_content.append(f"    选项: {text}")
                # 如果是标题或页码
                elif any(keyword in text for keyword in ["学年第", "期末考试试卷", "页(共", "课程名称", "考试形式", "题号", "分值", "得分"]):
                    organized_content.append(f"【标题】{text}")
                # 其他内容
                else:
                    if current_section == "header" and not organized_content:
                        organized_content.append(f"【试卷信息】{text}")
                    else:
                        organized_content.append(text)
            
            # 创建格式化的试卷内容
            formatted_exam_content = []
            
            # 标题部分
            formatted_exam_content.append("="*60)
            formatted_exam_content.append("林业经济学（双语）试卷A卷")
            formatted_exam_content.append("="*60)
            formatted_exam_content.append("")
            
            # 添加试卷信息
            for item in organized_content:
                if "【试卷信息】" in item or "【标题】" in item:
                    formatted_exam_content.append(item.replace("【试卷信息】", "").replace("【标题】", ""))
            
            formatted_exam_content.append("")
            formatted_exam_content.append("-" * 40)
            formatted_exam_content.append("题目部分")
            formatted_exam_content.append("-" * 40)
            formatted_exam_content.append("")
            
            # 添加题目
            for item in organized_content:
                if "【题目】" in item:
                    formatted_exam_content.append(item.replace("【题目】", "题目: "))
                elif "选项:" in item:
                    formatted_exam_content.append(item)
                elif "【试卷信息】" not in item and "【标题】" not in item and item.strip():
                    # 添加其他内容（如果不是重复的页眉页脚）
                    if not any(keyword in item for keyword in ["第", "页(共", "页)", "密", "封", "线"]):
                        if not any(prev_item == item for prev_item in formatted_exam_content[-5:]):  # 避免重复
                            formatted_exam_content.append(item)
            
            # 组合成完整内容
            complete_content = "\\n".join(formatted_exam_content)
            
            # 保存到文件（使用二进制模式避免编码问题）
            output_file = r"D:\code\试卷\林业经济学试卷_完整内容.txt"
            
            # 先尝试直接写入
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    for item in formatted_exam_content:
                        # 清理可能的问题字符
                        safe_item = item.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                        f.write(safe_item + '\\n')
                print(f"内容已成功保存到: {output_file}")
            except:
                # 如果失败，使用二进制模式
                with open(output_file, 'wb') as f:
                    content_bytes = '\\n'.join(formatted_exam_content).encode('utf-8', errors='ignore')
                    f.write(content_bytes)
                print(f"内容已使用二进制模式保存到: {output_file}")
            
            # 显示前几道题目
            print("\\n前几道题目预览:")
            print("-" * 30)
            question_count = 0
            for item in organized_content:
                if "【题目】" in item and question_count < 5:
                    question_count += 1
                    print(f"{item.replace('【题目】', '题目: ')}")
                    
                    # 查找该题目的选项
                    next_items = organized_content[organized_content.index(item)+1:organized_content.index(item)+6]
                    for next_item in next_items:
                        if "选项:" in next_item:
                            print(f"  {next_item}")
                    print()
        
        print(f"\\n处理完成！共提取 {len(extracted_text)} 个文本元素")
        
    except Exception as e:
        print(f"处理文档时发生错误: {str(e)}")
        import traceback
        traceback.print_exc()

def display_exam_structure(file_path):
    """
    显示试卷的整体结构
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            content = docx_zip.read('word/document.xml').decode('utf-8', errors='ignore')
            text_matches = re.findall(r'<w:t[^>]*>(.*?)</w:t>', content, re.DOTALL)
            
            extracted_text = []
            for match in text_matches:
                decoded = html.unescape(match)
                clean_text = re.sub(r'<[^>]+>', '', decoded)
                if clean_text.strip():
                    clean_safe = clean_text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    extracted_text.append(clean_safe)
        
        print("\\n试卷结构总览:")
        print("="*50)
        
        # 确定试卷类型和信息
        for text in extracted_text[:20]:  # 检查前20个项目
            if "林业经济学" in text:
                print(f"课程名称: {text}")
            elif "期末考试试卷" in text:
                print(f"试卷类型: {text}")
            elif "学年第" in text and "20" in text:
                print(f"学年信息: {text}")
            elif "考试形式" in text:
                print(f"考试形式: {text}")
        
        # 统计题目数量
        question_count = 0
        for text in extracted_text:
            if re.match(r'^\\d+[.、"]', text.strip()):
                question_count += 1
        
        print(f"题目总数: {question_count}")
        print(f"文本片段总数: {len(extracted_text)}")
        
        # 确定题型
        question_types = []
        for text in extracted_text:
            if "单选题" in text:
                question_types.append(text)
            elif "多选题" in text:
                question_types.append(text)
            elif "简答题" in text:
                question_types.append(text)
            elif "论述题" in text:
                question_types.append(text)
            elif "判断题" in text:
                question_types.append(text)
        
        if question_types:
            print("题型:")
            for q_type in set(question_types):
                print(f"  - {q_type}")
        else:
            print("未识别到题型，但检测到题目存在")
        
    except Exception as e:
        print(f"分析试卷结构时出错: {str(e)}")

if __name__ == "__main__":
    file_path = r"D:\code\试卷\林业经济学（双语）试卷A-打印.docx"
    
    # 显示试卷结构
    display_exam_structure(file_path)
    
    # 提取并保存完整内容
    extract_and_save_complete_content(file_path)