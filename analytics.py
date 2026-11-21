"""
T.R Technology — Backtest Analytics & Reporting
Computes all metrics from the rule file pass criteria.
"""
import pandas as pd
import numpy as np
from dataclasses import asdict
import os


def trades_to_dataframe(trades):
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([asdict(t) for t in trades])


def compute_metrics(df, initial_capital):
    if df.empty:
        return {"total_trades": 0, "error": "No trades"}
    m = {}
    m["total_trades"] = len(df)
    m["wins"] = int((df["pnl_after_fees"] > 0).sum())
    m["losses"] = int((df["pnl_after_fees"] <= 0).sum())
    m["win_rate"] = round(m["wins"] / m["total_trades"], 4) if m["total_trades"] else 0
    m["total_pnl"] = round(df["pnl_after_fees"].sum(), 2)
    m["total_fees"] = round(df["fee_paid"].sum(), 2)
    m["total_return_pct"] = round(m["total_pnl"] / initial_capital * 100, 2)
    
    gp = df[df["pnl_after_fees"] > 0]["pnl_after_fees"].sum()
    gl = abs(df[df["pnl_after_fees"] <= 0]["pnl_after_fees"].sum())
    m["profit_factor"] = round(gp / gl, 4) if gl > 0 else float("inf")
    
    m["expectancy_r"] = round(df["result_r"].mean(), 4)
    m["expectancy_usd"] = round(df["pnl_after_fees"].mean(), 4)
    
    w = df[df["result_r"] > 0]
    l = df[df["result_r"] <= 0]
    m["avg_r_win"] = round(w["result_r"].mean(), 4) if len(w) else 0
    m["avg_r_loss"] = round(l["result_r"].mean(), 4) if len(l) else 0
    
    eq = initial_capital + df["pnl_after_fees"].cumsum()
    pk = eq.cummax()
    dd = (pk - eq) / pk
    m["max_drawdown_pct"] = round(dd.max() * 100, 2)
    m["max_drawdown_usd"] = round((pk - eq).max(), 2)
    
    try:
        dur = pd.to_datetime(df["exit_time"]) - pd.to_datetime(df["entry_time"])
        m["avg_trade_duration"] = str(dur.mean())
    except Exception:
        m["avg_trade_duration"] = "N/A"
        
    return m


def compute_module_breakdown(df, initial_capital):
    return {
        mod: compute_metrics(df[df["module"] == mod], initial_capital)
        for mod in df["module"].unique()
    }


def compute_monthly_returns(df, initial_capital):
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["exit_month"] = pd.to_datetime(df["exit_time"]).dt.to_period("M")
    monthly = df.groupby("exit_month").agg(
        trades=("pnl_after_fees", "count"),
        pnl=("pnl_after_fees", "sum"),
        fees=("fee_paid", "sum")
    ).reset_index()
    
    cap = initial_capital
    rets = []
    for _, r in monthly.iterrows():
        rets.append(r["pnl"] / cap * 100)
        cap += r["pnl"]
    monthly["return_pct"] = rets
    return monthly


def walk_forward_analysis(df, initial_capital, n=3):
    if df.empty or len(df) < n:
        return []
    df = df.sort_values("entry_time").reset_index(drop=True)
    cs = len(df) // n
    results = []
    for i in range(n):
        s = i * cs
        e = (i + 1) * cs if i < n - 1 else len(df)
        chunk = df.iloc[s:e]
        m = compute_metrics(chunk, initial_capital)
        m["period"] = i + 1
        m["start_date"] = str(chunk["entry_time"].min())
        m["end_date"] = str(chunk["exit_time"].max())
        results.append(m)
    return results


def parameter_sensitivity_check(engine_class, data, coin, param_name, values, capital):
    import config as cfg
    orig = getattr(cfg, param_name)
    results = []
    for v in values:
        setattr(cfg, param_name, v)
        eng = engine_class(capital)
        trades = eng.run(data, coin)
        m = compute_metrics(trades_to_dataframe(trades), capital)
        m["param_name"] = param_name
        m["param_value"] = v
        results.append(m)
    setattr(cfg, param_name, orig)
    return results


def check_pass_criteria(metrics, min_trades=100, min_pf=1.3, max_dd=15.0):
    r = {}
    r["min_trades"] = {
        "pass": metrics.get("total_trades", 0) >= min_trades,
        "actual": metrics.get("total_trades", 0),
        "required": f">= {min_trades}"
    }
    r["profit_factor"] = {
        "pass": metrics.get("profit_factor", 0) >= min_pf,
        "actual": metrics.get("profit_factor", 0),
        "required": f">= {min_pf}"
    }
    r["max_drawdown"] = {
        "pass": metrics.get("max_drawdown_pct", 100) < max_dd,
        "actual": f"{metrics.get('max_drawdown_pct', 100)}%",
        "required": f"< {max_dd}%"
    }
    r["expectancy"] = {
        "pass": metrics.get("expectancy_r", -1) > 0,
        "actual": metrics.get("expectancy_r", -1),
        "required": "> 0"
    }
    return r


def generate_report(trades, initial_capital, coin, output_dir="."):
    df = trades_to_dataframe(trades)
    if df.empty:
        return "No trades."
    metrics = compute_metrics(df, initial_capital)
    breakdown = compute_module_breakdown(df, initial_capital)
    monthly = compute_monthly_returns(df, initial_capital)
    wf = walk_forward_analysis(df, initial_capital)
    pc = check_pass_criteria(metrics)
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  T.R TECHNOLOGY BACKTEST REPORT — {coin}")
    lines.append(f"  Initial Capital: ${initial_capital:.2f}")
    lines.append(f"{'='*60}\n")
    
    lines.append("── OVERALL ──")
    for k, v in metrics.items():
        if k != "error":
            lines.append(f"  {k:.<30} {v}")
    
    lines.append("\n── MODULE BREAKDOWN ──")
    for mod, m in breakdown.items():
        lines.append(f"  Module {mod}:")
        for k, v in m.items():
            if k not in ("error", "module"):
                lines.append(f"    {k:.<28} {v}")
    
    lines.append("\n── MONTHLY RETURNS ──")
    if not monthly.empty:
        for _, r in monthly.iterrows():
            lines.append(f"  {r['exit_month']}: {r['trades']:>3} trades  "
                f"PnL: ${r['pnl']:>8.2f}  Return: {r['return_pct']:>6.2f}%")
    
    lines.append("\n── WALK-FORWARD ──")
    for p in wf:
        pf = p.get("profit_factor", 0)
        st = "PASS" if pf >= 1.3 and p.get("expectancy_r", 0) > 0 else "FAIL"
        lines.append(f"  Period {p['period']}: {p['start_date'][:10]} -> {p['end_date'][:10]}  "
            f"PF={pf:.2f}  Exp={p.get('expectancy_r', 0):.4f}R  {st}")
    
    lines.append("\n── PASS CRITERIA ──")
    all_pass = True
    for c, r in pc.items():
        s = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            all_pass = False
        lines.append(f"  {c:.<25} {s}  (actual: {r['actual']}, required: {r['required']})")
    lines.append(f"\n  >>> {'ALL PASSED' if all_pass else 'SOME FAILED'} <<<\n")
    
    report = "\n".join(lines)
    os.makedirs(output_dir, exist_ok=True)
    rp = os.path.join(output_dir, f"backtest_report_{coin}.txt")
    with open(rp, "w") as f:
        f.write(report)
    csv_p = os.path.join(output_dir, f"trades_{coin}.csv")
    df.to_csv(csv_p, index=False)
    print(report)
    return rp
