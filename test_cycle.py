import sys
from pro_trader_v8 import BinanceFuturesClient, ProTraderV8Bot

api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"

client = BinanceFuturesClient(api_key, api_secret, testnet=True)
bot = ProTraderV8Bot(client)
print("Running single cycle test...")
bot.run_cycle()
print("Cycle completed successfully!")
