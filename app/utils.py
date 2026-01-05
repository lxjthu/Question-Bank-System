"""
工具类和辅助函数
"""
import os
from werkzeug.utils import secure_filename

def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'docx'}

# 导入WordToCsvConverter类
try:
    from word_to_csv_converter import WordToCsvConverter
except ImportError:
    # 如果找不到word_to_csv_converter模块，则创建一个简单的实现
    class WordToCsvConverter:
        def __init__(self):
            self.warnings = []

        def parse_questions_from_word_doc(self, word_file_path):
            """模拟解析Word文档中的题目"""
            # 这里应该有实际的解析逻辑
            # 为了兼容性，返回空列表
            return []

        def create_word_template(self, template_type, output_path):
            """创建Word模板"""
            # 这里应该有实际的模板创建逻辑
            pass