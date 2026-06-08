@echo off
set APP_DIR=%~dp0
"%APP_DIR%.venv\Scripts\python.exe" "%APP_DIR%wsgi.py"
