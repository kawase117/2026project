@echo off
setlocal
set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%~dp0logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG_FILE=%LOG_DIR%\run_%RUN_DATE%.log"
pushd "%ROOT%"
"%PYTHON%" scraper\twitter_monitor\scrape_tweets.py >> "%LOG_FILE%" 2>&1
"%PYTHON%" scraper\twitter_monitor\extract_answers.py >> "%LOG_FILE%" 2>&1
popd
endlocal
