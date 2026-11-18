@echo off
rem Run from source (development). For everyday use, build the .exe with build.bat.
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv || goto :fail
)
echo Checking dependencies...
venv\Scripts\python.exe -m pip install -q -r requirements.txt || goto :fail
start "" venv\Scripts\pythonw.exe main.py %*
exit /b 0

:fail
echo.
echo Setup failed. See messages above.
pause
exit /b 1
