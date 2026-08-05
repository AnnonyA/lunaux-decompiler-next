@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
title LunaUX Next Launcher

echo Starting LunaUX Next Windows Launcher...

py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.13 installer.py
    goto :done
)

py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
    py -3 installer.py
    goto :done
)

python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
    python installer.py
    goto :done
)

echo.
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Make sure "Add Python to PATH" is enabled.
echo.
pause
exit /b 1

:done
if errorlevel 1 (
    echo.
    echo LunaUX Next closed with an error.
    pause
)
endlocal
