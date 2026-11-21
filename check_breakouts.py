import json
with open('live_status.json', 'r') as f:
    d = json.load(f)
print('Active breakouts count:', len(d.get('actionable_breakouts', [])))
for b in d.get('actionable_breakouts', []):
    print(f"  {b['symbol']} {b['direction']} | Entry: ${b['entry_price']} | SL: ${b['sl_price']} ({b['sl_dist_pct']}%) | TP1: ${b['tp1_price']} | TP2: ${b['tp2_price']} | Mode: {b['action_mode']}")
