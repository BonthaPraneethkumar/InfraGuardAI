@echo off
setlocal
cd /d "%~dp0"
title InfraGuard AI - Local Server

echo.
echo ==========================================
echo        InfraGuard AI - One Click Start
echo ==========================================
echo.

set "PYEXE="

where python >nul 2>nul
if %errorlevel%==0 set "PYEXE=python"

if not defined PYEXE (
  where py >nul 2>nul
  if %errorlevel%==0 set "PYEXE=py"
)

if not defined PYEXE (
  for /d %%D in ("%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_*") do (
    if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
  )
)

if not defined PYEXE (
  echo Python was not found.
  echo Install Python 3.13 or later, then run this file again.
  pause
  exit /b 1
)

echo Python found: %PYEXE%

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [1/3] Creating project environment...
  "%PYEXE%" -m venv .venv
  if errorlevel 1 goto :fail
)

echo.
echo [2/3] Installing/updating required packages...
call ".venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [3/3] Starting InfraGuard AI...
echo Browser address: http://127.0.0.1:8000
echo Keep this black window open while using the app.
echo.
start "" "http://127.0.0.1:8000"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
goto :end

:fail
echo.
echo Something failed. Take a screenshot of this window and send it to ChatGPT.
pause

:end
endlocal
