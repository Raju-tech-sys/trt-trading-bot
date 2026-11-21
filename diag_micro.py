import requests
import pandas as pd
from indicators import compute_all_indicators

def check_micro(sym):
    r = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=25", timeout=6).json()
    df = pd.DataFrame(r, columns=["open_time","open","high","low","close","volume","ct","qv","tr","tb","tq","ig"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df = compute_all_indicators(df.iloc[:-1])
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    avg_v = df.iloc[-21:-1]["volume"].mean()
    vr = curr["volume"] / avg_v if avg_v > 0 else 1.0
    print(f"[{sym}] Close: {curr['close']} | 1m EMA20: {curr['ema_20']:.4f} | RSI: {curr['rsi_14']:.1f} | VolRatio: {vr:.2f}x | ATR: {curr['atr_14']:.4f}")
    touch_ema20 = prev["high"] >= prev["ema_20"] or prev["close"] >= prev["ema_20"]
    print(f"        Prev touched EMA20? {touch_ema20} | Current Red Close? {curr['close'] < curr['open']}")

for s in ["DOGEUSDT", "SOLUSDT", "BTCUSDT"]:
    check_micro(s)
