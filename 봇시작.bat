@echo off
chcp 65001 >/dev/null
cd /d %~dp0

if not exist venv\Scripts\activate (
    echo 먼저 setup.bat 을 실행해주세요.
    pause & exit /b 1
)

call venv\Scripts\activate
start "" "http://localhost:8000"
python main.py
