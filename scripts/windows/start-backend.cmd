@echo off
title IVR Dashboard - Backend (port 8000)
cd /d "%~dp0..\.."
if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERREUR] venv manquant. Installation une fois:
  echo   cd backend
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  echo   .venv\Scripts\python -m alembic upgrade head
  pause
  exit /b 1
)
cd backend
set PYTHONPATH=.
call .venv\Scripts\activate.bat
echo Backend: http://127.0.0.1:8000  (laisser cette fenetre ouverte)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
