@echo off
echo ============================================
echo  SchoolMS - Create Deploy Package
echo ============================================
echo.

set DEST=%~dp0deploy_output
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"

echo Copying app files...
xcopy "%~dp0files" "%DEST%\files\" /E /I /Q /EXCLUDE:%~dp0deploy_exclude.txt
xcopy "%~dp0wsgi.py"          "%DEST%\" /Q
xcopy "%~dp0requirements.txt" "%DEST%\" /Q
xcopy "%~dp0.env"             "%DEST%\" /Q 2>nul

echo Copying database...
xcopy "%~dp0school.db" "%DEST%\" /Q 2>nul
if not exist "%DEST%\school.db" (
    xcopy "%~dp0files\school.db" "%DEST%\" /Q 2>nul
)

echo Copying setup scripts...
xcopy "%~dp0server_setup.bat"        "%DEST%\" /Q
xcopy "%~dp0install_service.bat"     "%DEST%\" /Q
xcopy "%~dp0setup_cloudflare.bat"    "%DEST%\" /Q

echo.
echo Compressing to ZIP...
powershell -Command "Compress-Archive -Path '%DEST%\*' -DestinationPath '%~dp0SchoolMS_Server.zip' -Force"

rmdir /s /q "%DEST%"

echo.
echo ============================================
echo  DONE!  SchoolMS_Server.zip created
echo  Copy this ZIP to the server computer.
echo ============================================
pause
