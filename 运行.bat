@echo off
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
    echo [启动失败] exit code %errorlevel%
    echo 首次使用请先双击「一键部署.bat」配置环境
    echo.
)

pause

