import requests
import pandas as pd
from institutional_engine import InstitutionalSniperEngine
from indicators import compute_all_indicators

engine = InstitutionalSniperEngine(min_volume_24h_usd=20_000_000)

def fetch_tf(sym, tf, limit=50):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={tf}&limit={limit}"
    r = requests.get(url, timeout=8).json()
    df = pd.DataFrame(r, columns=["open_time","open","high","low","close","volume","ct","qv","tr","tb","tq","ig"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    return compute_all_indicators(df.iloc[:-1])

test_coins = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]
print("="*65)
print("  T.R TECHNOLOGY INSTITUTIONAL SNIPER ENGINE TEST")
print("  Checking 24h Volume, Open Interest (OI), HTF Structure & 1m Triggers")
print("="*65 + "\n")

for sym in test_coins:
    metrics = engine.get_token_market_metrics(sym)
    if not metrics:
        continue

    df_4h = fetch_tf(sym, "4h")
    df_1h = fetch_tf(sym, "1h")
    df_15m = fetch_tf(sym, "15m")
    df_1m = fetch_tf(sym, "1m", limit=35)

    htf = engine.analyze_htf_structure(df_4h, df_1h, df_15m)
    sig = engine.check_sniper_1m_trigger(df_1m, htf, metrics)

    v_m = round(metrics["volume_24h_usd"] / 1e6, 1)
    oi_m = round(metrics["oi_usd"] / 1e6, 1)
    f_pct = round(metrics["funding_rate"] * 100, 4)

    print(f"[{sym}] Price: ${metrics['price']} | 24h Vol: ${v_m}M | OI: ${oi_m}M | Funding: {f_pct:+.4f}%")
    print(f"       Market Structure: 4h={htf['trend_4h']}, 1h={htf['trend_1h']}, 15m={htf['trend_15m']} | Aligned: {htf['aligned']}")
    if sig:
        print(f"       🎯 [SNIPER SIGNAL] {sig.direction} | Target Gain: +{sig.target_gain_pct}% | R:R {sig.rr_ratio} | VolSurge: {sig.volume_surge}x")
        print(f"          SL: ${sig.sl_price} | TP1: ${sig.tp1_price} | TP2: ${sig.tp2_price}")
    else:
        print(f"       ⏳ Waiting for 1m pullback volume surge + HTF alignment")
    print()
