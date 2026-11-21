"""
T.R Technology — Production Live MTF Trading Bot (Phase 4.5)
Pairs: SOLUSDT, INJUSDT | Binance USDT-M Futures
Full 8-Timeframe Confluence Engine: 1M, 1W, 1D, 4H, 1H, 30M, 15M, 5M
Entry Execution: 5m / 15m closed candles with exchange-level SL & TP.
"""
import os
import sys
import time
import math
import hmac
import hashlib
import functools
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

print = functools.partial(print, flush=True)

import config as cfg
from indicators import compute_all_indicators
from mtf_analyzer import MTFConfluenceAnalyzer, MTFConfluenceReport


# ═══════════════════════════════════════════════════════════════════════════════
# BINANCE FUTURES API CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "TRT-MTF-Bot-v2.0"
        })

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def get_account_balance(self) -> float:
        params = self._sign({})
        r = self.session.get(f"{self.base_url}/fapi/v2/balance", params=params)
        r.raise_for_status()
        for item in r.json():
            if item["asset"] == "USDT":
                return float(item["availableBalance"])
        return 0.0

    def get_klines(self, symbol: str, interval: str, limit: int = 120) -> pd.DataFrame:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = self.session.get(f"{self.base_url}/fapi/v1/klines", params=params)
        r.raise_for_status()
        raw = r.json()

        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        # Drop unclosed candle
        return df.iloc[:-1].reset_index(drop=True)

    def get_symbol_precision(self, symbol: str):
        r = self.session.get(f"{self.base_url}/fapi/v1/exchangeInfo")
        r.raise_for_status()
        for s in r.json()["symbols"]:
            if s["symbol"] == symbol:
                qty_step = float([f["stepSize"] for f in s["filters"] if f["filterType"] == "LOT_SIZE"][0])
                price_tick = float([f["tickSize"] for f in s["filters"] if f["filterType"] == "PRICE_FILTER"][0])
                qty_prec = int(round(-math.log10(qty_step))) if qty_step < 1 else 0
                price_prec = int(round(-math.log10(price_tick))) if price_tick < 1 else 0
                return qty_prec, price_prec
        return 2, 2

    def set_leverage(self, symbol: str, leverage: int = 5):
        params = self._sign({"symbol": symbol, "leverage": leverage})
        r = self.session.post(f"{self.base_url}/fapi/v1/leverage", params=params)
        return r.json()

    def get_open_positions(self, symbol: str = None) -> list:
        params = self._sign({})
        r = self.session.get(f"{self.base_url}/fapi/v2/positionRisk", params=params)
        r.raise_for_status()
        positions = []
        for p in r.json():
            amt = float(p["positionAmt"])
            if amt != 0:
                if symbol is None or p["symbol"] == symbol:
                    positions.append(p)
        return positions

    def place_market_order(self, symbol: str, side: str, qty: float):
        params = self._sign({
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty
        })
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()

    def place_stop_loss_market(self, symbol: str, side: str, qty: float, stop_price: float):
        params = self._sign({
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": stop_price,
            "closePosition": "true"
        })
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()

    def place_take_profit_limit(self, symbol: str, side: str, qty: float, tp_price: float):
        params = self._sign({
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "price": tp_price,
            "quantity": qty,
            "timeInForce": "GTC",
            "reduceOnly": "true"
        })
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MTF BOT CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

