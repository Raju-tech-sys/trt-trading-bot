import requests, json
r = requests.get('http://localhost:8080/api/live', timeout=5)
d = r.json()
print(f"Status: {d['status']}")
bal = d['balance']
print(f"Balance: {bal}")
print(f"Positions ({len(d['open_positions'])}):")
for p in d['open_positions']:
    print(f"  {p['symbol']} | {p['side']} | Size: {p['size']} | Entry: {p['entryPrice']} | Mark: {p['markPrice']} | PnL: {p['unrealizedPnl']}")
