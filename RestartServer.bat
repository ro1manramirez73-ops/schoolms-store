@echo off
echo Restarting SchoolMS Server...
echo.

:: Stop current server process on port 5000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') do (
    echo Stopping process %%a...
    taskkill /PID %%a /F >nul 2>&1
)

timeout /t 2 >nul

:: Restart via Task Scheduler (if installed as a service)
schtasks /run /tn "SchoolMS" >nul 2>&1

timeout /t 3 >nul

:: Check if it came back up
netstat -an | findstr :5000 | findstr LISTENING >nul
if errorlevel 1 (
    echo Server not detected yet - it may still be starting.
    echo Wait 10 seconds then refresh your browser.
) else (
    echo Server is running on port 5000.
    echo Refresh your browser to see the changes.
)

echo.
pause
