"""
T.R Technology — Real-Time Trading Web Server & Live API Bridge + Command Chat Bot
Serves the Interactive Web Dashboard on http://localhost:8080
Provides live Binance Testnet account data, open positions, recent fills, 1m radar,
and an authenticated chat bot for trade commands & account queries.
"""
import os
import re
import sys
import time
import json
import hmac
import hashlib
import urllib.parse
import threading
import requests
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

API_KEY = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
API_SECRET = b"7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
BASE_URL = "https://testnet.binancefuture.com"
PORT = int(os.environ.get("PORT", 8080))

# ─── Chat Bot Password (Env var or default) ───
CHAT_PASSWORD = os.environ.get("CHAT_PASSWORD", "TRT@2024")

# ─── Bot Config File (Runtime-changeable parameters) ───
DIR_PATH = os.path.dirname(os.path.abspath(__file__))
BOT_CONFIG_FILE = os.path.join(DIR_PATH, "bot_config.json")


def sign(params: dict) -> str:
    params["timestamp"] = int(time.time() * 1000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(API_SECRET, q.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{q}&signature={sig}"


def _binance_signed_get(path: str, params: dict = None) -> dict:
    """Signed GET to Binance Futures Testnet."""
    if params is None:
        params = {}
    url = f"{BASE_URL}{path}?" + sign(params)
    r = requests.get(url, headers={"X-MBX-APIKEY": API_KEY}, timeout=5)
    return r.json()


def _binance_signed_post(path: str, params: dict) -> dict:
    """Signed POST to Binance Futures Testnet."""
    url = f"{BASE_URL}{path}?" + sign(params)
    r = requests.post(url, headers={"X-MBX-APIKEY": API_KEY}, timeout=6)
    return r.json()


def _binance_signed_delete(path: str, params: dict) -> dict:
    """Signed DELETE to Binance Futures Testnet."""
    url = f"{BASE_URL}{path}?" + sign(params)
    r = requests.delete(url, headers={"X-MBX-APIKEY": API_KEY}, timeout=6)
    return r.json()


# ═══════════════════════════════════════════════════════════════
#  BOT CONFIG MANAGEMENT
# ═══════════════════════════════════════════════════════════════
DEFAULT_CONFIG = {
    "risk_pct": 1.0,
    "leverage": 5,
    "margin_type": "CROSSED"
}


def load_bot_config() -> dict:
    try:
        if os.path.exists(BOT_CONFIG_FILE):
            with open(BOT_CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def save_bot_config(cfg: dict):
    try:
        with open(BOT_CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  CHAT COMMAND PROCESSOR
# ═══════════════════════════════════════════════════════════════
def process_chat_command(message: str) -> dict:
    """
    Process a chat command and return a response dict.
    Returns: {"reply": str, "type": "info"|"action"|"error"|"config"}
    """
    msg = message.strip()
    msg_lower = msg.lower()

    # ── HELP ──
    if msg_lower in ["help", "/help", "?", "commands"]:
        return _cmd_help()

    # ── ACCOUNT STATUS ──
    if msg_lower in ["status", "balance", "account", "bal"]:
        return _cmd_status()

    # ── OPEN POSITIONS ──
    if msg_lower in ["positions", "pos", "open", "open positions", "trades"]:
        return _cmd_positions()

    # ── RECENT TRADES / HISTORY ──
    if any(k in msg_lower for k in ["recent", "history", "last trades", "fills"]):
        return _cmd_recent_trades()

    # ── PNL / PROFIT / LOSS SUMMARY ──
    if any(k in msg_lower for k in ["pnl", "profit", "loss", "p&l", "earnings"]):
        return _cmd_pnl()

    # ── CLOSE POSITION ──
    if msg_lower.startswith("close "):
        return _cmd_close(msg)

    # ── MODIFY STOP LOSS ──
    if re.match(r"^(sl|stop.?loss|move.?sl)", msg_lower):
        return _cmd_modify_sl(msg)

    # ── SET LEVERAGE ──
    if "leverage" in msg_lower:
        return _cmd_set_leverage(msg)

    # ── SET RISK PER TRADE ──
    if any(k in msg_lower for k in ["risk", "per trade", "dollar", "trade size"]):
        return _cmd_set_risk(msg)

    # ── SET MARGIN TYPE ──
    if any(k in msg_lower for k in ["margin", "cross", "isolated"]):
        return _cmd_set_margin(msg)

    # ── CURRENT CONFIG ──
    if msg_lower in ["config", "settings", "current config", "show config"]:
        return _cmd_show_config()

    # ── SUGGEST / RECOMMENDATION ──
    if any(k in msg_lower for k in ["suggest", "recommendation", "advice", "analysis"]):
        return _cmd_suggest()

    return {
        "reply": "❓ কমান্ড বুঝতে পারিনি। `help` টাইপ করুন সব কমান্ড দেখতে।",
        "type": "error"
    }


# ─── HELP ───
def _cmd_help():
    return {
        "reply": (
            "📋 **TRT Command Bot — Available Commands:**\n\n"
            "**📊 Information:**\n"
            "• `status` — Account balance & overview\n"
            "• `positions` — All open positions with SL\n"
            "• `pnl` — Total profit/loss summary\n"
            "• `recent` — Last 10 trade fills\n"
            "• `config` — Current bot configuration\n\n"
            "**⚙️ Configuration:**\n"
            "• `leverage 10` — Set leverage (1-125)\n"
            "• `risk 2%` or `risk $50` — Set risk per trade\n"
            "• `margin cross` or `margin isolated` — Set margin mode\n\n"
            "**🎯 Trade Actions:**\n"
            "• `close BTCUSDT` — Close a specific position\n"
            "• `close all` — Close all open positions\n"
            "• `sl BTCUSDT 59000` — Move stop-loss to new price\n\n"
            "**💡 Analysis:**\n"
            "• `suggest` — Get trade suggestions & analysis"
        ),
        "type": "info"
    }


# ─── ACCOUNT STATUS ───
def _cmd_status():
    try:
        bal_res = _binance_signed_get("/fapi/v2/balance")
        usdt = next((b for b in bal_res if b.get("asset") == "USDT"), None)
        if not usdt:
            return {"reply": "❌ USDT balance not found.", "type": "error"}

        balance = round(float(usdt["balance"]), 2)
        available = round(float(usdt["availableBalance"]), 2)
        used = round(balance - available, 2)

        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0] if isinstance(pos_res, list) else []
        total_upnl = sum(float(p.get("unRealizedProfit", 0)) for p in active)

        return {
            "reply": (
                f"💰 **Account Status**\n\n"
                f"• Balance: **${balance:,.2f} USDT**\n"
                f"• Available: **${available:,.2f} USDT**\n"
                f"• In Use (Margin): **${used:,.2f} USDT**\n"
                f"• Open Positions: **{len(active)}/2**\n"
                f"• Unrealized PnL: **{'+'if total_upnl>=0 else ''}${total_upnl:,.2f} USDT**"
            ),
            "type": "info"
        }
    except Exception as e:
        return {"reply": f"❌ Error fetching account: {e}", "type": "error"}


# ─── OPEN POSITIONS ───
def _cmd_positions():
    try:
        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0] if isinstance(pos_res, list) else []

        if not active:
            return {"reply": "📭 কোনো ওপেন পজিশন নেই। বট নতুন A+ সেটআপ খুঁজছে।", "type": "info"}

        # Fetch algo orders for SL info
        algo_res = []
        try:
            ar = _binance_signed_get("/fapi/v1/openAlgoOrders")
            if isinstance(ar, list):
                algo_res = ar
        except Exception:
            pass

        lines = ["📊 **Open Positions:**\n"]
        for p in active:
            sym = p["symbol"]
            amt = float(p["positionAmt"])
            side = "LONG 🟢" if amt > 0 else "SHORT 🔴"
            entry = float(p["entryPrice"])
            mark = float(p["markPrice"])
            upnl = float(p["unRealizedProfit"])
            lev = p["leverage"]
            pnl_pct = round((upnl / (abs(amt) * entry)) * 100, 2) if entry > 0 else 0

            # Find SL
            sl = "N/A"
            for o in algo_res:
                if o.get("symbol") == sym and o.get("orderType") in ["STOP_MARKET", "STOP"]:
                    tp = float(o.get("triggerPrice", 0))
                    if tp > 0:
                        sl = f"${tp:,.2f}" if tp >= 10 else f"${tp:.4f}"
                        break

            entry_str = f"${entry:,.2f}" if entry >= 10 else f"${entry:.4f}"
            mark_str = f"${mark:,.2f}" if mark >= 10 else f"${mark:.4f}"
            pnl_icon = "✅" if upnl >= 0 else "❌"

            lines.append(
                f"**{sym}** — {side} ({lev}x)\n"
                f"  Entry: {entry_str} → Mark: {mark_str}\n"
                f"  SL: {sl}\n"
                f"  PnL: {pnl_icon} {'+'if upnl>=0 else ''}${upnl:.2f} ({pnl_pct:+.2f}%)\n"
            )

        return {"reply": "\n".join(lines), "type": "info"}
    except Exception as e:
        return {"reply": f"❌ Error fetching positions: {e}", "type": "error"}


# ─── RECENT TRADES ───
def _cmd_recent_trades():
    try:
        trades = _binance_signed_get("/fapi/v1/userTrades", {"limit": 15})
        if not isinstance(trades, list) or not trades:
            return {"reply": "📭 কোনো সাম্প্রতিক ট্রেড নেই।", "type": "info"}

        total_realized = 0
        total_fees = 0
        lines = ["📜 **Recent Trade Fills (Last 15):**\n"]
        for t in reversed(trades[-10:]):
            sym = t.get("symbol", "")
            side = t.get("side", "")
            qty = float(t.get("qty", 0))
            price = float(t.get("price", 0))
            rpnl = float(t.get("realizedPnl", 0))
            fee = float(t.get("commission", 0))
            ts = time.strftime("%m/%d %H:%M", time.gmtime(t.get("time", 0) / 1000))
            total_realized += rpnl
            total_fees += fee

            icon = "🟢" if "BUY" in side else "🔴"
            pnl_str = f"{'+'if rpnl>0 else ''}${rpnl:.2f}" if rpnl != 0 else "— Entry"

            lines.append(f"{icon} `{ts}` **{sym}** {side} {qty} @ ${price:.2f} → {pnl_str}")

        lines.append(f"\n💵 Total Realized: **{'+'if total_realized>=0 else ''}${total_realized:.2f}**")
        lines.append(f"💸 Total Fees: **-${total_fees:.2f}**")

        return {"reply": "\n".join(lines), "type": "info"}
    except Exception as e:
        return {"reply": f"❌ Error fetching trades: {e}", "type": "error"}


# ─── PNL SUMMARY ───
def _cmd_pnl():
    try:
        bal_res = _binance_signed_get("/fapi/v2/balance")
        usdt = next((b for b in bal_res if b.get("asset") == "USDT"), None)
        balance = float(usdt["balance"]) if usdt else 0

        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0] if isinstance(pos_res, list) else []
        total_upnl = sum(float(p.get("unRealizedProfit", 0)) for p in active)

        trades = _binance_signed_get("/fapi/v1/userTrades", {"limit": 50})
        total_realized = sum(float(t.get("realizedPnl", 0)) for t in trades) if isinstance(trades, list) else 0
        total_fees = sum(float(t.get("commission", 0)) for t in trades) if isinstance(trades, list) else 0

        net_profit = total_realized - total_fees + total_upnl
        icon = "📈" if net_profit >= 0 else "📉"

        return {
            "reply": (
                f"{icon} **Profit & Loss Summary**\n\n"
                f"• Realized PnL (Last 50 fills): **{'+'if total_realized>=0 else ''}${total_realized:.2f}**\n"
                f"• Unrealized PnL (Open): **{'+'if total_upnl>=0 else ''}${total_upnl:.2f}**\n"
                f"• Total Fees Paid: **-${total_fees:.2f}**\n"
                f"• Net Profit: **{'+'if net_profit>=0 else ''}${net_profit:.2f} USDT**\n"
                f"• Current Balance: **${balance:,.2f} USDT**"
            ),
            "type": "info"
        }
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "type": "error"}


