@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS-VOICE-CLONE-XTTS
set COQUI_TOS_AGREED=1
set CUDA_VISIBLE_DEVICES=
set JARVIS_LOCAL_CLONE_PREFER=xtts

echo.
echo  === JARVIS Voice Clone (XTTS Thomas 0701) ===
echo  API: http://127.0.0.1:8787
echo  UI:  http://127.0.0.1:7860
echo  Motor: XTTS-v2 clone REAL do sample (nao Edge)
echo.
echo  1a carga do modelo: ~1-2 min no CPU
echo.

start "JARVIS-CLONE-API" /MIN cmd /c "set COQUI_TOS_AGREED=1&& set CUDA_VISIBLE_DEVICES=&& python server.py"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:7860
python ui.py
pause
