@echo off
rem ============================================================
rem  ZCode Welfare Assistant launcher
rem  NOTE: keep this file ASCII-only. cmd.exe parses .bat files
rem  with the system OEM code page; UTF-8 Chinese text breaks
rem  parsing on Chinese Windows (GBK). Chinese docs: README.md
rem ============================================================
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" goto no_venv

"%PYEXE%" "%~dp0main.py" %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%

:no_venv
echo.
echo  [ERROR] Virtual environment ".venv" was not found.
echo.
echo  Run these commands in this folder first:
echo.
echo      python -m venv .venv
echo      .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo  Then start run.bat again.  (Chinese guide: README.md)
echo.
pause
exit /b 1