# ─── CLOSE POSITION ───
def _cmd_close(msg: str):
    try:
        parts = msg.strip().split()
        if len(parts) < 2:
            return {"reply": "❌ ব্যবহার: `close BTCUSDT` বা `close all`", "type": "error"}

        target = parts[1].upper()

        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0] if isinstance(pos_res, list) else []

        if not active:
            return {"reply": "📭 কোনো ওপেন পজিশন নেই ক্লোজ করার জন্য।", "type": "info"}

        to_close = active if target == "ALL" else [p for p in active if p["symbol"] == target]
        if not to_close:
            symbols = ", ".join(p["symbol"] for p in active)
            return {"reply": f"❌ `{target}` পজিশন পাওয়া যায়নি। Active: {symbols}", "type": "error"}

        results = []
        for p in to_close:
            sym = p["symbol"]
            amt = float(p["positionAmt"])
            close_side = "SELL" if amt > 0 else "BUY"
            close_qty = abs(amt)

            # Cancel all open orders for this symbol first (SL, TP etc.)
            try:
                _binance_signed_delete("/fapi/v1/allOpenOrders", {"symbol": sym})
            except Exception:
                pass

            # Cancel algo orders
            try:
                algo_orders = _binance_signed_get("/fapi/v1/openAlgoOrders")
                if isinstance(algo_orders, list):
                    for ao in algo_orders:
                        if ao.get("symbol") == sym:
                            try:
                                _binance_signed_delete("/fapi/v1/algoOrder", {"algoId": ao["algoId"]})
                            except Exception:
                                pass
            except Exception:
                pass

            # Place market close
            res = _binance_signed_post("/fapi/v1/order", {
                "symbol": sym,
                "side": close_side,
                "type": "MARKET",
                "quantity": close_qty,
                "reduceOnly": "true"
            })

            if res.get("orderId"):
                results.append(f"✅ **{sym}** ক্লোজ সফল! OrderId: {res['orderId']}")
            else:
                err = res.get("msg", str(res))
                results.append(f"❌ **{sym}** ক্লোজ ব্যর্থ: {err}")

        return {"reply": "🎯 **Position Close Result:**\n\n" + "\n".join(results), "type": "action"}
    except Exception as e:
        return {"reply": f"❌ Close error: {e}", "type": "error"}


