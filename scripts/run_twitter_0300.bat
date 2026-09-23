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
rem 03:00 slot: X monitoring, independent of the ana-slo pipeline.
rem Uses its own "twitter_monitor" file lock (see runlock.py), so it never
rem contends with the 07:00/07:30 ana-slo tasks' "daily_pipeline" lock.
"%PYTHON%" -u run_daily.py >> "%LOG_FILE%" 2>&1
popd

rem Right after collection, run announce-watch for TODAY (target_date =
rem today's JST date). Forecasts are usually posted the evening before
rem targeting today, so scanning right after the 03:00 collection lets the
rem morning routine start with this already done instead of waiting.
rem See backtest/daily_digest.py docstring: --date is the target date the
rem forecast is FOR, not the date it was posted.
set "PYTHONUTF8=1"
pushd "%ROOT%"
"%PYTHON%" -X utf8 -m backtest.daily_digest announce-watch >> "%LOG_FILE%" 2>&1
popd
endlocal
