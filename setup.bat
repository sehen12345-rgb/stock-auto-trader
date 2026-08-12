@echo off
title AI 자동매매 봇 - 초기 설치
cd /d %~dp0
echo.
echo  ================================================
echo   AI 자동매매 봇 초기 설치
echo  ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python 이 설치되어 있지 않습니다.
    echo        https://www.python.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)

echo [1/4] 가상환경 생성 중...
python -m venv venv
if errorlevel 1 (
    echo [오류] 가상환경 생성 실패
    pause
    exit /b 1
)

echo [2/4] 가상환경 활성화...
call venv\Scripts\activate

echo [3/4] 패키지 설치 중...
pip install --upgrade pip -q
pip install -r requirements.txt
if errorlevel 1 (
    echo [오류] 패키지 설치 실패
    pause
    exit /b 1
)

echo [4/4] 설정 파일 생성 중...
if not exist .env (
    copy .env.example .env
    echo       .env 파일 생성 완료
) else (
    echo       .env 파일 이미 존재합니다 (유지)
)

if not exist data mkdir data
if not exist logs mkdir logs

echo.
echo  ================================================
echo   설치 완료!
echo  ================================================
echo.
echo   다음 단계:
echo   1. .env 파일을 열어 설정 확인 (기본값: DEMO_MODE=true)
echo   2. run.bat 실행
echo   3. 브라우저에서 http://localhost:8000 접속
echo.
echo   API 키 없이 바로 데모 실행 가능합니다.
echo.
pause
