@echo off
chcp 65001 >nul
title JARVIS - Hermes + Agentes
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\iniciar-hermes-agentes.ps1"
exit /b 0
