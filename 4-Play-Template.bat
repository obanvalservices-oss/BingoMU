@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo Run 1-Install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo TEMPLATE mode — ChatGPT pattern (recommended).
echo F8 = stop ^| mouse to corner = failsafe
echo.
echo Tras Continue: 5s de cuenta regresiva para poner Remote Desktop al frente.
echo.
pause
python main.py --mode template --max-games 10 --countdown 5
echo.
pause
