@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -u start_miniapp.py
pause
