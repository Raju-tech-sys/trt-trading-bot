import requests, time

print('Checking Render deployment status...')
for i in range(6):
    try:
        r = requests.get('https://trt-trading-bot.onrender.com/api/live', timeout=8)
        d = r.json()
        print(f"Attempt {i+1}: Status={d.get('status')} | Balance={d.get('balance')} | Open={len(d.get('open_positions', []))} | Gainers={len(d.get('gainers', []))} | Squeezes={len(d.get('squeezes', []))}")
        if len(d.get('gainers', [])) > 0:
            print("✓ Full universe data live on Render!")
            break
    except Exception as e:
        print(f"Attempt {i+1}: Waiting for deploy... ({e})")
    time.sleep(6)
