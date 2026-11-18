@echo off
rem Builds dist\ParcelPing.exe (single portable file).
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    python -m venv venv || goto :fail
)
venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt || goto :fail
venv\Scripts\python.exe -m pytest -q || goto :fail
venv\Scripts\python.exe build.py || goto :fail
echo.
pause
exit /b 0

:fail
echo.
echo Build failed. See messages above.
pause
exit /b 1
