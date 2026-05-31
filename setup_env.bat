@echo off
setlocal

set INSTALL_DIR=%~1
if "%INSTALL_DIR%"=="" set INSTALL_DIR=%~dp0

echo ============================================================
echo  School Management System — First-Time Configuration
echo ============================================================
echo.

echo [1/1] Generating secure configuration...
if not exist "%INSTALL_DIR%\app\.env" (
    "%INSTALL_DIR%\.python\python.exe" -c "import secrets; f=open(r'%INSTALL_DIR%\app\.env','w'); f.write('SECRET_KEY='+secrets.token_hex(32)+'\nDATABASE_URL=sqlite:///school.db\nPORT=5000\n'); f.close()"
    if %ERRORLEVEL% neq 0 (
        echo ERROR: Could not create configuration file.
        echo Make sure the installer completed without errors.
        exit /b 1
    )
)

echo.
echo ============================================================
echo  Setup complete! Launch using the desktop shortcut.
echo ============================================================
echo.
endlocal
