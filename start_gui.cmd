@echo off
setlocal

REM Thaumcraft Nexus GUI launcher.
REM Double-click this file, or run it from cmd.exe.

cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PYTHON_CMD=py -3"
    ) else (
        echo [ERROR] Python was not found. Please install Python 3 and try again.
        pause
        exit /b 1
    )
)

echo Starting Thaumcraft Nexus GUI...
%PYTHON_CMD% tools\thaum_nexus_gui.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] GUI exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
