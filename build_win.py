#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_win.py — 试题管理系统 Windows EXE 构建脚本

运行方式（项目根目录）：
    python build_win.py

产物：
    dist/exam-system_v<VERSION>_win64.zip

要求：
    - Windows 10/11 x64
    - Python 3.10+（已加入 PATH，推荐 python.org 下载）
    - 网络连接（首次运行需下载依赖）
"""

import sys
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

# ── 强制 stdout/stderr 使用 UTF-8，彻底消除乱码 ───────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.upper() != 'UTF-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.upper() != 'UTF-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT             = Path(__file__).parent.resolve()
VENV_DIR         = ROOT / '.build_venv'
APP_NAME         = '试题管理系统'
SPEC_FILE        = 'exam_system_win.spec'
ZIP_PREFIX       = 'exam-system'

PACKAGES = [
    'flask',
    'flask-sqlalchemy',
    'python-docx>=1.1',
    'lxml',
    'openai',
    'python-dotenv',
    'pyinstaller',
]
MIRRORS = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple',
    'https://pypi.org/simple',
]


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def banner(msg: str):
    line = '=' * 60
    print(f'\n{line}\n  {msg}\n{line}')

def step(n: int, total: int, msg: str):
    print(f'\n[{n}/{total}] {msg}')

def ok(msg: str):
    print(f'[OK] {msg}')

def warn(msg: str):
    print(f'[警告] {msg}')

def fail(msg: str):
    print(f'\n[错误] {msg}', file=sys.stderr)
    sys.exit(1)

def run(cmd, check=True, **kwargs):
    """执行子进程，默认失败时抛出异常。"""
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        raise RuntimeError(f'命令失败（返回码 {result.returncode}）')
    return result


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    # ── 读取版本号 ────────────────────────────────────────────────────────────
    version_file = ROOT / 'VERSION'
    if not version_file.exists():
        fail('未找到 VERSION 文件')
    version  = version_file.read_text(encoding='utf-8').strip()
    zip_name = f'{ZIP_PREFIX}_v{version}_win64.zip'
    dist_app = ROOT / 'dist' / APP_NAME
    dist_zip = ROOT / 'dist' / zip_name

    banner(f'{APP_NAME} Windows 打包脚本  v{version}')
    print(f'Python  : {sys.version.split()[0]}  ({sys.executable})')
    print(f'根目录  : {ROOT}')
    print(f'输出 zip: dist/{zip_name}')

    # ── Step 1：创建隔离构建 venv ─────────────────────────────────────────────
    step(1, 4, f'创建隔离构建环境：{VENV_DIR.name}')
    if VENV_DIR.exists():
        print(f'  删除旧环境 {VENV_DIR.name} ...')
        shutil.rmtree(VENV_DIR)
    run([sys.executable, '-m', 'venv', str(VENV_DIR)])
    ok(f'venv 创建完成：{VENV_DIR}')

    venv_python      = VENV_DIR / 'Scripts' / 'python.exe'
    venv_pip         = VENV_DIR / 'Scripts' / 'pip.exe'
    venv_pyinstaller = VENV_DIR / 'Scripts' / 'pyinstaller.exe'

    # ── Step 2：安装依赖（三镜像回退）────────────────────────────────────────
    step(2, 4, '安装构建依赖...')
    run([str(venv_python), '-m', 'pip', 'install', '--upgrade', 'pip', '--quiet'])

    installed = False
    for mirror in MIRRORS:
        print(f'  尝试镜像：{mirror}')
        result = run(
            [str(venv_pip), 'install', '--quiet', '-i', mirror] + PACKAGES,
            check=False,
        )
        if result.returncode == 0:
            ok('依赖安装完成')
            installed = True
            break
        warn(f'镜像失败，切换下一个...')

    if not installed:
        fail('所有镜像均失败，请检查网络连接后重试')

    # ── Step 3：PyInstaller 打包 ──────────────────────────────────────────────
    step(3, 4, f'开始 PyInstaller 打包（{SPEC_FILE}）...')

    for d in ['build', 'dist']:
        p = ROOT / d
        if p.exists():
            print(f'  清理旧目录：{d}/')
            shutil.rmtree(p)

    spec_path = ROOT / SPEC_FILE
    if not spec_path.exists():
        fail(f'未找到 spec 文件：{spec_path}')

    run(
        [str(venv_pyinstaller), str(spec_path), '-y'],
        cwd=str(ROOT),
    )

    exe_path = dist_app / f'{APP_NAME}.exe'
    if not exe_path.exists():
        fail(f'未找到 EXE：{exe_path}\nPyInstaller 可能打包失败，请检查上方日志')
    ok(f'EXE 构建完成：{exe_path}')

    # ── Step 4：打包为 zip ────────────────────────────────────────────────────
    step(4, 4, f'打包为 zip 分发包：{zip_name}')

    if dist_zip.exists():
        dist_zip.unlink()

    count = 0
    with zipfile.ZipFile(dist_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(dist_app.rglob('*')):
            if f.is_file():
                arc = APP_NAME + '/' + f.relative_to(dist_app).as_posix()
                zf.write(f, arc)
                count += 1

    size_mb = dist_zip.stat().st_size / 1024 / 1024
    ok(f'zip 已生成：{dist_zip}')
    print(f'     共 {count} 个文件，{size_mb:.1f} MB')

    # ── 完成 ──────────────────────────────────────────────────────────────────
    banner('构建成功！')
    print(f'zip 路径  : dist\\{zip_name}')
    print(f'\n分发方式：')
    print(f'  1. 将 dist\\{zip_name} 发送给用户')
    print(f'  2. 用户解压后双击「{APP_NAME}\\{APP_NAME}.exe」启动')
    print(f'  3. 浏览器自动打开，首次运行数据库自动初始化')
    print(f'\n数据目录（题库/数据库/导出文件）：')
    print(f'  %APPDATA%\\{APP_NAME}\\')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        fail('用户中断')
    except RuntimeError as e:
        fail(str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        fail(f'未预期错误：{e}')
