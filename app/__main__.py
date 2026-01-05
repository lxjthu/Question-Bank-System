"""
主服务器文件
林业经济学（双语）试题管理系统
"""
from flask import Flask, render_template
from config import Config
import os

# 创建Flask应用
app = Flask(__name__)
app.config.from_object(Config)

# 注册蓝图
from app.routes import api_bp
app.register_blueprint(api_bp, url_prefix='/api')

# 首页路由
@app.route('/')
def index():
    """返回主页面"""
    return render_template('index.html')

def create_app():
    """应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # 注册蓝图
    from app.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # 首页路由
    @app.route('/')
    def index():
        return render_template('index.html')
    
    return app

if __name__ == '__main__':
    print("林业经济学（双语）试题管理系统")
    print("服务器启动中...")
    
    # 初始化临时目录
    Config.init_temp_dir()
    
    # 创建应用
    app = create_app()
    
    # 运行服务器
    app.run(debug=True, host='0.0.0.0', port=5000)