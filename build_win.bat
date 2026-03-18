@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================================
:: build_win.bat — 试题管理系统 Windows EXE 构建脚本
::
:: 使用方法（在项目根目录双击或命令行执行）：
::   build_win.bat
::
:: 产物：
::   dist\exam-system_v<VERSION>_win64.zip
::
:: 要求：
::   - Windows 10/11 x64
::   - Python 3.10+（已加入 PATH，推荐从 python.org 下载）
::   - 网络连接（首次运行需下载依赖）
:: ============================================================

set VENV_DIR=.build_venv
set APP_NAME=试题管理系统

:: ── 读取版本号 ────────────────────────────────────────────────────────────────
set /p VERSION=<VERSION
set ZIP_NAME=exam-system_v%VERSION%_win64.zip

echo.
echo ===========================================================
echo  %APP_NAME% Windows 打包脚本 v%VERSION%
echo ===========================================================
echo.

:: ── 检查 Python ───────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装并加入 PATH。
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] 使用 %PY_VER%

:: ── 创建隔离构建 venv ─────────────────────────────────────────────────────────
echo.
echo [1/4] 创建隔离构建环境：%VENV_DIR%
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
python -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [错误] 创建 venv 失败
    pause & exit /b 1
)
call "%VENV_DIR%\Scripts\activate.bat"

:: ── 安装依赖（三镜像回退）────────────────────────────────────────────────────
echo.
echo [2/4] 安装构建依赖...
pip install --upgrade pip --quiet

set MIRRORS=^
    https://pypi.tuna.tsinghua.edu.cn/simple ^
    https://mirrors.aliyun.com/pypi/simple ^
    https://pypi.org/simple

set PACKAGES=flask flask-sqlalchemy "python-docx>=1.1" lxml openai python-dotenv pyinstaller

for %%m in (%MIRRORS%) do (
    echo     尝试镜像：%%m
    pip install --quiet -i %%m %PACKAGES% && goto :deps_ok
)
echo [错误] 所有镜像均失败，请检查网络
call deactivate & pause & exit /b 1

:deps_ok
echo [OK] 依赖安装完成

:: ── PyInstaller 打包 ──────────────────────────────────────────────────────────
echo.
echo [3/4] 开始打包（PyInstaller）...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

pyinstaller exam_system_win.spec
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败
    call deactivate & pause & exit /b 1
)

set DIST_DIR=dist\%APP_NAME%
if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo [错误] 未找到 %DIST_DIR%\%APP_NAME%.exe，打包可能失败
    call deactivate & pause & exit /b 1
)
echo [OK] .exe 构建完成：%DIST_DIR%\%APP_NAME%.exe

:: ── 打包为 zip ────────────────────────────────────────────────────────────────
echo.
echo [4/4] 打包为 zip 分发包...
if exist "dist\%ZIP_NAME%" del "dist\%ZIP_NAME%"

python -c "
import zipfile, pathlib, sys
dist = pathlib.Path(r'dist/%APP_NAME%')
zip_path = pathlib.Path(r'dist/%ZIP_NAME%')
top = '%APP_NAME%'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for f in sorted(dist.rglob('*')):
        if f.is_file():
            arc = top + '/' + str(f.relative_to(dist)).replace(chr(92), '/')
            zf.write(f, arc)
print('[OK] zip 已生成：' + str(zip_path))
"
if errorlevel 1 (
    echo [错误] zip 打包失败
    call deactivate & pause & exit /b 1
)

call deactivate

:: ── 完成 ──────────────────────────────────────────────────────────────────────
echo.
echo ===========================================================
echo  构建成功！
echo  zip 路径：dist\%ZIP_NAME%
echo ===========================================================
echo.
echo 分发方式：
echo   1. 将 dist\%ZIP_NAME% 发送给用户
echo   2. 用户解压后双击「%APP_NAME%\%APP_NAME%.exe」启动
echo   3. 浏览器会自动打开，首次运行数据库自动初始化
echo.
echo 数据目录（题库、数据库、导出文件）：
echo   %%APPDATA%%\%APP_NAME%\
echo.
pause
