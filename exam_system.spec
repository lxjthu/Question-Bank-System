# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 试题管理系统 macOS 版

构建命令（在项目根目录执行）：
    pyinstaller exam_system.spec

目标平台：macOS arm64（Apple Silicon / M1+）
如需同时支持 Intel Mac，将 target_arch 改为 'universal2'
"""
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# ── 数据文件 ──────────────────────────────────────────────────────────────────
# python-docx 自带的 Word 模板文件（必须包含，否则无法创建 .docx）
docx_datas = collect_data_files('docx')
# Jinja2 内置模板
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
        # SQLAlchemy 方言（必须显式声明，否则运行时找不到 SQLite 驱动）
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
        # 标准库可能被遗漏
        'email.mime.text',
        'email.mime.multipart',
        'uuid',
        'json',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除所有 AI/ML 重量级依赖（它们是可选功能，不打包进 DMG）
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
        'openai',           # AI 相关（打包版不使用）
        'httpx', 'httpcore', 'anyio',
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
    upx=False,          # macOS 上 UPX 可能导致签名问题，关闭
    console=False,      # 不显示终端窗口
    disable_windowed_traceback=False,
    argv_emulation=True,          # macOS .app 需要此选项处理文件关联
    target_arch='arm64',          # Apple Silicon (M1/M2/M3)
    # target_arch='universal2',   # 取消注释则同时支持 Intel + Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='试题管理系统',
)

app = BUNDLE(
    coll,
    name='试题管理系统.app',
    icon=None,          # 替换为 'assets/icon.icns' 可添加自定义图标
    bundle_identifier='com.examSystem.questionBank',
    info_plist={
        'CFBundleName': '试题管理系统',
        'CFBundleDisplayName': '试题管理系统',
        'CFBundleVersion': '1.7.0',
        'CFBundleShortVersionString': '1.7.0',
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'NSAppleScriptEnabled': False,
        'LSMinimumSystemVersion': '12.0',       # macOS Monterey+
        'LSUIElement': False,                    # 显示在 Dock
        'NSHumanReadableCopyright': '',
        'CFBundleDocumentTypes': [],
    },
)
