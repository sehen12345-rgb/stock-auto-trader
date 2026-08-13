@echo off
cd /d %~dp0
start "" "http://localhost:8000"
call venv\Scripts\activate
python main.py
