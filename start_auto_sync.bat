@echo off
title TRT Pro Trader — Real-Time Auto Git Sync
color 0E
echo ==============================================================================
echo   TRT PRO TRADER — REAL-TIME AUTO GIT SYNC WATCHER
echo   Monitors file changes and auto-pushes to GitHub -> Render Live Deployment
echo ==============================================================================
echo.
cd /d "%~dp0"
.\.venv\Scripts\python.exe auto_git_sync.py
pause
