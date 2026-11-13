@echo off
cd /d "%~dp0"
echo Starting MarketPilot AI...
echo Open http://127.0.0.1:8000 in your browser.
echo Keep this window open while using the app.
python -u app.py
echo.
echo Server stopped.
pause
