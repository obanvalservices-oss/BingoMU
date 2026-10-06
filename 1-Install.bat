@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   Jewel Bingo Bot — Install (Windows)
echo ============================================
echo Folder: %CD%
echo.
echo Runs on THIS PC (Chrome Remote Desktop client).
echo Do NOT install on the game PC / local server.
echo.

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set PY=py -3
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set PY=python
  ) else (
    echo Python 3.11+ not found.
    echo Install from https://www.python.org/downloads/windows/
    echo Check "Add python.exe to PATH" during setup.
    pause
    exit /b 1
  )
)

echo Creating / updating .venv ...
%PY% -m venv .venv
if errorlevel 1 (
  echo Failed to create venv.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Install complete.
echo ============================================
echo.
echo Next: open Chrome Remote Desktop with Jewel Bingo visible,
echo then run  2-Calibrate.bat
echo.
pause
