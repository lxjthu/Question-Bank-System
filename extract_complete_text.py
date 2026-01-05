"""
处理编码问题并完整提取.docx文档内容
"""

import zipfile
import re
import html
import os

def clean_text_for_display(text):
    """
    清理文本以处理显示问题
    """
    if text is None:
        return ""
    # 替换特殊字符
    text = text.replace('\xb2', '[²]')  # 处理上标2等特殊字符
    text = text.replace('\ufffd', '[?]')
    text = text.replace('\x00', '')
    return text

def extract_complete_text_from_docx(file_path):
    """
    完整提取.docx文件中的文本内容
    """
    print(f"正在从 {file_path} 中提取完整文本内容...")
    print("="*60)
    
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
        return ""
    
    try:
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            content = docx_zip.read('word/document.xml').decode('utf-8')
            
            # 查找 <w:t> 和 </w:t> 之间的内容
            text_matches = re.findall(r'<w:t[^>]*>(.*?)</w:t>', content, re.DOTALL)
            
            # 处理HTML实体和XML标签
            extracted_text = []
            for match in text_matches:
                # 解码HTML实体
                decoded = html.unescape(match)
                # 去除可能残留的XML标签
                clean_text = re.sub(r'<[^>]+>', '', decoded)
                if clean_text.strip():
                    extracted_text.append(clean_text)
            
            # 组织提取的文本为更可读的格式
            print(f"共提取到 {len(extracted_text)} 个文本元素")
            print("-" * 30)
            
            # 显示前50个文本元素预览
            for i, text in enumerate(extracted_text[:50]):
                clean_display = clean_text_for_display(text)
                print(f"{i+1:2d}. {clean_display}")
            
            if len(extracted_text) > 50:
                print("...")
                print(f"还有 {len(extracted_text) - 50} 个文本元素")
            
            print("\n" + "="*60)
            print("完整提取的文本内容:")
            print("-" * 30)
            
            # 组合文本内容，处理重复部分（如页眉页脚）
            complete_text = ""
            section_start = 0
            
            # 标识试卷的不同部分
            sections = {
                'header': [],
                'questions': [],
                'footer': []
            }
            
            # 尝试识别试卷结构
            current_section = 'header'
            for text in extracted_text:
                clean_text = clean_text_for_display(text)
                
                # 识别试卷部分
                if any(keyword in clean_text for keyword in ['单选题', '多选题', '简答题', '论述题', '判断题']):
                    current_section = 'questions'
                
                if current_section == 'header':
                    sections['header'].append(clean_text)
                elif current_section == 'questions':
                    sections['questions'].append(clean_text)
            
            # 显示试卷结构
            print("试卷结构分析:")
            print("-" * 40)
            
            if sections['header']:
                print("试卷头部信息:")
                for item in sections['header'][:15]:  # 只显示前15项
                    print(f"  - {item}")
            
            if sections['questions']:
                print("\n题目内容:")
                for i, item in enumerate(sections['questions']):
                    print(f"  {i+1:2d}. {item}")
            
            # 组合所有文本为一个字符串
            complete_text = '\n'.join([clean_text_for_display(t) for t in extracted_text])
            
            return complete_text
    
    except UnicodeDecodeError as e:
        print(f"解码错误: {str(e)}")
        print("尝试使用不同的编码方式...")
        
        # 尝试其他方法
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            content_bytes = docx_zip.read('word/document.xml')
            try:
                # 尝试用latin-1解码，然后转换
                content = content_bytes.decode('latin-1')
                # 查找文本内容
                text_matches = re.findall(r'<w:t[^>]*>(.*?)</w:t>', content, re.DOTALL)
                
                extracted_text = []
                for match in text_matches:
                    decoded = html.unescape(match)
                    clean_text = re.sub(r'<[^>]+>', '', decoded)
                    if clean_text.strip():
                        # 安全地清理文本
                        clean_safe = clean_text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                        extracted_text.append(clean_safe)
                
                complete_text = '\n'.join(extracted_text)
                return complete_text
            except:
                print("无法解码文档内容")
                return ""

def extract_formatted_questions(file_path):
    """
    提取并格式化试卷中的题目
    """
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
                    # 清理特殊字符
                    clean_safe = clean_text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                    extracted_text.append(clean_safe)
            
            # 识别题目格式
            print("\n识别的题目内容:")
            print("-" * 40)
            
            question_count = 0
            for i, text in enumerate(extracted_text):
                # 检查是否是题目
                if re.match(r'^\d+\.', text.strip()) or re.match(r'^\d+\."', text.strip()):
                    question_count += 1
                    print(f"\n第 {question_count} 题: {text}")
                    
                    # 查找选项 (A., B., C., D.)
                    for j in range(i+1, min(i+10, len(extracted_text))):
                        next_text = extracted_text[j]
                        if re.match(r'^[A-D]\.', next_text.strip()) or re.match(r'^[A-D]\.', next_text.strip()):
                            print(f"    选项: {next_text}")
                        elif re.match(r'^\d+\.', next_text.strip()) and j > i+1:
                            # 如果遇到下一个题目，就停止
                            break
            
            if question_count == 0:
                print("没有识别到格式化的题目")
                print("显示所有包含数字的内容:")
                for i, text in enumerate(extracted_text):
                    if any(c.isdigit() for c in text):
                        print(f"{i+1}. {text}")
    
    except Exception as e:
        print(f"提取格式化题目时出错: {str(e)}")

if __name__ == "__main__":
    file_path = r"D:\code\试卷\林业经济学题库.docx"

    # 提取完整文本
    complete_text = extract_complete_text_from_docx(file_path)
    
    if complete_text:
        print(f"\n提取完成！完整文本长度: {len(complete_text)} 字符")
        
        # 保存到文件
        output_file = r"D:\code\试卷\extracted_content.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(complete_text)
        print(f"内容已保存到: {output_file}")
    
    # 提取格式化问题
    extract_formatted_questions(file_path)