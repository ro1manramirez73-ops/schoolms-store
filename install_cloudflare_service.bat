@echo off
echo ============================================
echo  Install Cloudflare Tunnel as Auto-Start
echo  RIGHT-CLICK and Run as Administrator
echo ============================================
echo.

set CF=c:\SchoolMS\cloudflared\cloudflared.exe
set CFG=c:\SchoolMS\cloudflared\config.yml

:: Remove old task if exists
schtasks /delete /tn "SchoolMSTunnel" /f >nul 2>&1

:: Install as scheduled task (runs as SYSTEM on startup)
schtasks /create /tn "SchoolMSTunnel" ^
    /tr "\"%CF%\" tunnel --config \"%CFG%\" run schoolms-tunnel" ^
    /sc ONSTART ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /delay 0001:00 ^
    /f

if errorlevel 1 (
    echo ERROR: Could not create task. Make sure you ran as Administrator.
    pause
    exit /b 1
)

echo.
echo Starting tunnel now...
schtasks /run /tn "SchoolMSTunnel"

echo.
echo ============================================
echo  Done! Tunnel installed and running.
echo  URL: https://school.yourdomain.com
echo  Auto-starts on every reboot.
echo ============================================
pause
