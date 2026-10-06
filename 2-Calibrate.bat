@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Run 1-Install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo.
echo IMPORTANTE:
echo   Despues de Continue tendras 8 segundos para poner
echo   Chrome Remote Desktop al FRENTE (Jewel Bingo visible)
echo   y sacar esta ventana del medio.
echo.
pause
python tools\calibrate_wizard.py --delay 8
echo.
pause
