@echo off
rem 蒲田5ホールのクイック収集を1回実行する（Windowsタスクスケジューラから1時間ごとに呼ぶ）。
rem 出力: scraper\realtime\output\snapshots\*.jsonl ／ ログ: logs\realtime_quick_YYYYMMDD.log
rem 失敗してもスケジューラ側で終了コードを見られるよう、pythonの終了コードをそのまま返す。
setlocal
cd /d "%~dp0\..\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%d
echo ===== %date% %time% start ===== >> logs\realtime_quick_%TODAY%.log
venv\Scripts\python.exe -m scraper.realtime.run --halls all --mode quick >> logs\realtime_quick_%TODAY%.log 2>&1
set RC=%ERRORLEVEL%
echo ===== %date% %time% end rc=%RC% ===== >> logs\realtime_quick_%TODAY%.log
exit /b %RC%