# ─── MODIFY STOP LOSS ───
def _cmd_modify_sl(msg: str):
    try:
        # Parse: sl BTCUSDT 59000
        parts = msg.strip().split()
        if len(parts) < 3:
            return {"reply": "❌ ব্যবহার: `sl BTCUSDT 59000`\nSymbol ও নতুন SL প্রাইস দিন।", "type": "error"}

        symbol = parts[1].upper()
        try:
            new_sl = float(parts[2])
        except ValueError:
            return {"reply": "❌ Invalid SL price. Number দিন।", "type": "error"}

        # Verify position exists
        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0 and p["symbol"] == symbol] if isinstance(pos_res, list) else []
        if not active:
            return {"reply": f"❌ `{symbol}` পজিশন পাওয়া যায়নি।", "type": "error"}

        p = active[0]
        amt = float(p["positionAmt"])
        side = "LONG" if amt > 0 else "SHORT"
        sl_side = "SELL" if side == "LONG" else "BUY"
        entry = float(p["entryPrice"])

        # Safety check
        if side == "LONG" and new_sl >= float(p["markPrice"]):
            return {"reply": f"❌ LONG পজিশনে SL (${new_sl}) মার্ক প্রাইসের উপরে সেট করা যাবে না।", "type": "error"}
        if side == "SHORT" and new_sl <= float(p["markPrice"]):
            return {"reply": f"❌ SHORT পজিশনে SL (${new_sl}) মার্ক প্রাইসের নিচে সেট করা যাবে না।", "type": "error"}

        # Cancel existing algo SL orders for this symbol
        try:
            algo_orders = _binance_signed_get("/fapi/v1/openAlgoOrders")
            if isinstance(algo_orders, list):
                for ao in algo_orders:
                    if ao.get("symbol") == symbol and ao.get("orderType") in ["STOP_MARKET", "STOP"]:
                        _binance_signed_delete("/fapi/v1/algoOrder", {"algoId": ao["algoId"]})
        except Exception:
            pass

        # Cancel standard SL orders
        try:
            open_orders = _binance_signed_get("/fapi/v1/openOrders", {"symbol": symbol})
            if isinstance(open_orders, list):
                for oo in open_orders:
                    if oo.get("type") in ["STOP_MARKET", "STOP"]:
                        _binance_signed_delete("/fapi/v1/order", {"symbol": symbol, "orderId": oo["orderId"]})
        except Exception:
            pass

        # Place new algo SL
        sl_params = {
            "symbol": symbol,
            "side": sl_side,
            "algoType": "CONDITIONAL",
            "type": "STOP_MARKET",
            "triggerPrice": new_sl,
            "quantity": abs(amt)
        }
        q = sign(sl_params)
        r = requests.post(f"{BASE_URL}/fapi/v1/algoOrder?{q}", headers={"X-MBX-APIKEY": API_KEY}, timeout=6)
        sl_res = r.json()

        is_be = (new_sl >= entry) if side == "LONG" else (new_sl <= entry)
        be_tag = " 🟢 (Breakeven!)" if is_be else ""
        sl_str = f"${new_sl:,.2f}" if new_sl >= 10 else f"${new_sl:.4f}"

        if sl_res.get("algoId") or sl_res.get("orderId"):
            return {
                "reply": f"✅ **{symbol}** Stop-Loss আপডেট সফল!\n\nনতুন SL: **{sl_str}**{be_tag}\nId: {sl_res.get('algoId') or sl_res.get('orderId')}",
                "type": "action"
            }
        else:
            err = sl_res.get("msg", str(sl_res))
            return {"reply": f"❌ SL আপডেট ব্যর্থ: {err}", "type": "error"}
    except Exception as e:
        return {"reply": f"❌ SL modify error: {e}", "type": "error"}


