@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%ROOT%\scraper\twitter_monitor\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\persistent_weekly_%RUN_DATE%.log"
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%"
rem Weekly (Monday after the morning run): persistent-unit list, frozen for forward testing.
rem   1. score: grade frozen lists whose following week has ended (do this first so the new
rem      list is not graded against itself).
rem   2. weekly: compute and freeze this week's list. Exit 1 when this as-of date is already
rem      frozen (re-run the same day) -- expected, not a failure.
rem   3. auto_commit_push: commits only the allow-listed machine output (backtest/persistent).
rem Rules and the pre-registered judgment: backtest/persistent_units.py, HYPOTHESIS_LEDGER.md
rem (persist-units-weekly).
"%PYTHON%" -u -m backtest.persistent_units score >> "%LOG_FILE%" 2>&1
"%PYTHON%" -u -m backtest.persistent_units weekly >> "%LOG_FILE%" 2>&1
"%PYTHON%" -u scripts\auto_commit_push.py >> "%LOG_FILE%" 2>&1
popd
endlocal
