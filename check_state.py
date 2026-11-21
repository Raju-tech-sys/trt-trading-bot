import requests, time, hmac, hashlib, urllib.parse

API_KEY = 'iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy'
SECRET  = '7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG'
BASE = 'https://testnet.binancefuture.com'

def signed_get(ep, extra={}):
    p = {'timestamp': int(time.time()*1000), 'recvWindow': 10000}
    p.update(extra)
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f'{BASE}{ep}?{qs}&signature={sig}'
    r = requests.get(url, headers={'X-MBX-APIKEY': API_KEY}, timeout=10)
    return r.json()

# Get positions
positions = signed_get('/fapi/v2/positionRisk')
open_pos = [p for p in positions if float(p.get('positionAmt',0)) != 0]
print('=== OPEN POSITIONS ===')
for p in open_pos:
    side = 'LONG' if float(p['positionAmt']) > 0 else 'SHORT'
    print(f"  {p['symbol']} | {side} | Qty: {p['positionAmt']} | Entry: {p['entryPrice']} | Mark: {p['markPrice']} | PnL: {p['unRealizedProfit']}")

# Get account balance
acct = signed_get('/fapi/v2/account')
print(f"\nBalance: {acct.get('totalWalletBalance','?')} USDT")
print(f"Available: {acct.get('availableBalance','?')} USDT")

# Get recent trades for relevant symbols
print('\n=== RECENT TRADES (last 5 per symbol) ===')
for sym in ['ETHUSDT', 'BTCUSDT', 'SOLUSDT']:
    trades = signed_get('/fapi/v1/userTrades', {'symbol': sym, 'limit': 10})
    if trades:
        for t in trades[-5:]:
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(t['time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  {t['symbol']} | {t['side']} | Qty: {t['qty']} | Price: {t['price']} | PnL: {t['realizedPnl']} | {ts}")

# Get open orders
print('\n=== OPEN ORDERS ===')
orders = signed_get('/fapi/v1/openOrders')
for o in orders:
    stop = o.get('stopPrice', '')
    price = o.get('price', '')
    print(f"  {o['symbol']} | {o['type']} | {o['side']} | StopPrice: {stop} | Price: {price} | Qty: {o['origQty']} | Status: {o['status']}")

# Get algo orders
print('\n=== ALGO ORDERS ===')
try:
    algo = signed_get('/fapi/v1/algoOrders', {'status': 'WORKING'})
    if isinstance(algo, dict) and 'orders' in algo:
        for o in algo['orders']:
            print(f"  {o.get('symbol','')} | {o.get('side','')} | StopPrice: {o.get('stopPrice','')} | Qty: {o.get('origQty','')}")
    elif isinstance(algo, list):
        for o in algo:
            print(f"  {o}")
    else:
        print(f"  Response: {algo}")
except Exception as e:
    print(f"  Error: {e}")