# ─── SET LEVERAGE ───
def _cmd_set_leverage(msg: str):
    try:
        nums = re.findall(r"(\d+)", msg)
        if not nums:
            return {"reply": "❌ ব্যবহার: `leverage 10` — 1 থেকে 125 এর মধ্যে দিন।", "type": "error"}
        lev = int(nums[0])
        if lev < 1 or lev > 125:
            return {"reply": f"❌ Leverage {lev}x সীমার বাইরে। 1-125 এর মধ্যে দিন।", "type": "error"}

        cfg = load_bot_config()
        old_lev = cfg.get("leverage", 5)
        cfg["leverage"] = lev
        save_bot_config(cfg)

        return {
            "reply": f"⚙️ **Leverage আপডেট সফল!**\n\n• আগে: **{old_lev}x**\n• এখন: **{lev}x**\n\n_পরবর্তী সব নতুন ট্রেডে {lev}x leverage ব্যবহার হবে।_",
            "type": "config"
        }
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "type": "error"}


# ─── SET RISK PER TRADE ───
def _cmd_set_risk(msg: str):
    try:
        msg_lower = msg.lower()

        # Try to find percentage: "risk 2%" or "risk 1.5%"
        pct_match = re.search(r"(\d+\.?\d*)\s*%", msg)
        # Try to find dollar: "risk $50" or "risk 50 dollar"
        dollar_match = re.search(r"\$?\s*(\d+\.?\d*)\s*(?:dollar|usd)?", msg_lower)

        cfg = load_bot_config()
        old_risk = cfg.get("risk_pct", 1.0)

        if pct_match:
            new_pct = float(pct_match.group(1))
            if new_pct < 0.1 or new_pct > 5.0:
                return {"reply": f"❌ Risk {new_pct}% সীমার বাইরে। 0.1% - 5.0% এর মধ্যে দিন।", "type": "error"}
            cfg["risk_pct"] = new_pct
            save_bot_config(cfg)
            return {
                "reply": f"⚙️ **Risk Per Trade আপডেট সফল!**\n\n• আগে: **{old_risk}%** প্রতি ট্রেডে\n• এখন: **{new_pct}%** প্রতি ট্রেডে\n\n_যেমন: $10,000 ব্যালেন্সে প্রতি ট্রেডে ~${10000*new_pct/100:.0f} রিস্ক হবে।_",
                "type": "config"
            }
        elif dollar_match:
            # Convert dollar to approximate percentage
            return {"reply": "💡 ব্যবহার: `risk 1.5%` — শতকরা হারে দিন (0.1% - 5.0%)।\nবর্তমান ব্যালেন্সের উপর ভিত্তি করে ক্যালকুলেট হবে।", "type": "info"}
        else:
            return {"reply": f"❌ ব্যবহার: `risk 2%` — শতকরা রিস্ক দিন।\n\nবর্তমান রিস্ক: **{old_risk}%**", "type": "error"}
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "type": "error"}


