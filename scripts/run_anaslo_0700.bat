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
rem 07:00 slot: ana-slo first attempt only. ana-slo publishes around 07:30
rem (irregularly), so this often comes up empty -- that is expected, not a
rem failure. The 07:30 task (run_morning.bat) retries and does the rest
rem (DB update / history / announce scoring / forward freeze) once.
"%PYTHON%" -u scripts\run_morning.py --skip-history --skip-forward --skip-announce-score --skip-twitter >> "%LOG_FILE%" 2>&1
popd
endlocal
