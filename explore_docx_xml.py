"""
探索.docx文件的内部结构
.docx文件本质上是一个ZIP压缩包
"""

import zipfile
import os
from xml.dom import minidom

def explore_docx_internal_structure(file_path):
    """
    探索.docx文件的内部XML结构
    """
    print(f"正在探索 .docx 文件内部结构: {file_path}")
    print("="*60)
    
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 - {file_path}")
        return
    
    try:
        # 读取ZIP文件内容
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            file_list = docx_zip.namelist()
            print("文件内部结构:")
            print("-" * 30)
            for file_name in file_list:
                print(f"  {file_name}")
            
            # 读取主要的XML文件
            print("\n正在读取主要内容...")
            print("-" * 30)
            
            # 读取document.xml
            if 'word/document.xml' in file_list:
                print("\nword/document.xml 内容 (前1000字符):")
                print("-" * 40)
                doc_content = docx_zip.read('word/document.xml').decode('utf-8')
                print(doc_content[:1000] + ("..." if len(doc_content) > 1000 else ""))
                
                # 尝试解析XML来获取文本
                try:
                    dom = minidom.parseString(docx_zip.read('word/document.xml'))
                    text_elements = dom.getElementsByTagName('w:t')
                    
                    print(f"\n从XML中找到 {len(text_elements)} 个文本元素:")
                    print("-" * 40)
                    
                    all_text = []
                    for elem in text_elements:
                        if elem.firstChild:
                            text = elem.firstChild.nodeValue
                            if text.strip():  # 只显示非空文本
                                all_text.append(text)
                                print(f"- {text}")
                    
                    if all_text:
                        print(f"\n全文本内容:")
                        print("-" * 30)
                        print(" ".join(all_text))
                
                except Exception as e:
                    print(f"解析XML时出错: {str(e)}")
            
            # 读取页眉页脚
            print("\n正在检查页眉页脚...")
            print("-" * 30)
            
            for file_name in file_list:
                if file_name.startswith('word/header') or file_name.startswith('word/footer'):
                    print(f"\n{file_name}:")
                    try:
                        header_footer_content = docx_zip.read(file_name).decode('utf-8')
                        print(header_footer_content[:500] + ("..." if len(header_footer_content) > 500 else ""))
                    except:
                        print("  无法解码此文件")
            
            # 读取settings.xml查看文档设置
            if 'word/settings.xml' in file_list:
                print(f"\nword/settings.xml:")
                settings_content = docx_zip.read('word/settings.xml').decode('utf-8')
                print(settings_content[:500] + ("..." if len(settings_content) > 500 else ""))

    except Exception as e:
        print(f"读取 .docx 文件时发生错误: {str(e)}")
        import traceback
        traceback.print_exc()

def extract_text_from_docx_xml(file_path):
    """
    从docx的XML结构中提取文本
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as docx_zip:
            # 读取word/document.xml
            if 'word/document.xml' in docx_zip.namelist():
                content = docx_zip.read('word/document.xml').decode('utf-8')
                
                # 简单正则表达式或字符串方法提取文本
                # 在Word XML中，文本标签是 <w:t>
                import re
                # 查找 <w:t> 和 </w:t> 之间的内容
                text_matches = re.findall(r'<w:t[^>]*>(.*?)</w:t>', content, re.DOTALL)
                
                # 需要处理XML实体转义
                import html
                extracted_text = []
                for match in text_matches:
                    # 解码HTML实体
                    decoded = html.unescape(match)
                    # 去除XML标签（如果有的话）
                    clean_text = re.sub(r'<[^>]+>', '', decoded)
                    if clean_text.strip():
                        extracted_text.append(clean_text)
                
                return extracted_text
    
    except Exception as e:
        print(f"从XML提取文本时出错: {str(e)}")
        return []

if __name__ == "__main__":
    file_path = r"D:\code\试卷\林业经济学（双语）试卷A-打印.docx"
    
    # 探索内部结构
    explore_docx_internal_structure(file_path)
    
    print("\n" + "="*60)
    print("尝试从XML中提取文本:")
    print("-" * 30)
    
    xml_text = extract_text_from_docx_xml(file_path)
    if xml_text:
        print(f"提取到 {len(xml_text)} 个文本片段:")
        for i, text in enumerate(xml_text):
            print(f"{i+1}. {text}")
    else:
        print("未能从XML中提取到文本")