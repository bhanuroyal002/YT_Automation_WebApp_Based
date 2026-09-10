@echo off
setlocal
cd /d "%~dp0"

echo ==================================================
echo   YTS Automation Web Interface - Windows
echo ==================================================

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not installed or not in PATH.
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js is not installed or not in PATH.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm is not installed or not in PATH.
  exit /b 1
)
where adb >nul 2>nul
if errorlevel 1 (
  echo ERROR: ADB is not installed or not in PATH.
  exit /b 1
)

echo Python :
python --version
echo Node   :
node --version
echo npm    :
npm --version
echo ADB    :
adb version | findstr /i "Android Debug Bridge"

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if not defined HOST set HOST=127.0.0.1
if not defined PORT set PORT=5000
if not defined FLASK_DEBUG set FLASK_DEBUG=0

if defined ADB_DEVICE echo ADB device target: %ADB_DEVICE%

echo.
echo Starting YTS Automation Web Interface...
echo Open: http://%HOST%:%PORT%
echo Press Ctrl+C to stop.
echo.
python app.py
endlocal
