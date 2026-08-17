@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_site777_graph_collect.ps1"
exit /b %ERRORLEVEL%
