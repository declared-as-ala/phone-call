@echo off
title IVR Dashboard - Frontend (Vite)
cd /d "%~dp0..\..\frontend"
if not exist "node_modules" (
  echo [ERREUR] node_modules manquant. Lance: npm install
  pause
  exit /b 1
)
echo Ouvrir dans le navigateur l'URL affichee ci-dessous (souvent http://localhost:5173)
npm run dev
pause
