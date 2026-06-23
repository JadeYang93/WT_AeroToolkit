@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM prefer python, fallback to py launcher
where python >nul 2>nul
if %errorlevel%==0 (
    set PY=python
) else (
    set PY=py
)

echo Starting wind farm stats tool...
echo Command: %PY% src\main.py
echo.

%PY% src\main.py

if %errorlevel% neq 0 (
    echo.
    echo [Failed] exit code %errorlevel%
    echo 1. Install Python
    echo 2. pip install PyQt5 pandas matplotlib numpy openpyxl
    echo 3. Sync latest src/ folder
    echo.
)

pause
