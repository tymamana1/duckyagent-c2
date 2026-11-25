@echo off
REM ============================================================
REM   DuckyScript Local Server - Start
REM   Serves .duckyscript files via HTTP for the Pi to fetch
REM
REM   Usage: start_ducky_server.bat
REM   Then set your Pi's loader.conf SCRIPT_URL to:
REM     http://YOUR_PC_IP/ducky/default.duckyscript
REM ============================================================

echo ============================================
echo   DuckyScript Local Server
echo ============================================
echo.

REM Find the IP address of this PC on the local network
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set PI_IP=%%a
)

if not defined PI_IP (
    echo ERROR: Could not find your IP address.
    echo Make sure you are connected to a network.
    pause
    exit /b 1
)

REM Trim whitespace from the IP
set PI_IP=%PI_IP: =%

echo Your PC's local IP address is: %PI_IP%
echo Your PC's network name is:   %COMPUTERNAME%.local
echo.
echo On your Pi, set SCRIPT_URL to either:
echo   http://%PI_IP%/default.duckyscript
echo   or  http://%COMPUTERNAME%.local/default.duckyscript
echo.
echo Starting server on port 8080...
echo Press Ctrl+C to stop the server.
echo.

REM Create scripts folder if it doesn't exist
if not exist "%~dp0scripts" mkdir "%~dp0scripts"

REM Start Python HTTP server in background, serving the scripts folder
cd /d "%~dp0scripts"
python -m http.server 8080 --bind %PI_IP%
