@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%ROOT%\scraper\twitter_monitor\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\morning_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%"
rem ana-slo is published around 07:30 (irregularly), so this runs after it:
rem yesterday's hall results, then any announcement whose target day has data,
rem then the X pipeline. Order matters -- see run_morning.py's docstring.
"%PYTHON%" -u scripts\run_morning.py >> "%LOG_FILE%" 2>&1
popd
endlocal
