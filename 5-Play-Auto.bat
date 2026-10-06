@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Run 1-Install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo AUTO mode — uses in-game Auto-Place.
echo F8 = stop ^| mouse to corner = failsafe
echo.
pause
python main.py --mode auto --max-games 10
echo.
pause
