@echo off
REM Run as Administrator: right-click -> Run as administrator
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-rtp-firewall.ps1"
echo.
echo Router port-forward (do this in your router admin page):
echo   Protocol: UDP
echo   External ports: 10000-10100
echo   Internal IP: check with  ipconfig  (Wi-Fi IPv4, e.g. 10.38.202.178)
echo   Internal ports: 10000-10100
echo.
pause
