"""
T.R Technology — Cloud Runner for Render.com (Free Tier)
Launches:
1. Pro Trader v8.0 Dual-Engine & Universe Scanner (in background thread/process)
2. Real-Time Web Server & API Bridge on the cloud PORT
"""
import os
import sys
import time
import subprocess
import threading

def run_bot_daemon():
    print("[CLOUD RUNNER] Starting Pro Trader v8.0 Universe Daemon...")
    time.sleep(1)
    while True:
        try:
            bot_process = subprocess.Popen([sys.executable, "-u", "pro_trader_v8.py"])
            bot_process.wait()
            print("[CLOUD RUNNER] Bot process ended. Restarting in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"[CLOUD RUNNER] Bot runner error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # 1. Start bot daemon in background thread
    t = threading.Thread(target=run_bot_daemon, daemon=True)
    t.start()

    # 2. Start web server on main thread
    from web_server import run_server
    print(f"[CLOUD RUNNER] Starting Web Server on PORT {os.environ.get('PORT', 8080)}...")
    run_server()
