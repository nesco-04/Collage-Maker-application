@echo off
REM Builds a standalone Windows executable for Collage Maker using
REM PyInstaller. The resulting .exe requires no Python installation on the
REM target machine and opens the GUI with no console window.

setlocal

set VENV_DIR=%~dp0.venv

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment. Ensure Python 3.12+ is installed and on PATH.
        exit /b 1
    )
)

"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"

echo Building executable with PyInstaller...
"%VENV_DIR%\Scripts\python.exe" -m PyInstaller "%~dp0collage_app.spec" --noconfirm

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete. The executable is at dist\CollageMaker\CollageMaker.exe
endlocal
