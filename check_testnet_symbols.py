import requests

r_testnet = requests.get('https://testnet.binancefuture.com/fapi/v1/exchangeInfo', timeout=10).json()
testnet_symbols = {s['symbol'] for s in r_testnet.get('symbols', []) if s.get('status') == 'TRADING'}
print(f"Total trading symbols on Testnet: {len(testnet_symbols)}")

r_mainnet = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=10).json()
valid_pairs = []
for p in r_mainnet:
    sym = p['symbol']
    vol = float(p.get('quoteVolume', 0))
    if sym.endswith('USDT') and vol >= 10000000:
        in_testnet = sym in testnet_symbols
        valid_pairs.append({
            'symbol': sym,
            'change': float(p['priceChangePercent']),
            'vol': vol,
            'in_testnet': in_testnet
        })

print(f"Total >10M USDT pairs on Mainnet: {len(valid_pairs)}")
testnet_supported = [p for p in valid_pairs if p['in_testnet']]
print(f"Of those, supported on Testnet: {len(testnet_supported)}")
print("Sample supported pairs:", [p['symbol'] for p in testnet_supported[:15]])
