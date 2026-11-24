@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0morning_brief.py"
set "morning_status=%errorlevel%"
"%~dp0.venv\Scripts\python.exe" "%~dp0followup_brief.py"
if errorlevel 1 exit /b 1
exit /b %morning_status%
