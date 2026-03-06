#!/usr/bin/env python3
"""试题管理系统 — macOS 应用启动器

PyInstaller 打包时以此文件为入口。
职责：
1. 在导入任何 app 模块之前设置 EXAM_DATA_DIR / DATABASE_URL 环境变量
2. 启动 Flask 服务器（后台线程）
3. 自动打开系统浏览器

数据目录（可写）：
  macOS 打包版：~/Library/Application Support/试题管理系统/
  普通 Python 运行：项目根目录（保持向后兼容）
"""
import os
import sys
import socket
import threading
import time
import webbrowser


# ── 1. 数据目录 ───────────────────────────────────────────────────────────────

def _data_dir() -> str:
    """返回用户可写数据目录并确保其存在。"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包环境 → macOS 标准用户数据目录
        d = os.path.join(
            os.path.expanduser('~'),
            'Library', 'Application Support', '试题管理系统',
        )
    else:
        # 普通 Python 运行 → 项目根目录
        d = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(d, exist_ok=True)
    for sub in ('uploads/images', 'temp', 'exports'):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def _setup_env(data_dir: str) -> None:
    """在导入任何 app 模块之前写好所有环境变量。"""
    os.environ.setdefault('EXAM_DATA_DIR', data_dir)
    os.environ.setdefault('DATABASE_URL', f'sqlite:///{data_dir}/exam_system.db')


# ── 2. 端口探测 ───────────────────────────────────────────────────────────────

def _free_port(start: int = 5050) -> int:
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start


# ── 3. 主函数 ─────────────────────────────────────────────────────────────────

def main() -> None:
    data_dir = _data_dir()
    _setup_env(data_dir)          # 必须在导入 app 模块之前

    # 延迟导入，确保环境变量已生效
    from app.factory import create_app

    port = _free_port()
    url = f'http://127.0.0.1:{port}'

    flask_app = create_app('production')

    # 稍后自动打开浏览器
    def _open_browser():
        time.sleep(1.8)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f'[试题管理系统] 数据目录: {data_dir}')
    print(f'[试题管理系统] 访问地址: {url}')

    flask_app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == '__main__':
    main()
