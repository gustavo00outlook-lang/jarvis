@echo off
chcp 65001 >nul
title JARVIS
cd /d "%~dp0"
echo Subindo JARVIS (clone + cerebro + orbe + 1 janela)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\iniciar-jarvis-completo.ps1"
if errorlevel 1 (
  echo.
  echo Falhou. Veja logs\backend.err.log e logs\frontend-start.err.log
  pause
  exit /b 1
)
exit /b 0
