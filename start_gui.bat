@echo off
cd /d "%~dp0"

set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0data\gui_launch.log"

if not exist "%PY%" (
    echo ERROR: Python not found in .venv
    echo Run in PowerShell:
    echo   cd /d "%~dp0"
    echo   py -3.11 -m venv .venv
    echo   .venv\Scripts\pip install -e ".[ocr]"
    pause
    exit /b 1
)

if exist "%PYW%" (
    "%PYW%" -m request_processor.ui.gui 2>>"%LOG%"
) else (
    start "" "%PY%" -m request_processor.ui.gui
    exit /b 0
)

if errorlevel 1 (
    echo.
    echo GUI failed to start. Log:
    type "%LOG%" 2>nul
    echo.
    pause
    exit /b 1
)