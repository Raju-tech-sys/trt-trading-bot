"""
T.R Technology — Backtest Runner (Phase 2)

Usage:
    python main.py                          # Full backtest, both coins
    python main.py --coin SOLUSDT           # Single coin
    python main.py --start 2024-11-01 --end 2026-11-01
    python main.py --oos                    # Out-of-sample split
    python main.py --sensitivity            # Parameter sensitivity
    python main.py --walk-forward           # Walk-forward analysis
    python main.py --all                    # Everything
"""
import argparse
import os
import sys
import time

import config as cfg
from data_fetcher import load_all_data
from indicators import compute_all_indicators
from backtest_engine import BacktestEngine
from analytics import (
    trades_to_dataframe, compute_metrics, compute_module_breakdown,
    compute_monthly_returns, walk_forward_analysis, parameter_sensitivity_check,
    check_pass_criteria, generate_report
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results")


def prepare_data(raw):
    prepared = {}
    for sym, frames in raw.items():
        print(f"\nComputing indicators for {sym}...")
        prepared[sym] = {
            "15m": compute_all_indicators(frames["15m"]),
            "1h":  compute_all_indicators(frames["1h"]),
            "4h":  compute_all_indicators(frames["4h"]),
            "funding": frames["funding"],
        }
        for tf in ["15m", "1h", "4h"]:
            print(f"  {tf}: {len(prepared[sym][tf])} candles")
    return prepared


def run_full(data, coins):
    for coin in coins:
        print(f"\n{'='*60}\n  BACKTEST: {coin}\n{'='*60}")
        eng = BacktestEngine(cfg.INITIAL_CAPITAL)
        trades = eng.run(data[coin], coin)
        print(f"  {len(trades)} trade results | Final: ${eng.capital:.2f}")
        generate_report(trades, cfg.INITIAL_CAPITAL, coin, OUTPUT_DIR)


def run_oos(data, coins):
    for coin in coins:
        print(f"\n{'='*60}\n  OOS BACKTEST: {coin}\n{'='*60}")
        total = len(data[coin]["15m"])
        split = int(total * (1 - cfg.OUT_OF_SAMPLE_RATIO))
        print(f"\n  In-Sample (70%: {split} candles)")
        e1 = BacktestEngine(cfg.INITIAL_CAPITAL)
        t1 = e1.run(data[coin], coin, end_idx=split)
        m1 = compute_metrics(trades_to_dataframe(t1), cfg.INITIAL_CAPITAL)
        
        print(f"\n  Out-of-Sample (30%: {total-split} candles)")
        e2 = BacktestEngine(cfg.INITIAL_CAPITAL)
        t2 = e2.run(data[coin], coin, start_idx=split)
        m2 = compute_metrics(trades_to_dataframe(t2), cfg.INITIAL_CAPITAL)
        
        print(f"\n  {'Metric':<25} {'IS':>12} {'OOS':>15}")
        print(f"  {'-'*52}")
        for k in ["total_trades", "win_rate", "profit_factor", "expectancy_r", "max_drawdown_pct", "total_pnl"]:
            print(f"  {k:<25} {str(m1.get(k, 'N/A')):>12} {str(m2.get(k, 'N/A')):>15}")
            
        if m1.get("profit_factor", 0) > 0 and m2.get("profit_factor", 0) > 0:
            div = abs(m1["profit_factor"] - m2["profit_factor"]) / m1["profit_factor"]
            print(f"\n  PF Divergence: {div*100:.1f}%  {'OK' if div < 0.2 else 'TOO HIGH'}")


def run_sensitivity(data, coins):
    params = {
        "ADX_TREND_THRESHOLD": [22, 23, 24, 25, 26, 27, 28],
        "MOD_A_SL_ATR_MULT": [1.0, 1.25, 1.5, 1.75, 2.0],
        "MOD_B_RSI_OVERSOLD": [25, 28, 30, 32, 35],
        "MOD_B_RSI_OVERBOUGHT": [65, 68, 70, 72, 75],
    }
    for coin in coins:
        print(f"\n{'='*60}\n  SENSITIVITY: {coin}\n{'='*60}")
        for pn, vals in params.items():
            print(f"\n  {pn}: {vals}")
            res = parameter_sensitivity_check(BacktestEngine, data[coin], coin, pn, vals, cfg.INITIAL_CAPITAL)
            print(f"  {'Val':>8} {'Trades':>8} {'PF':>8} {'Exp(R)':>8} {'DD%':>8}")
            for r in res:
                print(f"  {r['param_value']:>8} {r.get('total_trades', 0):>8} "
                    f"{r.get('profit_factor', 0):>8.2f} {r.get('expectancy_r', 0):>8.4f} "
                    f"{r.get('max_drawdown_pct', 0):>8.2f}")


def run_wf(data, coins):
    for coin in coins:
        print(f"\n{'='*60}\n  WALK-FORWARD: {coin}\n{'='*60}")
        eng = BacktestEngine(cfg.INITIAL_CAPITAL)
        trades = eng.run(data[coin], coin)
        wf = walk_forward_analysis(trades_to_dataframe(trades), cfg.INITIAL_CAPITAL, cfg.WALK_FORWARD_PERIODS)
        profitable = 0
        for p in wf:
            pf = p.get("profit_factor", 0)
            if pf >= 1.0:
                profitable += 1
            print(f"  {'Y' if pf >= 1 else 'N'} Period {p['period']}: "
                f"{p['start_date'][:10]} -> {p['end_date'][:10]}  "
                f"Trades={p.get('total_trades', 0)}  PF={pf:.2f}")
        print(f"\n  Profitable: {profitable}/{len(wf)} {'PASS' if profitable > len(wf)/2 else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser(description="T.R Technology Backtest")
    ap.add_argument("--coin", type=str, default=None)
    ap.add_argument("--start", type=str, default="2024-11-01")
    ap.add_argument("--end", type=str, default="2026-11-01")
    ap.add_argument("--oos", action="store_true")
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--walk-forward", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    coins = [args.coin] if args.coin else cfg.PAIRS
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("+" + "="*58 + "+")
    print("|  T.R TECHNOLOGY — BACKTEST ENGINE v1.0                  |")
    print("|  Module A (Trend Pullback) + Module B (Range)           |")
    print("+" + "="*58 + "+")
    print(f"\n  Coins:   {coins}")
    print(f"  Period:  {args.start} -> {args.end}")
    print(f"  Capital: ${cfg.INITIAL_CAPITAL}")
    print(f"  Fees:    Taker {cfg.TAKER_FEE*100}% | Maker {cfg.MAKER_FEE*100}% | Slip {cfg.SLIPPAGE*100}%")

    print(f"\n{'~'*60}\n  STEP 1: Fetching data...\n{'~'*60}")
    t0 = time.time()
    raw = load_all_data(coins, args.start, args.end)

    print(f"\n{'~'*60}\n  STEP 2: Computing indicators...\n{'~'*60}")
    data = prepare_data(raw)
    print(f"\n  Data ready in {time.time()-t0:.1f}s")

    print(f"\n{'~'*60}\n  STEP 3: Running backtest...\n{'~'*60}")
    run_full(data, coins)

    if args.oos or args.all:
        run_oos(data, coins)
    if args.walk_forward or args.all:
        run_wf(data, coins)
    if args.sensitivity or args.all:
        run_sensitivity(data, coins)

    print(f"\n{'='*60}\n  Results: {os.path.abspath(OUTPUT_DIR)}\n{'='*60}")


if __name__ == "__main__":
    main()
