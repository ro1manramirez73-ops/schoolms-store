@echo off
setlocal
echo ============================================================
echo  SchoolMS — Build Python Environment for Installer
echo  Run this ONCE before compiling the installer.
echo  Requires internet access (one-time only on your machine).
echo ============================================================
echo.

set SCRIPT_DIR=%~dp0
set PYTHON_DIR=%SCRIPT_DIR%.python

if exist "%PYTHON_DIR%" (
    echo Removing previous .python build...
    rmdir /s /q "%PYTHON_DIR%"
)

echo [1/4] Extracting Python runtime...
powershell -NoProfile -Command "Expand-Archive -Path '%SCRIPT_DIR%python-embed.zip' -DestinationPath '%PYTHON_DIR%' -Force"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Could not extract python-embed.zip
    pause & exit /b 1
)

echo [2/4] Enabling site-packages...
powershell -NoProfile -Command "Get-ChildItem '%PYTHON_DIR%\python*._pth' | ForEach-Object { (Get-Content $_.FullName) -replace '#import site', 'import site' | Set-Content $_.FullName }"

echo [3/4] Installing pip...
"%PYTHON_DIR%\python.exe" "%SCRIPT_DIR%get-pip.py" --quiet
if %ERRORLEVEL% neq 0 (
    echo ERROR: pip install failed. Check your internet connection.
    pause & exit /b 1
)

echo [4/4] Installing all packages (this may take a few minutes)...
"%PYTHON_DIR%\python.exe" -m pip install -r "%SCRIPT_DIR%requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo ERROR: Package installation failed.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Done! .python folder is ready with all packages.
echo  Now open installer.iss in Inno Setup and click Compile.
echo ============================================================
pause
