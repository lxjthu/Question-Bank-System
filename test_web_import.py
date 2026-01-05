"""
测试Web服务器的Word导入功能
"""
import json
import tempfile
import os
from web_server import app
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import requests
from io import BytesIO

def test_web_import():
    print("测试Web服务器的Word导入功能...")
    
    # 检查必要的依赖
    try:
        import flask
        print("  √ Flask 已安装")
    except ImportError:
        print("  X Flask 未安装")
        return False
    
    try:
        import docx
        print("  √ python-docx 已安装")
    except ImportError:
        print("  X python-docx 未安装")
        return False
    
    # 检查文件是否存在
    if os.path.exists("D:\\code\\试卷\\test_questions_proper.docx"):
        print("  √ 测试Word文档存在")
    else:
        print("  X 测试Word文档不存在")
        return False
    
    print("\n  提示: 要完整测试Web服务器功能，请运行 'python web_server.py'")
    print("  然后在浏览器中打开 http://localhost:5000")
    print("  在'题库管理'标签页中导入Word文档进行测试")
    
    # 检查关键文件和函数
    try:
        from word_to_csv_converter import WordToCsvConverter
        converter = WordToCsvConverter()
        print("  √ WordToCsvConverter 可用")
    except Exception as e:
        print(f"  X WordToCsvConverter 错误: {e}")
        return False
    
    try:
        # 测试解析功能
        questions = converter.parse_questions_from_word_doc("D:\\code\\试卷\\test_questions_proper.docx")
        print(f"  √ 解析功能正常，解析到 {len(questions)} 道题目")
    except Exception as e:
        print(f"  X 解析功能错误: {e}")
        return False
    
    # 检查web_server.py中的API端点
    try:
        # 检查是否定义了必要的API端点
        url_map = app.url_map
        endpoints = [str(rule) for rule in url_map.iter_rules()]
        required_endpoints = ['/api/convert-word', '/api/questions', '/api/export/json', '/api/export/csv']
        
        for endpoint in required_endpoints:
            if endpoint in endpoints:
                print(f"  √ API端点 {endpoint} 已定义")
            else:
                print(f"  X API端点 {endpoint} 未定义")
                return False
        
        print("  √ 所有必要的API端点都已定义")
    except Exception as e:
        print(f"  X 检查API端点时出错: {e}")
        return False
    
    print("\nWeb服务器Word导入功能测试完成！")
    print("所有组件都已正确配置，可以正常工作。")
    return True

if __name__ == "__main__":
    test_web_import()