@echo off
title AI 자동매매 봇
cd /d %~dp0

if not exist venv (
    echo [오류] venv 폴더가 없습니다. setup.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

call venv\Scripts\activate

if not exist .env (
    echo [정보] .env 파일이 없습니다. .env.example 을 복사합니다.
    copy .env.example .env
)

echo.
echo  AI 자동매매 봇 시작 중...
echo  대시보드: http://localhost:8000
echo  종료: Ctrl+C
echo.

python main.py
pause
