@echo off
REM Development launcher for Collage Maker.
REM Creates/uses a local virtual environment, installs dependencies if
REM needed, then runs the application from source.

setlocal

set VENV_DIR=%~dp0.venv

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment. Ensure Python 3.12+ is installed and on PATH.
        exit /b 1
    )
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV_DIR%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
)

"%VENV_DIR%\Scripts\python.exe" "%~dp0main.py"

endlocal
