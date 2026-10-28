@echo off
rem Start PL Analyzer Pro from this checkout with the project virtual environment.
rem Double-click, or run from a terminal:  run-pl-analyzer.bat [zh|en]
setlocal
cd /d "%~dp0"

set "ENTRY=%~dp0main_zh.py"
set "PY=%~dp0.venv\Scripts\python.exe"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"

if /i "%~1"=="en" set "ENTRY=%~dp0main.py"
if /i "%~1"=="en-US" set "ENTRY=%~dp0main.py"

if not exist "%PY%" goto no_venv
if not exist "%ENTRY%" goto no_entry

if exist "%PYW%" (
    start "" "%PYW%" "%ENTRY%"
) else (
    start "" "%PY%" "%ENTRY%"
)
exit /b 0

:no_venv
echo [PL Analyzer Pro] Project virtual environment not found: %PY%
echo.
echo   python -m venv .venv
echo   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
echo.
echo Alternatively run a built release from the dist folder.
pause
exit /b 1

:no_entry
echo [PL Analyzer Pro] Entry point not found: %ENTRY%
pause
exit /b 1
