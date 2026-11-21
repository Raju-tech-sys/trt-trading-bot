"""
T.R Technology — Real-Time Trading Web Server & Live API Bridge
Serves the Interactive Web Dashboard on http://localhost:8080
Provides live Binance Testnet account data, open positions, recent fills, and 1m radar.
"""
import os
import sys
import time
import json
import hmac
import hashlib
import urllib.parse
import threading
import requests
from http.server import HTTPServer, SimpleHTTPRequestHandler

API_KEY = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
API_SECRET = b"7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
BASE_URL = "https://testnet.binancefuture.com"
PORT = int(os.environ.get("PORT", 8080))


def sign(params: dict) -> str:
    params["timestamp"] = int(time.time() * 1000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(API_SECRET, q.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{q}&signature={sig}"


LAST_KNOWN_STATUS = {
    "screened": {},
    "gainers": [],
    "losers": [],
    "squeezes": [],
    "actionable_breakouts": [],
    "total_eligible": 146
}

def fetch_live_binance_state() -> dict:
    global LAST_KNOWN_STATUS
    try:
        # 1. Balance
        bal_res = requests.get(f"{BASE_URL}/fapi/v2/balance?" + sign({}), headers={"X-MBX-APIKEY": API_KEY}, timeout=4).json()
        usdt = next((b for b in bal_res if b.get("asset") == "USDT"), {"balance": 5000, "availableBalance": 5000})

        # 2. Positions
        pos_res = requests.get(f"{BASE_URL}/fapi/v2/positionRisk?" + sign({}), headers={"X-MBX-APIKEY": API_KEY}, timeout=4).json()
        active_pos = [
            {
                "symbol": p["symbol"],
                "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "size": abs(float(p["positionAmt"])),
                "entryPrice": float(p["entryPrice"]),
                "markPrice": float(p["markPrice"]),
                "unrealizedPnl": float(p["unRealizedProfit"]),
                "liquidationPrice": float(p["liquidationPrice"]),
                "leverage": int(p["leverage"]),
                "marginType": p["marginType"]
            }
            for p in pos_res if float(p.get("positionAmt", 0)) != 0
        ]

        # 3. User Trades (Recent Fills)
        trades_res = requests.get(f"{BASE_URL}/fapi/v1/userTrades?" + sign({"limit": 20}), headers={"X-MBX-APIKEY": API_KEY}, timeout=4).json()
        clean_trades = []
        if isinstance(trades_res, list):
            for t in reversed(trades_res):
                clean_trades.append({
                    "id": t.get("id"),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t.get("time", 0) / 1000)),
                    "symbol": t.get("symbol"),
                    "side": t.get("side"),
                    "qty": float(t.get("qty", 0)),
                    "price": float(t.get("price", 0)),
                    "realizedPnl": float(t.get("realizedPnl", 0)),
                    "fee": float(t.get("commission", 0))
                })

        # 4. Read Live Screening Status
        screened = {}
        gainers = []
        losers = []
        squeezes = []
        actionable_breakouts = []
        total_eligible = 146
        status_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_status.json")
        for _ in range(3):
            try:
                if os.path.exists(status_file):
                    with open(status_file, "r", encoding="utf-8") as f:
                        st = json.load(f)
                        if st.get("gainers") or st.get("squeezes"):
                            LAST_KNOWN_STATUS["screened"] = st.get("screened_tokens", {})
                            LAST_KNOWN_STATUS["gainers"] = st.get("gainers", [])
                            LAST_KNOWN_STATUS["losers"] = st.get("losers", [])
                            LAST_KNOWN_STATUS["squeezes"] = st.get("squeezes", [])
                            LAST_KNOWN_STATUS["actionable_breakouts"] = st.get("actionable_breakouts", [])
                            LAST_KNOWN_STATUS["total_eligible"] = st.get("total_eligible_universe", 146)
                    break
            except Exception:
                time.sleep(0.05)

        return {
            "status": "ONLINE",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "balance": round(float(usdt["balance"]), 2),
            "available": round(float(usdt["availableBalance"]), 2),
            "total_unrealized_pnl": round(sum(p["unrealizedPnl"] for p in active_pos), 2),
            "open_positions": active_pos,
            "recent_trades": clean_trades,
            "screened_tokens": LAST_KNOWN_STATUS["screened"],
            "gainers": LAST_KNOWN_STATUS["gainers"],
            "losers": LAST_KNOWN_STATUS["losers"],
            "squeezes": LAST_KNOWN_STATUS["squeezes"],
            "actionable_breakouts": LAST_KNOWN_STATUS["actionable_breakouts"],
            "total_eligible_universe": LAST_KNOWN_STATUS["total_eligible"]
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "balance": 4957.23,
            "available": 471.44,
            "total_unrealized_pnl": 0.0,
            "open_positions": [],
            "recent_trades": [],
            "screened_tokens": {}
        }


class RealTimeRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS so browser can access from any origin
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/trt_bot_app.html"
            return super().do_GET()

        elif self.path.startswith("/api/live"):
            data = fetch_live_binance_state()
            payload = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        return super().do_GET()


def run_server():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("0.0.0.0", PORT), RealTimeRequestHandler)
    print(f"🚀 [REAL-TIME WEB SERVER] Running at http://localhost:{PORT}")
    print(f"   API Endpoint: http://localhost:{PORT}/api/live")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
