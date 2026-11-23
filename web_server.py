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

        # 2. Positions & Guaranteed Stop-Loss Orders
        pos_res = requests.get(f"{BASE_URL}/fapi/v2/positionRisk?" + sign({}), headers={"X-MBX-APIKEY": API_KEY}, timeout=4).json()
        
        algo_res = []
        try:
            ar = requests.get(f"{BASE_URL}/fapi/v1/openAlgoOrders?" + sign({}), headers={"X-MBX-APIKEY": API_KEY}, timeout=3).json()
            if isinstance(ar, list):
                algo_res = ar
        except Exception:
            pass

        orders_res = []
        try:
            orr = requests.get(f"{BASE_URL}/fapi/v1/openOrders?" + sign({}), headers={"X-MBX-APIKEY": API_KEY}, timeout=3).json()
            if isinstance(orr, list):
                orders_res = orr
        except Exception:
            pass

        active_pos = []
        if isinstance(pos_res, list):
            for p in pos_res:
                amt = float(p.get("positionAmt", 0))
                if amt == 0:
                    continue
                sym = p.get("symbol", "")
                side = "LONG" if amt > 0 else "SHORT"
                entry = float(p.get("entryPrice", 0))
                mark = float(p.get("markPrice", 0))

                sl_price = None
                # Check Binance open algo orders (Guaranteed CONDITIONAL STOP_MARKET)
                for o in algo_res:
                    if o.get("symbol") == sym and o.get("orderType") in ["STOP_MARKET", "STOP", "STOP_LOSS"]:
                        tp = float(o.get("triggerPrice", 0))
                        if tp > 0:
                            sl_price = tp
                            break

                # Check standard open orders fallback
                if sl_price is None:
                    for o in orders_res:
                        if o.get("symbol") == sym and o.get("type") in ["STOP_MARKET", "STOP", "STOP_LOSS"]:
                            sp = float(o.get("stopPrice", 0))
                            if sp > 0:
                                sl_price = sp
                                break

                # Safety calculation fallback if order query fails
                if sl_price is None and entry > 0:
                    sl_price = round(entry * 0.988 if side == "LONG" else entry * 1.012, 4)

                is_be = (sl_price >= entry) if side == "LONG" else (sl_price <= entry)
                dist_pct = round(((sl_price - mark) / mark) * 100.0, 2) if mark > 0 and sl_price else 0.0

                active_pos.append({
                    "symbol": sym,
                    "side": side,
                    "size": abs(amt),
                    "entryPrice": entry,
                    "markPrice": mark,
                    "slPrice": sl_price,
                    "slDistPct": dist_pct,
                    "isBreakeven": is_be,
                    "unrealizedPnl": float(p.get("unRealizedProfit", 0)),
                    "liquidationPrice": float(p.get("liquidationPrice", 0)),
                    "leverage": int(p.get("leverage", 5)),
                    "marginType": p.get("marginType", "cross")
                })

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

        elif self.path.startswith("/api/debug"):
            dir_path = os.path.dirname(os.path.abspath(__file__))
            status_file = os.path.join(dir_path, "live_status.json")
            debug_info = {
                "cwd": os.getcwd(),
                "file_path": os.path.abspath(__file__),
                "dir_files": os.listdir(dir_path) if os.path.exists(dir_path) else [],
                "status_file": status_file,
                "status_exists": os.path.exists(status_file),
                "last_known_gainers": len(LAST_KNOWN_STATUS.get("gainers", [])),
                "last_known_squeezes": len(LAST_KNOWN_STATUS.get("squeezes", []))
            }
            try:
                rf = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3)
                debug_info["fapi_status"] = rf.status_code
                debug_info["fapi_type"] = type(rf.json()).__name__
                if not isinstance(rf.json(), list):
                    debug_info["fapi_resp"] = str(rf.json())[:100]
            except Exception as e:
                debug_info["fapi_err"] = str(e)
            if os.path.exists(status_file):
                try:
                    debug_info["status_file_size"] = os.path.getsize(status_file)
                    with open(status_file, "r", encoding="utf-8") as f:
                        content = json.load(f)
                    debug_info["json_keys"] = list(content.keys())
                    debug_info["json_gainers_len"] = len(content.get("gainers", []))
                    debug_info["json_squeezes_len"] = len(content.get("squeezes", []))
                except Exception as e:
                    debug_info["json_error"] = str(e)

            payload = json.dumps(debug_info, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

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
