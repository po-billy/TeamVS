@echo off
rem TeamVS bot launcher (ASCII only - cmd has issues with UTF-8 batch files)
cd /d "%~dp0"

if not exist ".env" (
    echo [ERROR] .env file not found.
    echo         Copy .env.example to .env and fill in your tokens.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)

echo [START] Launching TeamVS bot... (Ctrl+C to stop)
.venv\Scripts\python bot.py
pause
