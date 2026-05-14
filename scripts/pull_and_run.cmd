@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0\.."
echo Repo root: %CD%

echo Fetching latest from origin...
git fetch origin
git pull --ff-only
if errorlevel 1 (
    echo Fast-forward failed, doing normal pull
    git pull
)

set "VENV_DIR="
if exist ".venv" (
    set "VENV_DIR=.venv"
) else if exist "venv" (
    set "VENV_DIR=venv"
) else (
    echo No virtualenv found. Creating .venv...
    python -m venv .venv
    set "VENV_DIR=.venv"
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "requirements.txt" (
    echo Installing requirements...
    
    "%VENV_PYTHON%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo pip not found; attempting ensurepip...
        "%VENV_PYTHON%" -m ensurepip --upgrade >nul 2>&1
        if errorlevel 1 (
            echo ensurepip failed; downloading get-pip.py...
            curl -sS https://bootstrap.pypa.io/get-pip.py -o "%TEMP%\get-pip.py"
            "%VENV_PYTHON%" "%TEMP%\get-pip.py"
        )
    )

    "%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
    
    :: Remove uvloop for Windows as it causes issues
    findstr /v "uvloop" requirements.txt > "%TEMP%\req_no_uvloop.txt"
    "%VENV_PYTHON%" -m pip install -r "%TEMP%\req_no_uvloop.txt"
    del "%TEMP%\req_no_uvloop.txt"
)

if not exist "logs" mkdir logs
if not exist "run" mkdir run

:: Kill existing process using WMI
wmic process where "name='python.exe' and (commandline like '%%uvicorn%%' or commandline like '%%main:app%%')" call terminate >nul 2>&1

echo Starting uvicorn...
start /b cmd /c ""%VENV_PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000 > logs\server.log 2>&1"

echo Done. Logs at logs\server.log