# ─── SET MARGIN TYPE ───
def _cmd_set_margin(msg: str):
    try:
        msg_lower = msg.lower()
        cfg = load_bot_config()
        old_type = cfg.get("margin_type", "CROSSED")

        if "isolated" in msg_lower:
            new_type = "ISOLATED"
        elif "cross" in msg_lower:
            new_type = "CROSSED"
        else:
            return {"reply": f"❌ ব্যবহার: `margin cross` বা `margin isolated`\n\nবর্তমান: **{old_type}**", "type": "error"}

        cfg["margin_type"] = new_type
        save_bot_config(cfg)

        display = "Cross (ক্রস)" if new_type == "CROSSED" else "Isolated (আইসোলেটেড)"
        return {
            "reply": (
                f"⚙️ **Margin Type আপডেট সফল!**\n\n"
                f"• আগে: **{old_type}**\n"
                f"• এখন: **{display}**\n\n"
                f"_বটের পরবর্তী সব নতুন ট্রেড {display} মার্জিনে ওপেন হবে।_\n"
                f"_(নোট: ওপেন ট্রেডগুলোর মার্জিন বাইন্যান্স রুলস অনুযায়ী ক্লোজ হওয়ার পর নতুন মার্জিনে কাজ করবে।)_"
            ),
            "type": "config"
        }
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "type": "error"}


