@echo off
set "ROOT=%~dp0"
"%ROOT%runtime\python\python.exe" "%ROOT%my-agent\launcher.py" "%~1"
pause
 