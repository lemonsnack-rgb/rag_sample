@echo off
cd /d C:\project\01_RAG
REM 캐시 삭제
if exist __pycache__ rd /s /q __pycache__
REM Streamlit 실행
.\venv\Scripts\streamlit.exe run app.py
pause
