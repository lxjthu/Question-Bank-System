"""
配置文件
"""
import os

class Config:
    # 文件上传限制
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    # 允许的文件扩展名
    ALLOWED_EXTENSIONS = {'docx'}
    # 临时文件目录
    TEMP_DIR = os.path.join(os.path.dirname(__file__), 'temp')
    
    @staticmethod
    def init_temp_dir():
        """初始化临时目录"""
        if not os.path.exists(Config.TEMP_DIR):
            os.makedirs(Config.TEMP_DIR)