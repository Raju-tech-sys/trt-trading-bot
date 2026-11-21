import requests
d = requests.get('http://localhost:8080/api/live').json()
print("Live API Breakouts:", len(d.get('actionable_breakouts', [])))
for b in d.get('actionable_breakouts', []):
    print("  Symbol:", b['symbol'], b['direction'], "Entry:", b['entry_price'], "SL:", b['sl_price'], "TP1:", b['tp1_price'], "TP2:", b['tp2_price'])
