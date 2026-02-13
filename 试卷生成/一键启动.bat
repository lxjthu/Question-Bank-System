@echo off
chcp 65001 >nul
title 试题管理系统 - 一键启动

echo ============================================
echo     林业经济学（双语）试题管理系统
echo ============================================
echo.

:: 记录项目目录
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: 检查 Python 是否可用
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8 以上版本。
    pause
    exit /b 1
)

:: 显示 Python 版本
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [信息] 检测到 %%i

:: 虚拟环境目录
set "VENV_DIR=%PROJECT_DIR%venv"

:: 判断虚拟环境是否已存在
if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [信息] 虚拟环境已存在，跳过创建。
) else (
    echo [信息] 正在创建虚拟环境...
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败！
        pause
        exit /b 1
    )
    echo [完成] 虚拟环境创建成功。
)

:: 激活虚拟环境
echo [信息] 激活虚拟环境...
call "%VENV_DIR%\Scripts\activate.bat"

:: 安装/更新依赖
echo [信息] 检查并安装依赖...
pip install -r "%PROJECT_DIR%requirements.txt" -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败！
    pause
    exit /b 1
)
echo [完成] 依赖已就绪。

echo.
echo ============================================
echo   启动服务器: http://localhost:5000
echo   按 Ctrl+C 停止服务器
echo ============================================
echo.

:: 延迟 1 秒后打开浏览器（在后台执行）
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

:: 启动 Flask 服务器（阻塞在这里，直到用户按 Ctrl+C）
python "%PROJECT_DIR%server.py"

:: 服务器关闭后
echo.
echo [信息] 服务器已停止。
pause
