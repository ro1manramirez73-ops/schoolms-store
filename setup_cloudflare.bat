@echo off
echo ============================================
echo  SchoolMS - Cloudflare Tunnel Setup
echo  Permanent HTTPS URL (requires Cloudflare
echo  account + domain added to Cloudflare)
echo  Run as Administrator
echo ============================================
echo.
echo BEFORE YOU START:
echo  1. Create a FREE account at cloudflare.com
echo  2. Add your domain to Cloudflare (it will
echo     give you nameservers to set at your
echo     domain registrar - takes ~5 minutes)
echo  3. Then run this script
echo.
pause

set APP_DIR=%~dp0
set CF_DIR=%APP_DIR%cloudflared
set CF_EXE=%CF_DIR%\cloudflared.exe
set CF_CONFIG=%CF_DIR%\config.yml

:: ── Step 1: Download cloudflared ─────────────────────────────────────────────
if not exist "%CF_EXE%" (
    echo [1/5] Downloading Cloudflare Tunnel...
    mkdir "%CF_DIR%" 2>nul
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF_EXE%'"
    if errorlevel 1 (
        echo ERROR: Download failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo Download complete.
) else (
    echo [1/5] cloudflared already downloaded.
)

:: ── Step 2: Login ─────────────────────────────────────────────────────────────
echo.
echo [2/5] Login to Cloudflare...
echo  A browser window will open. Log in and authorize.
echo.
pause
"%CF_EXE%" login
if errorlevel 1 (
    echo ERROR: Login failed.
    pause
    exit /b 1
)

:: ── Step 3: Create tunnel ─────────────────────────────────────────────────────
echo.
echo [3/5] Creating tunnel named "schoolms-tunnel"...
"%CF_EXE%" tunnel create schoolms-tunnel 2>&1
echo.
echo The Tunnel ID was shown above (long UUID like: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
echo.
set /p TUNNEL_ID=Paste your Tunnel ID here and press Enter:

:: ── Step 4: Set hostname and DNS ──────────────────────────────────────────────
echo.
echo [4/5] Configure your public URL
echo  Enter the subdomain you want, e.g.:
echo    school.yourdomain.com
echo    portal.yourdomain.com
echo.
set /p HOSTNAME=Enter your full hostname (e.g. school.yourdomain.com):

:: Create the config file (stored next to cloudflared.exe, not in APPDATA)
(
echo tunnel: %TUNNEL_ID%
echo credentials-file: %CF_DIR%\%TUNNEL_ID%.json
echo.
echo ingress:
echo   - hostname: %HOSTNAME%
echo     service: http://localhost:5000
echo   - service: http_status:404
) > "%CF_CONFIG%"

echo.
echo Creating DNS record for %HOSTNAME%...
"%CF_EXE%" tunnel route dns schoolms-tunnel %HOSTNAME%
if errorlevel 1 (
    echo WARNING: DNS record may already exist or domain not found in Cloudflare.
    echo Check your Cloudflare dashboard to confirm the CNAME record exists.
)

:: ── Step 5: Test then install as service ──────────────────────────────────────
echo.
echo [5/5] Testing tunnel...
echo  Your school system should be accessible at:
echo  https://%HOSTNAME%
echo.
echo  Press Ctrl+C after confirming it works, then
echo  this script will install it as a service.
echo.
"%CF_EXE%" tunnel --config "%CF_CONFIG%" run schoolms-tunnel

echo.
echo ============================================
echo  Installing tunnel as auto-start service...
echo ============================================
schtasks /delete /tn "SchoolMSTunnel" /f >nul 2>&1
schtasks /create /tn "SchoolMSTunnel" ^
    /tr "\"%CF_EXE%\" tunnel --config \"%CF_CONFIG%\" run schoolms-tunnel" ^
    /sc ONSTART ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /delay 01:00 ^
    /f

if errorlevel 1 (
    echo ERROR: Could not install as service. Make sure you ran as Administrator.
    pause
    exit /b 1
)

schtasks /run /tn "SchoolMSTunnel"

echo.
echo ============================================
echo  DONE!
echo  Your school system is live at:
echo  https://%HOSTNAME%
echo.
echo  Access it from any phone, tablet, or PC.
echo  The tunnel starts automatically on reboot.
echo.
echo  To remove: schtasks /delete /tn SchoolMSTunnel /f
echo ============================================
pause
