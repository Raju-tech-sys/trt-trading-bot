"""
T.R Technology — Cloud Runner for Render.com (Free Tier)
Runs both:
1. Pro Trader v8.0 Universe & Institutional Engine (Thread)
2. Real-Time Web Server & API Bridge (Main Thread)
"""
import os
import sys
import time
import threading

BOT_HEALTH = {
    "started": False,
    "last_error": None,
    "restarts": 0,
}

def run_bot_thread():
    print("[CLOUD RUNNER] Starting Pro Trader v8.0 Universe Engine Thread...", flush=True)
    BOT_HEALTH["started"] = True
    time.sleep(2)
    while True:
        try:
            from pro_trader_v8 import BinanceFuturesClient, ProTraderV8Bot
            api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
            api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
            client = BinanceFuturesClient(api_key, api_secret, testnet=True)
            bot = ProTraderV8Bot(client)
            bot.start()
        except Exception as e:
            BOT_HEALTH["last_error"] = str(e)
            BOT_HEALTH["restarts"] += 1
            print(f"[CLOUD RUNNER ERROR] Bot thread exception: {e}. Restarting in 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    # Ensure current directory is the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # 1. Start bot daemon in background thread
    t = threading.Thread(target=run_bot_thread, name="ProTraderBotThread", daemon=True)
    t.start()

    # 2. Start web server on main thread
    from web_server import run_server
    port = int(os.environ.get("PORT", 8080))
    print(f"[CLOUD RUNNER] Starting Web Server on PORT {port}...", flush=True)
    run_server()
