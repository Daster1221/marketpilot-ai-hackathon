@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m pip install -r requirements-speech.txt
if errorlevel 1 goto end
python prepare_speech.py
:end
pause
