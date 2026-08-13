@echo off
chcp 65001 >nul
cd /d C:\Users\com\stock-auto-trader

if not exist venv\Scripts\activate.bat (
    echo 먼저 setup.bat 을 실행해주세요.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
start "" "http://localhost:8000"
python main.py
pause
