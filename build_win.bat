@echo off
:: build_win.bat — 双击此文件即可启动 Windows EXE 打包流程
:: 实际逻辑在 build_win.py（Python 脚本，无编码问题）

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
    echo         Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -X utf8 build_win.py
pause
