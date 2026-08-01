@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

echo ==^> Rendering Asterisk PJSIP configuration
call backend\.venv\Scripts\python.exe infra\sipup\scripts\render_pjsip_from_env.py
echo ==^> Asterisk Docker (if Docker Desktop is running)
cd infra\sipup
docker compose up -d 2>nul
cd /d "%ROOT%"

echo ==^> Backend
start "IVR Backend" cmd /k "%ROOT%\scripts\windows\start-backend.cmd"

echo ==^> SIP UP ARI bridge
start "IVR SIP UP Bridge" cmd /k "%ROOT%\scripts\windows\start-sipup-bridge.cmd"

echo ==^> Frontend
start "IVR Frontend" cmd /k "%ROOT%\scripts\windows\start-frontend.cmd"

echo.
echo Three windows opened. Open http://localhost:5173
echo If calls fail with SIP 403, whitelist your public IP in the SIP UP dashboard.
pause
