@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist .env (
    copy .env.example .env >nul
    echo Fill .env with your keys, then run this file again.
    notepad .env
    pause
    exit /b
)
python -u telegram_bot.py
pause
