@echo off
echo ============================================
echo  SchoolMS - Install Windows Service
echo  RIGHT-CLICK and Run as Administrator
echo ============================================
echo.

set APP_DIR=%~dp0
set SVC_NAME=SchoolMS

:: Remove existing scheduled task if present
schtasks /delete /tn "%SVC_NAME%" /f >nul 2>&1

echo Installing service using Task Scheduler...

schtasks /create /tn "%SVC_NAME%" ^
    /tr "\"%APP_DIR%.venv\Scripts\python.exe\" \"%APP_DIR%wsgi.py\"" ^
    /sc ONSTART ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /delay 00:30 ^
    /f

if errorlevel 1 (
    echo ERROR: Could not create scheduled task.
    echo Make sure you ran this as Administrator.
    pause
    exit /b 1
)

echo Starting service now...
schtasks /run /tn "%SVC_NAME%"
timeout /t 4 >nul

netstat -an | findstr :5000 | findstr LISTENING >nul
if errorlevel 1 (
    echo WARNING: Server may still be starting. Wait 30 seconds and check.
) else (
    echo Server is running on port 5000.
)

echo.
echo ============================================
echo  Service installed!
echo  The server will auto-start on every reboot.
echo  To remove: schtasks /delete /tn %SVC_NAME% /f
echo ============================================
pause
