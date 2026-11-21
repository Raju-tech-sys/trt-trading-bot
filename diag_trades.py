import hmac
import hashlib
import time
import requests
import urllib.parse

api_key = 'iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy'
api_secret = b'7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG'
base = 'https://testnet.binancefuture.com'

def sign(params):
    params['timestamp'] = int(time.time() * 1000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(api_secret, q.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{q}&signature={sig}'

trades = requests.get(f'{base}/fapi/v1/userTrades?' + sign({'limit': 30}), headers={'X-MBX-APIKEY': api_key}).json()
print('=== ALL EXECUTED TRADES ON BINANCE ===')
total_pnl = 0
for t in trades:
    pnl = float(t.get('realizedPnl', 0))
    fee = float(t.get('commission', 0))
    total_pnl += pnl - fee
    timestr = time.strftime('%H:%M:%S', time.gmtime(t['time']/1000))
    sym = t['symbol']
    side = t['side']
    qty = float(t['qty'])
    price = float(t['price'])
    print(f"{timestr} | {sym:<9} | {side:<4} | Qty: {qty:<8.3f} | Price: ${price:<9.2f} | PnL: ${pnl:<8.2f} | Fee: ${fee:.2f}")

print(f'\nTOTAL REALIZED PNL (NET OF FEES): ${total_pnl:.2f}')

pos = requests.get(f'{base}/fapi/v2/positionRisk?' + sign({}), headers={'X-MBX-APIKEY': api_key}).json()
active = [p for p in pos if float(p.get('positionAmt', 0)) != 0]
print('\n=== CURRENT OPEN POSITIONS ===')
for p in active:
    print(p['symbol'], p['positionAmt'], 'Entry:', p['entryPrice'], 'Mark:', p['markPrice'], 'PnL:', p['unRealizedProfit'])
