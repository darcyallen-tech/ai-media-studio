@echo off
setlocal
cd /d "%~dp0"

echo.
echo  AI Media Studio
echo  ---------------
echo.

REM Create venv if missing
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv — is Python 3.10+ on PATH?
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate .venv
    pause
    exit /b 1
)

REM Skip pip when core deps already import
python -c "import flet, PIL, cv2, fal_client, httpx, openai, dotenv, pygame" >nul 2>&1
if errorlevel 1 (
    echo Installing / updating dependencies...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo pip install failed.
        pause
        exit /b 1
    )
) else (
    echo Dependencies already satisfied — skipping pip install.
)

echo.
echo Launching desktop app...
python app.py
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo App exited with code %EXITCODE%.
    pause
)
exit /b %EXITCODE%
