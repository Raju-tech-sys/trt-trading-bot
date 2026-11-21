from pro_trader_v8 import BinanceFuturesClient, ProTraderV8Bot
import json

api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"

client = BinanceFuturesClient(api_key, api_secret, testnet=True)
bot = ProTraderV8Bot(client)
bot.run_cycle()

with open("live_status.json") as f:
    data = json.load(f)
    print("\n--- SAMPLE ACTIONABLE SETUP ---")
    if data.get("actionable_breakouts"):
        s = data["actionable_breakouts"][0]
        print("Symbol:", s.get("symbol"))
        print("Current Price:", s.get("current_price"))
        print("Entry Price:", s.get("entry_price"))
        print("SL Price:", s.get("sl_price"))
        print("Status:", s.get("status"))
        print("Is Invalid:", s.get("is_invalid"))
        print("Timestamp:", s.get("detected_timestamp"))
        print("Detected at:", s.get("detected_at"))
