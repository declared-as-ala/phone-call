@echo off
title IVR - SIP UP ARI Bridge
cd /d "%~dp0..\.."
if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERREUR] venv backend manquant.
  pause
  exit /b 1
)
cd backend
set PYTHONPATH=.
call .venv\Scripts\activate.bat
echo Bridge ARI - laisser cette fenetre ouverte avec le backend
python scripts\run_sip_up_ari_bridge.py
pause
