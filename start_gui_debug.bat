@echo off
cd /d "%~dp0"
set "LOGDIR=%~dp0data\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo Starting GUI (debug mode, console visible)...
echo Working dir: %CD%
echo Logs: %LOGDIR%\app_YYYY-MM-DD.log
echo.
"%~dp0.venv\Scripts\python.exe" -m request_processor.ui.gui
set "EC=%ERRORLEVEL%"
echo.
echo Exit code: %EC%
echo [%date% %time%] start_gui_debug exit=%EC% >> "%~dp0data\gui_launch.log"
pause
