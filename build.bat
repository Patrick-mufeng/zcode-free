@echo off
REM ==========================================================================
REM  Build script for ZCode Welfare Assistant (onedir, PyInstaller)
REM  NOTE: This file must stay pure ASCII. cmd.exe parses .bat using the
REM  system codepage; non-ASCII text here breaks the whole script on
REM  Chinese Windows. Keep messages in English.
REM ==========================================================================
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
set ICON=build\app.ico
set SPEC=build.spec

echo [1/5] Checking virtual environment...
if not exist "%PY%" (
  echo   ERROR: %PY% not found.
  echo   Run: python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

echo [2/5] Checking PyInstaller...
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo   PyInstaller missing, installing 6.22.2 ...
  "%PY%" -m pip install "pyinstaller==6.22.2"
  if errorlevel 1 exit /b 1
)

echo [3/5] Generating application icon...
"%PY%" build\make_icon.py
if errorlevel 1 exit /b 1

echo [4/5] Running selftest ^(must pass before packaging^)...
"%PY%" selftest.py
if errorlevel 1 (
  echo   ERROR: selftest failed. Fix it before packaging.
  exit /b 1
)

echo [5/5] Building with PyInstaller...
if exist dist\ZCodeAssistant rmdir /s /q "dist\ZCodeAssistant"
"%PY%" -m PyInstaller "%SPEC%" --noconfirm --clean --distpath dist --workpath build\pyi
if errorlevel 1 exit /b 1

echo.
echo Done. Output: dist\ZCodeAssistant\ZCodeAssistant.exe
echo.
echo Verify before shipping:
echo   - config.yaml is created next to the exe on first run
echo   - "Detect ZCode" button still finds the client (win32com hiddenimports)
echo   - double-click twice shows the single-instance message
echo   - antivirus does not flag the exe
endlocal
