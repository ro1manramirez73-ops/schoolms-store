@echo off
setlocal

set INSTALL_DIR=%~1
if "%INSTALL_DIR%"=="" set INSTALL_DIR=%~dp0

echo ============================================================
echo  School Management System — First-Time Setup
echo ============================================================
echo.

echo [1/5] Extracting Python runtime...
powershell -NoProfile -Command "Expand-Archive -Path '%INSTALL_DIR%\python-embed.zip' -DestinationPath '%INSTALL_DIR%\.python' -Force"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Could not extract Python runtime.
    exit /b 1
)

echo [2/5] Enabling site-packages...
powershell -NoProfile -Command "Get-ChildItem '%INSTALL_DIR%\.python\python*._pth' | ForEach-Object { (Get-Content $_.FullName) -replace '#import site', 'import site' | Set-Content $_.FullName }"

echo [3/5] Installing pip...
"%INSTALL_DIR%\.python\python.exe" "%INSTALL_DIR%\get-pip.py" --quiet
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Could not install pip. Check your internet connection.
    exit /b 1
)

echo [4/5] Installing dependencies (internet required)...
"%INSTALL_DIR%\.python\python.exe" -m pip install -r "%INSTALL_DIR%\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Dependency installation failed. Check your internet connection.
    exit /b 1
)

echo [5/5] Generating configuration...
if not exist "%INSTALL_DIR%\app\.env" (
    "%INSTALL_DIR%\.python\python.exe" -c ^
        "import secrets; f=open(r'%INSTALL_DIR%\app\.env','w'); f.write('SECRET_KEY='+secrets.token_hex(32)+'\nDATABASE_URL=sqlite:///school.db\nPORT=5000\n'); f.close()"
)

echo.
echo ============================================================
echo  Setup complete!
echo  Launch the application using the desktop shortcut.
echo ============================================================
echo.
endlocal
