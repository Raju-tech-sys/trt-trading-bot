@echo off
title T.R Technology Pro Trader v8.0 Universe Breakout & Institutional Bot
color 0A
echo ==============================================================================
echo   T.R TECHNOLOGY PRO TRADER v8.0 — UNIVERSE SCANNER ^& INSTITUTIONAL BOT
echo   - Scans 140+ Binance Futures USDT Pairs (Top Gainers, Losers, Squeezes)
echo   - MODULE 1: SMC Pullback Reversals (Trend Alignment + Discount Rejection)
echo   - MODULE 2: Institutional Breakout Engine (4H Squeeze + Vol Surge + Wick Filter)
echo   - Safe Structural SL (0.8%% - 1.5%% Breathing Room) ^| Dynamic 1%% Risk
echo ==============================================================================
echo.
cd /d "%~dp0"
.\.venv\Scripts\python.exe -u pro_trader_v8.py
pause
