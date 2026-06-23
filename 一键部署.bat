@echo off
cd /d "%~dp0"

REM ============================================================
REM   气动组工具箱 - 一键部署（内网源）
REM   内网唯一 pip 源：http://sanynexus.sany.com.cn/repository/pypi-aliyun/simple/
REM ============================================================

set PIP_INDEX_URL=http://sanynexus.sany.com.cn/repository/pypi-aliyun/simple/
set PIP_TRUSTED_HOST=sanynexus.sany.com.cn

echo ============================================================
echo   气动组工具箱 - 一键部署
echo ============================================================
echo.

REM === 检测 Python（优先 python，其次 py launcher）===
where python >nul 2>nul
if %errorlevel%==0 (
    set PY=python
    goto :found_py
)
where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py
    goto :found_py
)

echo [错误] 未找到 Python。
echo 请先安装 Python 3.8+（勾选 Add Python to PATH），重新运行本脚本。
echo 下载地址（内网）：http://sanynexus.sany.com.cn/
echo.
pause
exit /b 1

:found_py
echo Python:           %PY%
echo 内网 pip 源:      %PIP_INDEX_URL%
echo Trusted Host:     %PIP_TRUSTED_HOST%
echo.
echo ------------------------------------------------------------

REM === [1/3] 升级 pip ===
echo [1/3] 升级 pip...
%PY% -m pip install --upgrade pip -i %PIP_INDEX_URL% --trusted-host %PIP_TRUSTED_HOST%
if %errorlevel% neq 0 (
    echo [警告] pip 升级失败，继续后续步骤...
)
echo.

REM === [2/3] 安装依赖 ===
echo [2/3] 安装依赖（requirements.txt）...
%PY% -m pip install -r requirements.txt -i %PIP_INDEX_URL% --trusted-host %PIP_TRUSTED_HOST%
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败。请检查：
    echo   1. 内网 VPN 是否已连接
    echo   2. 源是否可达：%PIP_INDEX_URL%
    echo   3. 手动测试：%PY% -m pip install numpy -i %PIP_INDEX_URL% --trusted-host %PIP_TRUSTED_HOST%
    echo.
    pause
    exit /b 1
)
echo.

REM === [3/3] 验证安装 ===
echo [3/3] 验证依赖可正常 import...
%PY% -c "import PyQt5, numpy, pandas, scipy, openpyxl, matplotlib, psutil; from scipy.interpolate import PchipInterpolator; print('依赖验证 OK')"
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖验证失败，请查看上方报错。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   部署完成！
echo   双击「运行.bat」启动工具箱
echo ============================================================
echo.
pause

