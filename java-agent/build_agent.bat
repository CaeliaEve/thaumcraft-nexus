@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_agent.ps1" %*
exit /b %ERRORLEVEL%
