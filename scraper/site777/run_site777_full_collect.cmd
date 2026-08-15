@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_site777_full_collect_parallel.ps1" %*
exit /b %ERRORLEVEL%