class LiveMTFBot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.analyzer = MTFConfluenceAnalyzer()
        self.symbols = cfg.PAIRS
        self.daily_start_balance = 0.0
        self.last_day = None
        self.trigger_tf = "15m"  # Primary trigger: 15m closed candle (also reads 5m)

    def sync_account(self):
        balance = self.client.get_account_balance()
        today = datetime.now(timezone.utc).date()
        if self.last_day != today:
            self.daily_start_balance = balance
            self.last_day = today
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daily balance anchored: ${self.daily_start_balance:.2f}")
        return balance

    def _save_live_status(self, symbol: str, rep: MTFConfluenceReport, balance: float, open_pos_count: int):
        import json
        status_file = os.path.join(os.path.dirname(__file__), "live_status.json")
        data = {}
        if os.path.exists(status_file):
            try:
                with open(status_file, "r") as f:
                    data = json.load(f)
            except:
                pass
        
        data["status"] = "RUNNING"
        data["last_update"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        data["balance"] = round(balance, 2)
        data["open_positions"] = open_pos_count
        if "symbols" not in data:
            data["symbols"] = {}
        data["symbols"][symbol] = {
            "confluence": rep.total_confluence,
            "bias": rep.overall_bias.value,
            "allowed": rep.allowed_direction or "WAITING",
            "macro": rep.macro_score,
            "mid": rep.mid_score,
            "micro": rep.micro_score,
            "reasons": rep.reasons
        }
        try:
            with open(status_file, "w") as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def execute_mtf_trade(self, symbol: str, trig: dict, rep: MTFConfluenceReport, balance: float):
        direction = trig["direction"]
        entry = trig["entry_price"]
        sl = trig["sl_price"]
        tp1 = trig["tp1_price"]

        print(f"\n🎯 [MTF TRADE TRIGGERED] {symbol} {direction}!")
        print(f"   Confluence Score: {rep.total_confluence}% | Bias: {rep.overall_bias.value}")
        print(f"   Entry: ~${entry:.2f} | SL: ${sl:.2f} | TP1: ${tp1:.2f} (Trigger: {trig['trigger_tf']})")

        risk_usd = 0.01 * balance  # 1% risk
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return

        raw_qty = risk_usd / sl_dist
        qty_prec, price_prec = self.client.get_symbol_precision(symbol)
        qty = round(raw_qty, qty_prec)

        if qty <= 0:
            print(f"   ⚠️ Calculated qty {raw_qty} rounded to 0. Skipping.")
            return

        order_side = "BUY" if direction == "LONG" else "SELL"
        sl_side = "SELL" if direction == "LONG" else "BUY"
        sl_price = round(sl, price_prec)
        tp1_price = round(tp1, price_prec)

        try:
            self.client.set_leverage(symbol, 5)
            print(f"   Executing MARKET {order_side} of {qty} {symbol}...")
            entry_res = self.client.place_market_order(symbol, order_side, qty)
            print(f"   ✓ Filled! Order ID: {entry_res.get('orderId')}")

            print(f"   Placing Exchange Stop-Loss at ${sl_price:.2f}...")
            sl_res = self.client.place_stop_loss_market(symbol, sl_side, qty, sl_price)
            print(f"   ✓ Stop-Loss Placed! ID: {sl_res.get('orderId')}")

            tp_qty = round(qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   Placing TP1 (50%) at ${tp1_price:.2f}...")
                tp_res = self.client.place_take_profit_limit(symbol, sl_side, tp_qty, tp1_price)
                print(f"   ✓ TP1 Order Placed! ID: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [ERROR] Trade placement failed: {e}")
            try:
                self.client.place_market_order(symbol, sl_side, qty)
            except:
                pass

    def run_mtf_scan(self):
        balance = self.sync_account()
        open_positions = self.client.get_open_positions()
        active_coins = {p["symbol"] for p in open_positions}

        print(f"\n{'='*65}")
        print(f"🔍 [MTF SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open Positions: {len(open_positions)}/2")
        print(f"{'='*65}")

        if len(open_positions) >= cfg.MAX_TOTAL_POSITIONS:
            print("   Max positions (2) active. Skipping new triggers.")
            return

        for sym in self.symbols:
            if sym in active_coins:
                print(f"   [{sym}] Position already open. Skipping.")
                continue

            try:
                # 1. Fetch 8 timeframes
                tf_data = {}
                for tf in self.analyzer.TIMEFRAMES:
                    raw_df = self.client.get_klines(sym, tf, limit=100)
                    tf_data[tf] = compute_all_indicators(raw_df)

                # 2. Evaluate Full Multi-Timeframe Confluence
                rep = self.analyzer.evaluate_confluence(sym, tf_data)
                
                print(f"📊 [{sym}] Confluence: {rep.total_confluence:+.1f}% | Bias: {rep.overall_bias.value} | Allowed: {rep.allowed_direction}")
                print(f"   Macro (1M,1W,1D): {rep.macro_score:+.2f} | Mid (4H,1H,30M): {rep.mid_score:+.2f} | Micro (15M,5M): {rep.micro_score:+.2f}")

                # Save live status to JSON for Dashboard App
                self._save_live_status(sym, rep, balance, len(open_positions))

                # 3. If Higher TFs have clear Confluence, check 1m, 5m & 15m triggers!
                if rep.allowed_direction:
                    print(f"   ⚡ High Confluence confirmed for {rep.allowed_direction}! Checking 1m, 5m & 15m triggers...")
                    
                    # High-speed trigger hierarchy: 1m -> 5m -> 15m
                    trig = None
                    for tf_name in ["1m", "5m", "15m"]:
                        if tf_name in tf_data:
                            trig = self.analyzer.check_micro_entry_trigger(
                                tf_data[tf_name], rep.allowed_direction, trigger_name=tf_name
                            )
                            if trig:
                                break

                    if trig:
                        self.execute_mtf_trade(sym, trig, rep, balance)
                        break
                    else:
                        print(f"   ⏳ Confluence ready, waiting for 1m/5m/15m pullback bounce candle close.")
                else:
                    print(f"   🚫 {rep.reasons[0]}")

            except Exception as e:
                print(f"   [{sym}] Scan error: {e}")

    def start_loop(self):
        print("="*65)
        print("  T.R TECHNOLOGY HIGH-SPEED MTF BOT RUNNING (1-MIN SCAN)")
        print("  Confluence: 1M -> 1W -> 1D -> 4H -> 1H -> 15M -> 5M -> 1M")
        print(f"  Triggers: 1m / 5m / 15m Closed Candles | Scan Interval: 30s")
        print("="*65)

        # Run immediately once
        self.run_mtf_scan()

        last_evaluated_minute = -1
        while True:
            try:
                now = datetime.now(timezone.utc)
                # Check EVERY MINUTE (at second :03 right after candle closes)
                if now.minute != last_evaluated_minute:
                    print(f"\n⏰ 1-Minute Candle Close ({now.strftime('%H:%M:%S UTC')})! Scanning live...")
                    time.sleep(2)  # wait 2s for candle to finalize
                    self.run_mtf_scan()
                    last_evaluated_minute = now.minute

                time.sleep(5)  # poll loop sleeps only 5 seconds
            except KeyboardInterrupt:
                print("\nMTF Bot stopped by user.")
                break
            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(5)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="T.R Technology MTF Bot")
    parser.add_argument("--testnet", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--api-key", type=str, default="")
    parser.add_argument("--api-secret", type=str, default="")
    args = parser.parse_args()

    api_key = args.api_key or "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
    api_secret = args.api_secret or "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
    is_testnet = not args.live

    client = BinanceFuturesClient(api_key, api_secret, testnet=is_testnet)
    bot = LiveMTFBot(client)
    bot.start_loop()


if __name__ == "__main__":
    main()
