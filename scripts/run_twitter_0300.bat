@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "TW_DIR=%ROOT%\scraper\twitter_monitor"
set "LOG_DIR=%TW_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\twitter_0300_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%TW_DIR%"
rem 03:00 slot: X monitoring only, independent of the ana-slo pipeline.
rem Uses its own "twitter_monitor" file lock (see runlock.py), so it never
rem contends with the 07:00/07:30 ana-slo tasks' "daily_pipeline" lock.
"%PYTHON%" -u run_daily.py >> "%LOG_FILE%" 2>&1
popd
endlocal
