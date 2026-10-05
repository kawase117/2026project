@echo off
cd /d %~dp0\..\..
set PYTHONUTF8=1
venv\Scripts\python.exe -m scraper.daidata.run_mitoya_complete
