@echo off
REM Raspberry Pi USB Rubber Ducky - Quick Test Launcher
REM Run this to test scripts on your Windows PC

cd /d "%~dp0"

echo ============================================
echo   Raspberry Pi USB Rubber Ducky
echo   Quick Test (types in active window)
echo ============================================
echo.
echo Make sure you click on the window where you
echo want the script to type (Notepad, etc.)
echo.
echo Available scripts:
echo   1. hello_world.duckyscript
echo   2. system_info.duckyscript  
echo   3. powershell_info.duckyscript
echo   4. default.duckyscript
echo.
set /p choice="Enter script number (1-4), or press Enter to cancel: "

if "%choice%"=="1" set SCRIPT=hello_world.duckyscript
if "%choice%"=="2" set SCRIPT=system_info.duckyscript
if "%choice%"=="3" set SCRIPT=powershell_info.duckyscript
if "%choice%"=="4" set SCRIPT=default.duckyscript

if not defined SCRIPT (
    if "%choice%"=="" (
        echo Cancelled.
    ) else (
        echo Invalid choice '%choice%'. Please enter a number between 1 and 4.
    )
    pause
    exit /b 1
)

echo.
echo Running %SCRIPT%...
echo Click on the window where you want it to type!
echo.
timeout /t 3 /nobreak >nul

python ducky.py %SCRIPT%
echo.
echo Done! Press any key to close.
pause >nul