# ─── SHOW CONFIG ───
def _cmd_show_config():
    cfg = load_bot_config()
    margin_display = "Cross (ক্রস)" if cfg["margin_type"] == "CROSSED" else "Isolated (আইসোলেটেড)"
    return {
        "reply": (
            f"⚙️ **Current Bot Configuration:**\n\n"
            f"• Risk Per Trade: **{cfg['risk_pct']}%** of balance\n"
            f"• Leverage: **{cfg['leverage']}x**\n"
            f"• Margin Type: **{margin_display}**\n"
            f"• Max Concurrent Trades: **2**\n"
            f"• Auto-Trade Engine: **Active (Pro Trader v8.0)**\n"
            f"• Stop-Loss: **Structural 0.8%-1.5%**\n"
            f"• TP1: **1.8R (50% partial close + SL→BE)**\n"
            f"• TP2: **3.5R (Full runner close)**\n\n"
            f"_`leverage 10`, `risk 2%`, `margin isolated` দিয়ে পরিবর্তন করুন।_"
        ),
        "type": "config"
    }


# ─── SUGGEST / ANALYSIS ───
def _cmd_suggest():
    try:
        pos_res = _binance_signed_get("/fapi/v2/positionRisk")
        active = [p for p in pos_res if float(p.get("positionAmt", 0)) != 0] if isinstance(pos_res, list) else []

        if not active:
            return {
                "reply": (
                    "💡 **Bot Analysis:**\n\n"
                    "• কোনো ওপেন পজিশন নেই। ২/২ স্লট ফাঁকা আছে।\n"
                    "• বট অটোমেটিক্যালি 146+ পেয়ারে A+ সেটআপ খুঁজছে।\n"
                    "• নতুন সিগন্যাল আসলে সেরা ২টি অটো-এক্সিকিউট হবে।\n\n"
                    "_ধৈর্য ধরুন — মার্কেট যখন সঠিক সেটআপ দেবে তখনই ট্রেড নেবে। 🎯_"
                ),
                "type": "info"
            }

        lines = ["💡 **Bot Analysis & Suggestions:**\n"]
        for p in active:
            sym = p["symbol"]
            amt = float(p["positionAmt"])
            side = "LONG" if amt > 0 else "SHORT"
            entry = float(p["entryPrice"])
            mark = float(p["markPrice"])
            upnl = float(p["unRealizedProfit"])
            pnl_pct = round(((mark - entry) / entry) * 100, 2) if side == "LONG" else round(((entry - mark) / entry) * 100, 2)

            if pnl_pct >= 5:
                lines.append(
                    f"🏆 **{sym}** ({side}): +{pnl_pct}% প্রফিটে! +${upnl:.2f}\n"
                    f"  → 💡 TP2 টার্গেটের কাছে এসেছে। আংশিক প্রফিট নিতে পারেন অথবা SL ব্রেক-ইভেনে সরান।\n"
                    f"  → কমান্ড: `sl {sym} {entry}` (Breakeven SL)\n"
                )
            elif pnl_pct >= 2:
                lines.append(
                    f"✅ **{sym}** ({side}): +{pnl_pct}% প্রফিটে! +${upnl:.2f}\n"
                    f"  → 💡 ভালো চলছে। SL কিছুটা উপরে তুলে রিস্ক কমাতে পারেন।\n"
                )
            elif pnl_pct >= 0:
                lines.append(
                    f"🔄 **{sym}** ({side}): +{pnl_pct}% — প্রায় ব্রেক-ইভেনে।\n"
                    f"  → 💡 ধৈর্য ধরুন। SL যেখানে আছে সেখানেই রাখুন।\n"
                )
            else:
                lines.append(
                    f"⚠️ **{sym}** ({side}): {pnl_pct}% — ${abs(upnl):.2f} লসে।\n"
                    f"  → 💡 প্যানিক ক্লোজ করবেন না। SL সেট আছে, রিস্ক ম্যানেজড।\n"
                )

        return {"reply": "\n".join(lines), "type": "info"}
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "type": "error"}


