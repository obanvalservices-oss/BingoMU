@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Run 1-Install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Dry-run: logs decisions, minimal mouse movement.
echo F8 = stop. Remote Desktop should be visible.
echo.
python main.py --mode template --dry-run --max-games 1
echo.
pause
