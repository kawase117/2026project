@echo off
setlocal
set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%~dp0logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\run_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%"
rem run_daily.py detects collection gaps and picks profile crawl vs date-window
rem search accordingly; keep the logic there, not in this batch file.
"%PYTHON%" scraper\twitter_monitor\run_daily.py >> "%LOG_FILE%" 2>&1
popd
endlocal
