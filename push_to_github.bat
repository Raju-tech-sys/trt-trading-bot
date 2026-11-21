@echo off
title TRT Pro Trader — 1-Click Push to GitHub
color 0B
echo ==============================================================================
echo   T.R TECHNOLOGY — 1-CLICK AUTO-PUSH TO GITHUB & RENDER CLOUD
echo ==============================================================================
echo.

set "PATH=%PATH%;C:\Users\FanixOP\.local\bin\git\cmd"
cd /d "%~dp0"

echo [1/3] Adding changed files to git...
git add -A

echo [2/3] Committing changes...
git commit -m "Auto-update: %DATE% %TIME%"

echo [3/3] Pushing to GitHub (main branch)...
git push origin main

echo.
echo ==============================================================================
echo   SUCCESS! Pushed to GitHub!
echo   Render.com is now automatically deploying your live update!
echo   Live URL: https://trt-trading-bot.onrender.com
echo ==============================================================================
echo.
timeout /t 5
