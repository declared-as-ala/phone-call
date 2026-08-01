@echo off
title Fix LuvVoice token in backend\.env
cd /d "%~dp0..\..\backend"
set ENVFILE=%CD%\.env

if not exist "%ENVFILE%" (
  if exist ".env.example" copy /Y .env.example .env
)

echo.
echo === Fix LuvVoice ===
echo Fichier: %ENVFILE%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%ENVFILE%';" ^
  "$token='lvv_e23064a261e674e8cbd6e1ec.30a68375e5d63bac838370b45f20bc346cb2232712a220a2148037f47f124c1b';" ^
  "$lines=@(); if(Test-Path $p){$lines=Get-Content $p};" ^
  "$lines=$lines | Where-Object {$_ -notmatch '^LUVVOICE_API_TOKEN=' -and $_ -notmatch '^LUVVOICE_DEFAULT_VOICE_ID='};" ^
  "$lines += 'LUVVOICE_API_TOKEN='+$token;" ^
  "$lines += 'LUVVOICE_DEFAULT_VOICE_ID=voice-001';" ^
  "$lines | Set-Content -Encoding UTF8 $p;" ^
  "Write-Host 'OK - token ecrit dans .env'"

echo.
findstr LUVVOICE .env
echo.
echo REDEMARRE le backend (Ctrl+C puis start-backend.cmd)
pause
