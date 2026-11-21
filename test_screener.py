import time
import requests
import pandas as pd
import numpy as np

# Load testnet symbols
r_testnet = requests.get('https://testnet.binancefuture.com/fapi/v1/exchangeInfo', timeout=10).json()
testnet_symbols = {s['symbol'] for s in r_testnet.get('symbols', []) if s.get('status') == 'TRADING'}

# Load mainnet 24h ticker
r_mainnet = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=10).json()
candidates = []
for p in r_mainnet:
    sym = p['symbol']
    vol = float(p.get('quoteVolume', 0))
    if sym.endswith('USDT') and vol >= 10000000 and sym in testnet_symbols:
        candidates.append({
            'symbol': sym,
            'change': float(p['priceChangePercent']),
            'vol': vol,
            'price': float(p['lastPrice'])
        })

print(f"Total eligible symbols: {len(candidates)}")

# Sort by volume and extreme momentum
candidates.sort(key=lambda x: x['vol'], reverse=True)
top_pool = candidates[:40] # Analyze top 40 liquid symbols

print("Screening top 40 liquid symbols for institutional breakout/breakdown...")

session = requests.Session()

results = []
for c in top_pool:
    sym = c['symbol']
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=30"
        r = session.get(url, timeout=4).json()
        if not isinstance(r, list) or len(r) < 25:
            continue
        
        df = pd.DataFrame(r, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        
        # Consolidation check (prior 16 candles)
        prior = df.iloc[-17:-1]
        box_high = prior["high"].max()
        box_low = prior["low"].min()
        box_range = box_high - box_low
        mid = (box_high + box_low) / 2.0
        box_pct = (box_range / mid) * 100.0 if mid > 0 else 999.0
        
        curr = df.iloc[-1]
        close = curr["close"]
        open_p = curr["open"]
        high = curr["high"]
        low = curr["low"]
        rng = high - low
        body = abs(close - open_p)
        
        disp = body / rng if rng > 0 else 0
        avg_vol = df.iloc[-21:-1]["volume"].mean()
        vol_surge = curr["volume"] / avg_vol if avg_vol > 0 else 1.0
        
        # Check breakout
        # Bullish
        upper_wick = high - max(close, open_p)
        lower_wick = min(close, open_p) - low
        upper_wick_ratio = upper_wick / rng if rng > 0 else 1.0
        lower_wick_ratio = lower_wick / rng if rng > 0 else 1.0
        
        is_bullish = (close > box_high and close > open_p and box_pct <= 4.0 and disp >= 0.55 and vol_surge >= 1.25 and upper_wick_ratio < 0.28)
        is_bearish = (close < box_low and close < open_p and box_pct <= 4.0 and disp >= 0.55 and vol_surge >= 1.25 and lower_wick_ratio < 0.28)
        
        results.append({
            'symbol': sym,
            'change': c['change'],
            'box_pct': round(box_pct, 2),
            'vol_surge': round(vol_surge, 2),
            'disp': round(disp, 2),
            'bullish': is_bullish,
            'bearish': is_bearish,
            'price': close
        })
        time.sleep(0.05)
    except Exception as e:
        pass

print(f"\nScanned {len(results)} symbols.")
breakouts = [r for r in results if r['bullish'] or r['bearish']]
print(f"Active High-Probability Setups: {len(breakouts)}")
for b in breakouts:
    direction = "BULLISH BREAKOUT 🚀" if b['bullish'] else "BEARISH BREAKDOWN 💥"
    print(f"  {b['symbol']:<12} | {direction} | Box: {b['box_pct']}% | Vol Surge: {b['vol_surge']}x | Body: {int(b['disp']*100)}%")

if not breakouts:
    print("No sudden breakout candle currently printing on 15m. Showing top 5 tightest consolidations:")
    results.sort(key=lambda x: x['box_pct'])
    for b in results[:5]:
        print(f"  {b['symbol']:<12} | Box Squeeze: {b['box_pct']}% | Vol Surge: {b['vol_surge']}x | Body: {int(b['disp']*100)}%")
