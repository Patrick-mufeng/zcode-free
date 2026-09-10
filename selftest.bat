@echo off
rem Self-test launcher (ASCII only, see run.bat notes)
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" goto no_venv

echo Running self-test, please wait...
echo.
"%PYEXE%" "%~dp0selftest.py" %*
echo.
pause
exit /b %ERRORLEVEL%

:no_venv
echo.
echo  [ERROR] Virtual environment ".venv" was not found.
echo  Run:  python -m venv .venv
echo        .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1
