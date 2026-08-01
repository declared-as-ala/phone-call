@echo off
title IVR Dashboard - Install everything
cd /d "%~dp0..\.."
set ROOT=%CD%

where python >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Python introuvable. Installe Python 3.10+ avec "Add to PATH".
  pause
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] npm introuvable. Installe Node.js 18+ LTS.
  pause
  exit /b 1
)

echo === Backend: venv + pip + alembic ===
cd /d "%ROOT%\backend"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -c "from app.services.audio_convert import resolve_ffmpeg_executable; ff=resolve_ffmpeg_executable(); print('ffmpeg:', ff or 'MISSING — pip install imageio-ffmpeg')"
if not exist ".env" (
  if exist ".env.example" (
    copy /Y .env.example .env
    echo Cree backend\.env depuis .env.example — edite TELEPHONY_PROVIDER et LUVVOICE_API_TOKEN.
  )
) else (
  echo Utilise backend\.env du zip ^(LuvVoice / config deja inclus^).
)
set PYTHONPATH=.
python -m alembic upgrade head
python -c "from app.services.luvvoice_tts import api_token_configured; print('LuvVoice configure:', api_token_configured())"

echo.
echo === Frontend: npm install ===
cd /d "%ROOT%\frontend"
call npm install

echo.
echo Installation terminee.
echo   1^) Editer backend\.env si besoin
echo   2^) Compte admin:
echo      cd backend
echo      .venv\Scripts\activate.bat
echo      python scripts\create_admin.py --email admin@client.com --password "ChangeMe123!"
echo   3^) Demarrer: scripts\windows\start-backend.cmd puis start-frontend.cmd
echo   4^) Navigateur: http://localhost:5173
pause