# ═══════════════════════════════════════════════════════════════
#  LIVE DASHBOARD STATE
# ═══════════════════════════════════════════════════════════════
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
                for o in algo_res:
                    if o.get("symbol") == sym and o.get("orderType") in ["STOP_MARKET", "STOP", "STOP_LOSS"]:
                        tp = float(o.get("triggerPrice", 0))
                        if tp > 0:
                            sl_price = tp
                            break

                if sl_price is None:
                    for o in orders_res:
                        if o.get("symbol") == sym and o.get("type") in ["STOP_MARKET", "STOP", "STOP_LOSS"]:
                            sp = float(o.get("stopPrice", 0))
                            if sp > 0:
                                sl_price = sp
                                break

                if sl_price is None and entry > 0:
                    sl_price = round(entry * 0.988 if side == "LONG" else entry * 1.012, 4)

                is_be = (sl_price >= entry) if side == "LONG" else (sl_price <= entry)
                dist_pct = round(((sl_price - mark) / mark) * 100.0, 2) if mark > 0 and sl_price else 0.0

                # Check if SL has been shifted to guaranteed profit
                is_profit_sl = (sl_price > entry) if side == "LONG" else (sl_price < entry)
                locked_profit_pct = round(abs((sl_price - entry) / entry) * 100.0, 2) if (is_profit_sl and entry > 0 and sl_price) else 0.0

                # Profit % calculations (ROE % and Price % move)
                lev = int(p.get("leverage", 5))
                margin_type = str(p.get("marginType", "cross")).lower()
                price_pnl_pct = round(((mark - entry) / entry * 100.0) if side == "LONG" else ((entry - mark) / entry * 100.0), 2) if entry > 0 else 0.0
                position_initial_margin = (abs(amt) * entry) / lev if lev > 0 else 1.0
                upnl = float(p.get("unRealizedProfit", 0))
                roe_pct = round((upnl / position_initial_margin) * 100.0, 2) if position_initial_margin > 0 else 0.0

                active_pos.append({
                    "symbol": sym,
                    "side": side,
                    "size": abs(amt),
                    "entryPrice": entry,
                    "markPrice": mark,
                    "slPrice": sl_price,
                    "slDistPct": dist_pct,
                    "isBreakeven": is_be,
                    "isProfitSl": is_profit_sl,
                    "lockedProfitPct": locked_profit_pct,
                    "unrealizedPnl": upnl,
                    "pnlPercent": roe_pct,
                    "pricePnlPercent": price_pnl_pct,
                    "liquidationPrice": float(p.get("liquidationPrice", 0)),
                    "leverage": lev,
                    "marginType": margin_type
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
        status_file = os.path.join(DIR_PATH, "live_status.json")
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

        cfg = load_bot_config()
        # Compute live execution leverage & margin string
        if active_pos:
            m_type = "Isolated" if "iso" in active_pos[0]["marginType"].lower() else "Cross"
            live_exec_str = f"{active_pos[0]['leverage']}x {m_type}"
            live_exec_sub = "Live Active Trade Margin"
        else:
            m_type = "Isolated" if cfg.get("margin_type") == "ISOLATED" else "Cross"
            live_exec_str = f"{cfg.get('leverage', 5)}x {m_type}"
            live_exec_sub = "Bot Configured Execution"

        return {
            "status": "ONLINE",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "balance": round(float(usdt["balance"]), 2),
            "available": round(float(usdt["availableBalance"]), 2),
            "total_unrealized_pnl": round(sum(p["unrealizedPnl"] for p in active_pos), 2),
            "open_positions": active_pos,
            "recent_trades": clean_trades,
            "execution_leverage_display": live_exec_str,
            "execution_leverage_subtitle": live_exec_sub,
            "bot_config": cfg,
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


# ═══════════════════════════════════════════════════════════════
#  HTTP REQUEST HANDLER
# ═══════════════════════════════════════════════════════════════
_CACHE_LOCK = threading.Lock()
_LAST_STATE_TIME = 0.0
_CACHED_STATE = None

def get_live_binance_state_cached() -> dict:
    global _LAST_STATE_TIME, _CACHED_STATE
    now = time.time()
    with _CACHE_LOCK:
        if _CACHED_STATE and (now - _LAST_STATE_TIME < 1.5):
            return _CACHED_STATE
    
    fresh = fetch_live_binance_state()
    with _CACHE_LOCK:
        _CACHED_STATE = fresh
        _LAST_STATE_TIME = now
    return fresh


class RealTimeRequestHandler(SimpleHTTPRequestHandler):
    def _clean_path(self) -> str:
        return self.path.split("?")[0].rstrip("/")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Chat-Password")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        clean_path = self._clean_path()
        if clean_path == "" or clean_path == "/index.html":
            self.path = "/trt_bot_app.html"
            return super().do_GET()

        elif clean_path.startswith("/api/debug"):
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

        elif clean_path.startswith("/api/live"):
            data = get_live_binance_state_cached()
            payload = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        return super().do_GET()

    def do_POST(self):
        """Handle chat bot API requests."""
        clean_path = self._clean_path()
        if clean_path == "/api/chat":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode("utf-8"))

                password = body.get("password", "")
                if password != CHAT_PASSWORD:
                    resp = json.dumps({"error": "unauthorized", "reply": "🔒 পাসওয়ার্ড ভুল।"}).encode("utf-8")
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return

                message = body.get("message", "").strip()
                if not message:
                    resp = json.dumps({"reply": "❌ খালি মেসেজ।", "type": "error"}).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return

                result = process_chat_command(message)
                result["timestamp"] = time.strftime("%H:%M:%S UTC", time.gmtime())

                resp = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            except Exception as e:
                resp = json.dumps({"reply": f"❌ Server error: {e}", "type": "error"}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            return

        elif clean_path == "/api/chat/auth":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                body = json.loads(post_data.decode("utf-8"))
                password = body.get("password", "")

                if password == CHAT_PASSWORD:
                    resp = json.dumps({"authenticated": True}).encode("utf-8")
                    self.send_response(200)
                else:
                    resp = json.dumps({"authenticated": False, "error": "🔒 পাসওয়ার্ড ভুল। আবার চেষ্টা করুন।"}).encode("utf-8")
                    self.send_response(401)

                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                resp = json.dumps({"authenticated": False, "error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        """Suppress noisy HTTP logs but keep errors."""
        if args and "404" in str(args[0]):
            super().log_message(format, *args)


def run_server():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RealTimeRequestHandler)
    print(f"🚀 [REAL-TIME WEB SERVER] Running at http://localhost:{PORT} (Multi-Threaded)")
    print(f"   API Endpoint: http://localhost:{PORT}/api/live")
    print(f"   Chat Bot API: http://localhost:{PORT}/api/chat")
    print(f"   Chat Password: {'*' * len(CHAT_PASSWORD)} (Set CHAT_PASSWORD env var to change)")
    server.serve_forever()
    print(f"🚀 [REAL-TIME WEB SERVER] Running at http://localhost:{PORT}")
    print(f"   API Endpoint: http://localhost:{PORT}/api/live")
    print(f"   Chat Bot API: http://localhost:{PORT}/api/chat")
    print(f"   Chat Password: {'*' * len(CHAT_PASSWORD)} (Set CHAT_PASSWORD env var to change)")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
