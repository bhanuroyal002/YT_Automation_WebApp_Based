@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==================================================
echo   YTS Automation Web Interface - Windows
echo ==================================================

where python >nul 2>nul || (echo ERROR: Python is not installed or not in PATH.& exit /b 1)
where node >nul 2>nul || (echo ERROR: Node.js is not installed or not in PATH.& exit /b 1)
where npm >nul 2>nul || (echo ERROR: npm is not installed or not in PATH.& exit /b 1)
where adb >nul 2>nul || (echo ERROR: ADB is not installed or not in PATH.& exit /b 1)

python --version
node --version
npm --version
adb version

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  python -m venv .venv || exit /b 1
)
call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1

if not defined HOST set "HOST=127.0.0.1"
if not defined PORT set "PORT=5000"
if not defined FLASK_DEBUG set "FLASK_DEBUG=0"
if defined ADB_DEVICE echo ADB device target: %ADB_DEVICE%

echo.
echo Starting YTS Automation Web Interface...
echo Open: http://%HOST%:%PORT%
echo Press Ctrl+C to stop.
echo.
python app.py
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
