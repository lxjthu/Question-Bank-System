"""
应用工厂
"""
from flask import Flask
from config import Config

def create_app():
    """创建Flask应用实例"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # 注册蓝图
    from app.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # 首页路由
    @app.route('/')
    def index():
        from flask import render_template
        return render_template('index.html')
    
    return app