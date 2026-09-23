@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%ROOT%\scraper\twitter_monitor\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\morning_0730_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%"
rem 07:30 slot: ana-slo retry (idempotent -- scraper skips already-fetched days),
rem then DB update, history, announce scoring, and forward-test freeze -- once.
rem X monitoring runs separately at 03:00 (scripts\run_twitter_0300.bat).
"%PYTHON%" -u scripts\run_morning.py --skip-twitter >> "%LOG_FILE%" 2>&1
popd
endlocal
