import requests

r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=10).json()
usdt_pairs = [p for p in r if p['symbol'].endswith('USDT') and float(p.get('quoteVolume', 0)) >= 15000000]
print(f'Total USDT pairs with >15M 24h vol: {len(usdt_pairs)}')

usdt_pairs.sort(key=lambda x: float(x['priceChangePercent']), reverse=True)
print('\n--- Top 5 Gainers ---')
for p in usdt_pairs[:5]:
    vol = float(p['quoteVolume']) / 1e6
    print(f"  {p['symbol']}: {float(p['priceChangePercent']):+.2f}% | Vol: ${vol:.1f}M | Price: {p['lastPrice']}")

print('\n--- Top 5 Losers ---')
for p in reversed(usdt_pairs[-5:]):
    vol = float(p['quoteVolume']) / 1e6
    print(f"  {p['symbol']}: {float(p['priceChangePercent']):+.2f}% | Vol: ${vol:.1f}M | Price: {p['lastPrice']}")
