@echo off
echo ============================================
echo  SchoolMS - Server Setup
echo  Run this ONCE on the server computer
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed.
    echo Please install Python from https://python.org/downloads
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

set APP_DIR=%~dp0

echo [1/4] Creating virtual environment...
python -m venv "%APP_DIR%.venv"
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
"%APP_DIR%.venv\Scripts\python.exe" -m pip install --upgrade pip -q
"%APP_DIR%.venv\Scripts\pip.exe" install -r "%APP_DIR%requirements.txt" -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [3/4] Adding firewall rule for port 5000...
netsh advfirewall firewall delete rule name="SchoolMS" >nul 2>&1
netsh advfirewall firewall add rule name="SchoolMS" dir=in action=allow protocol=TCP localport=5000

echo [4/4] Testing server startup...
start /b "" "%APP_DIR%.venv\Scripts\python.exe" "%APP_DIR%wsgi.py"
set TEST_PID=%ERRORLEVEL%
timeout /t 4 >nul
netstat -an | findstr :5000 | findstr LISTENING >nul
if errorlevel 1 (
    echo WARNING: Server did not start on port 5000. Check for errors.
) else (
    echo Server is responding correctly on port 5000.
)

:: Kill only the test server process by port, not all python.exe
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo ============================================
echo  Setup complete!
echo  Next: Run install_service.bat as Admin
echo        to auto-start on boot.
echo ============================================
pause
