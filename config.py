import os
from datetime import timedelta

class Config:
    """Base configuration class"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False
    TESTING = False
    
    # File upload settings
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Upload folder
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'csv'}
    
    # Temporary files directory
    TEMP_FOLDER = os.path.join(os.path.dirname(__file__), 'temp')
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    
    # Exports directory
    EXPORTS_FOLDER = os.path.join(os.path.dirname(__file__), 'exports')
    os.makedirs(EXPORTS_FOLDER, exist_ok=True)
    
    # Templates directory
    TEMPLATES_FOLDER = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(TEMPLATES_FOLDER, exist_ok=True)
    
    # Database settings
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.dirname(__file__), 'exam_system.db')
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