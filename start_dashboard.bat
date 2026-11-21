@echo off
title T.R Technology Live Web Dashboard (Port 8080)
color 0B
echo ==============================================================================
echo   T.R TECHNOLOGY LIVE WEB DASHBOARD SERVER
echo   Opening http://localhost:8080 in your browser...
echo ==============================================================================
echo.
cd /d "%~dp0"
start http://localhost:8080
.\.venv\Scripts\python.exe -u web_server.py
pause
