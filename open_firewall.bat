@echo off
echo Adding firewall rule for SchoolMS (port 5000)...
netsh advfirewall firewall delete rule name="SchoolMS" >nul 2>&1
netsh advfirewall firewall add rule name="SchoolMS" dir=in action=allow protocol=TCP localport=5000
if %errorlevel%==0 (
    echo.
    echo SUCCESS! Other computers on the network can now connect.
) else (
    echo.
    echo FAILED. Please right-click this file and choose "Run as administrator".
)
pause
