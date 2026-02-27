@echo off
REM Rium GM Dosimeter Launcher for Windows
REM ASNR (formerly IRSN) Project

echo.
echo ============================================================
echo   RIUM GM DOSIMETER READER - Windows Launcher
echo   ASNR (formerly IRSN) Project
echo ============================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python 3.7 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Run the launcher
python launcher.py

pause
