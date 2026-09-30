@echo off
chcp 65001 >nul
REM pushd умеет UNC (\\nas01\...\request_processor): cmd даёт временную букву.
REM cd /d на такой путь падает в C:\Windows и пугает оператора.
pushd "%~dp0"
if errorlevel 1 goto :unc_fail

REM Ранний визуальный сигнал: до pythonw на NAS может пройти 10+ с
title Lab_request — запуск…
echo Lab_request: запуск… (на сетевом диске это может занять 10-20 с)

set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"
set "LOGDIR=%~dp0data\logs"
set "LAUNCHLOG=%~dp0data\gui_launch.log"
REM Не грузить ico splash с UNC (ускоряет появление окна)
set "REQUEST_PROCESSOR_SPLASH_ICON=0"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%date% %time%] start_gui.bat begin >> "%LAUNCHLOG%"
echo [%date% %time%] cwd=%CD% >> "%LAUNCHLOG%"
echo [%date% %time%] PY=%PY% >> "%LAUNCHLOG%"

if not exist "%PY%" (
    echo ERROR: Python not found in .venv
    echo [%date% %time%] ERROR: no venv python >> "%LAUNCHLOG%"
    echo Run in PowerShell:
    echo   pushd "%~dp0"
    echo   py -3.11 -m venv .venv
    echo   .venv\Scripts\pip install -e ".[cv]"
    goto :fail
)

if exist "%PYW%" (
    "%PYW%" -m request_processor.ui.gui 2>>"%LAUNCHLOG%"
) else (
    start "" "%PY%" -m request_processor.ui.gui
    goto :done
)

if errorlevel 1 (
    echo [%date% %time%] GUI exitcode=%ERRORLEVEL% >> "%LAUNCHLOG%"
    echo.
    echo GUI failed to start. See:
    echo   %LAUNCHLOG%
    echo   %LOGDIR%\app_YYYY-MM-DD.log
    echo.
    type "%LAUNCHLOG%" 2>nul
    echo.
    goto :fail
)

echo [%date% %time%] start_gui.bat end ok >> "%LAUNCHLOG%"
goto :done

:unc_fail
echo Не удалось открыть папку программы:
echo   %~dp0
echo Если это сетевой путь \\server\..., запустите Lab_request с буквы диска W:\
pause
exit /b 1

:fail
popd
pause
exit /b 1

:done
popd
exit /b 0
