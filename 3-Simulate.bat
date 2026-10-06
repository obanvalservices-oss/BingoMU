@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Run 1-Install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python tools\simulate_offline.py --template --games 20 --sims 400
echo.
pause
