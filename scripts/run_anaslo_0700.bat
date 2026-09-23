@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%ROOT%\scraper\twitter_monitor\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\morning_0700_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%"
rem 07:00 slot: ana-slo attempt, then --only-if-complete decides whether to
rem keep going. ana-slo publishes around 07:30 (irregularly), so this often
rem comes up short -- that is expected, not a failure. But when it DOES come
rem up complete this early, there is no reason to wait 30 minutes for 07:30:
rem run_morning.py checks every hall's max date and, if all reached
rem yesterday, finishes history / announce scoring / forward freeze right
rem here. If any hall is still short, it stops and leaves the rest to the
rem 07:30 task (run_morning.bat), which always runs to completion regardless.
"%PYTHON%" -u scripts\run_morning.py --skip-twitter --only-if-complete >> "%LOG_FILE%" 2>&1
popd
endlocal
