@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
    echo Project Python is missing. See README.md to set up .venv.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m host.gui
if errorlevel 1 pause
