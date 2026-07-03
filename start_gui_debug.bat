@echo off
cd /d "%~dp0"
echo Starting GUI (debug mode, console visible)...
echo Working dir: %CD%
"%~dp0.venv\Scripts\python.exe" -m request_processor.ui.gui
echo.
echo Exit code: %ERRORLEVEL%
pause