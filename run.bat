@echo off
chcp 65001 >nul
REM Launch Sonos Caster. Uses python.exe (with console) because on this
REM machine pythonw-created Tk windows do not always map to the screen.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo Starting Sonos Caster... (this console window can stay minimized)
".venv\Scripts\python.exe" main.py
pause
