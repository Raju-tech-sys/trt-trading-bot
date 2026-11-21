import requests
import pandas as pd
from indicators import compute_all_indicators

sym = "BNBUSDT"
url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=30"
r = requests.get(url, timeout=5).json()
df = pd.DataFrame(r, columns=[
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"
])
for col in ["open", "high", "low", "close", "volume"]:
    df[col] = df[col].astype(float)
df = compute_all_indicators(df)
c1 = df.iloc[-1]
c_prev = df.iloc[-2]
print(f"BNBUSDT 1H Close: {c1['close']} | EMA20: {c1['ema_20']:.2f} | EMA50: {c1['ema_50']:.2f} | RSI14: {c1['rsi_14']:.2f}")
print(f"1H Trend: {'BULLISH' if c1['close'] > c1['ema_20'] and c1['ema_20'] > c1['ema_50'] else 'MIXED/BEARISH'}")
