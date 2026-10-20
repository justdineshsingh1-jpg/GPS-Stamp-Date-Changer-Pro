@echo off
setlocal enabledelayedexpansion
title GPS Stamp Date Changer Pro

echo ==============================================================
echo        GPS STAMP DATE CHANGER PRO - LAUNCHER
echo ==============================================================
echo.

REM 1. Detect Python executable
set "PY_EXE="

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_EXE=python"
    ) else (
        where py >nul 2>nul
        if !errorlevel! equ 0 (
            set "PY_EXE=py"
        )
    )
)

if "%PY_EXE%"=="" (
    echo [ERROR] Python 3.10+ was not found on your system!
    echo Please install Python 3.11 from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [OK] Using Python: %PY_EXE%
echo.

REM 2. Install / check requirements
echo [1/3] Verifying dependencies...
"%PY_EXE%" -m pip install -r requirements.txt --quiet --no-warn-script-location

REM 3. Generate sample files if not present
if not exist "samples\IMG001.jpg" (
    echo [2/3] Generating demonstration sample survey data and photographs...
    "%PY_EXE%" generate_samples.py
) else (
    echo [2/3] Test samples ready.
)

REM 4. Launch web application
echo [3/3] Starting web server on http://127.0.0.1:8000 ...
echo Application is opening in your default web browser...
echo.
echo ==============================================================
echo [ANY DEVICE ACCESS]:
echo To use this software on your mobile phone, tablet, or another
echo computer on the same Wi-Fi, open this link in any browser:
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "ipv4"') do (
    set "IP=%%a"
    set "IP=!IP: =!"
    echo     http://!IP!:8000
)
echo ==============================================================
echo.
echo Press Ctrl+C in this terminal window to stop the server.
echo.

start "" http://127.0.0.1:8000
"%PY_EXE%" -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload

pause
