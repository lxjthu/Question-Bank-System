@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在停止旧服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >/dev/null 2>&1
)
timeout /t 1 >nul

echo 启动服务中...
venv\Scripts\python.exe server.py
