@echo off
chcp 65001 >/dev/null
echo =============================
echo  주식 자동매매 봇 초기 설치
echo =============================
echo.
cd /d %~dp0
echo [1/3] 가상환경 생성 중...
python -m venv venv
if errorlevel 1 (
    echo Python이 없습니다. https://python.org 에서 설치 후 다시 실행하세요.
    pause & exit /b 1
)
echo [2/3] 패키지 설치 중... (2-3분 소요)
call venv\Scripts\activate
pip install -r requirements.txt --quiet
echo [3/3] 폴더 생성...
if not exist data mkdir data
if not exist logs mkdir logs
echo.
echo 설치 완료! 이제 봇시작.bat 을 실행하세요.
pause
