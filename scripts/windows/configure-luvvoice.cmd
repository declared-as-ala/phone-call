@echo off
title Configure LuvVoice token
cd /d "%~dp0..\..\backend"
if "%~1"=="" (
  echo.
  echo Usage:
  echo   configure-luvvoice.cmd YOUR_LUVVOICE_TOKEN
  echo.
  echo Example:
  echo   configure-luvvoice.cmd lvv_abc123...
  echo.
  echo Get token: LuvVoice Dashboard -^> API Tokens ^(Plus plan+^)
  pause
  exit /b 1
)
if not exist ".env" (
  if exist ".env.example" copy /Y .env.example .env
  echo Created .env from .env.example
)
set TOKEN=%~1
powershell -NoProfile -Command ^
  "$p='.env'; $t=$env:TOKEN; $lines=Get-Content $p -ErrorAction SilentlyContinue; if(-not $lines){$lines=@()}; $lines=$lines | Where-Object {$_ -notmatch '^\s*LUVVOICE_API_TOKEN=' -and $_ -notmatch '^\s*LUVVOICE_DEFAULT_VOICE_ID='}; $lines += \"LUVVOICE_API_TOKEN=$t\"; $lines += 'LUVVOICE_DEFAULT_VOICE_ID=voice-001'; $lines | Set-Content $p -Encoding UTF8"
if errorlevel 1 (
  echo [ERREUR] Impossible d'ecrire backend\.env
  pause
  exit /b 1
)
echo.
echo OK — LuvVoice configure dans backend\.env
echo Redemarre le backend:
echo   scripts\windows\start-backend.cmd
echo Puis Ctrl+Shift+R dans le navigateur.
pause
