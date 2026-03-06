import os

# 数据根目录：
#   - 普通运行：项目根目录（__file__ 所在目录）
#   - PyInstaller 打包：由 launcher.py 预先写入 EXAM_DATA_DIR，指向
#     ~/Library/Application Support/试题管理系统（macOS）
_DATA_BASE = (
    os.environ.get('EXAM_DATA_DIR')
    or os.path.dirname(os.path.abspath(__file__))
)


class Config:
    """Base configuration class"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False
    TESTING = False

    # File upload settings
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'csv'}

    # Writable directories — resolved against _DATA_BASE at import time.
    # os.makedirs calls removed from class body; factory.py creates them at startup.
    UPLOAD_FOLDER   = os.path.join(_DATA_BASE, 'uploads')
    TEMP_FOLDER     = os.path.join(_DATA_BASE, 'temp')
    EXPORTS_FOLDER  = os.path.join(_DATA_BASE, 'exports')
    TEMPLATES_FOLDER = os.path.join(_DATA_BASE, 'templates')

    # Database
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL')
        or 'sqlite:///' + os.path.join(_DATA_BASE, 'exam_system.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'  # In-memory database for test isolation


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}