# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 试题管理系统 Windows 版

构建命令（在项目根目录执行）：
    pyinstaller exam_system_win.spec

目标平台：Windows 10/11 x64
产物：dist\试题管理系统\ 目录（onedir 模式）
      build_win.bat 会进一步打包为 zip 分发包
"""
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# ── 读取版本号 ─────────────────────────────────────────────────────────────────
with open('VERSION', 'r', encoding='utf-8') as _f:
    _VERSION = _f.read().strip()

# ── 数据文件 ──────────────────────────────────────────────────────────────────
docx_datas   = collect_data_files('docx')
jinja2_datas = collect_data_files('jinja2')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Flask 模板（HTML 页面）
        ('app/templates', 'app/templates'),
        # python-docx + jinja2 内部数据
        *docx_datas,
        *jinja2_datas,
    ],
    hiddenimports=[
        # SQLAlchemy 方言
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.pysqlite',
        'sqlalchemy.pool',
        'sqlalchemy.event',
        # Flask 相关
        'flask',
        'flask_sqlalchemy',
        'jinja2',
        'jinja2.ext',
        'werkzeug',
        'werkzeug.routing',
        'werkzeug.middleware',
        'click',
        'itsdangerous',
        'markupsafe',
        # python-docx
        'docx',
        'docx.oxml',
        'docx.oxml.ns',
        'lxml',
        'lxml.etree',
        'lxml._elementpath',
        # DeepSeek 直出
        'openai',
        'openai._models',
        'openai.resources',
        'dotenv',
        'httpx',
        'httpcore',
        'anyio',
        'certifi',
        'charset_normalizer',
        # 标准库
        'email.mime.text',
        'email.mime.multipart',
        'uuid',
        'json',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'sentence_transformers',
        'qdrant_client',
        'transformers',
        'paddle', 'paddleocr',
        'numpy', 'scipy', 'sklearn', 'scikit_learn',
        'matplotlib', 'pandas',
        'IPython', 'jupyter', 'ipykernel',
        'PyQt5', 'PyQt6', 'PySide6',
        'tkinter', '_tkinter',
        'PIL', 'Pillow',
        'cv2', 'opencv',
        'sympy', 'mpmath',
        'rank_bm25', 'jieba',
        'test', 'tests',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='试题管理系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # Windows 上 UPX 可减小体积
    upx_exclude=[],
    console=False,      # 不显示命令行窗口
    icon=None,          # 替换为 'assets/icon.ico' 可添加自定义图标
    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='试题管理系统',
)
