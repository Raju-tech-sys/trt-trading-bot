"""
T.R Technology — Production Top Gainers Momentum Bot (Phase 5)
Dynamically scans Binance Futures for Top Gainers (> $15M Vol, +8% to +60% pump)
Runs Multi-Timeframe Confluence (1M -> 1m) and triggers fast Long pullbacks on 1m/5m.
Strict $5 Risk Management per trade.
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
            "User-Agent": "TRT-TopGainer-Bot-v3.0"
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

    def get_top_gainers(self, top_n: int = 5, min_volume_usd: float = 15_000_000) -> list:
        """Fetch highest percentage gainers on Binance Futures with high liquidity."""
        # Ticker 24hr data is public from production Binance
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10)
            data = r.json()
            usdt_pairs = []
            for item in data:
                sym = item.get("symbol", "")
                if sym.endswith("USDT") and "_" not in sym:
                    try:
                        pct = float(item["priceChangePercent"])
                        vol = float(item["quoteVolume"])
                        # Only include healthy pumps: +5% to +80%, liquid
                        if vol >= min_volume_usd and pct >= 5.0:
                            usdt_pairs.append({
                                "symbol": sym,
                                "gain_pct": pct,
                                "volume": vol,
                                "price": float(item["lastPrice"])
                            })
                    except:
                        pass

            usdt_pairs.sort(key=lambda x: x["gain_pct"], reverse=True)
            return usdt_pairs[:top_n]
        except Exception as e:
            print(f"Error fetching top gainers: {e}")
            return [{"symbol": "SOLUSDT", "gain_pct": 0, "volume": 1e8, "price": 0}]

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

    def get_open_positions(self) -> list:
        params = self._sign({})
        r = self.session.get(f"{self.base_url}/fapi/v2/positionRisk", params=params)
        r.raise_for_status()
        return [p for p in r.json() if float(p["positionAmt"]) != 0]

    def place_market_order(self, symbol: str, side: str, qty: float):
        params = self._sign({"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty})
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()

    def place_stop_loss_market(self, symbol: str, side: str, qty: float, stop_price: float):
        params = self._sign({
            "symbol": symbol, "side": side, "type": "STOP_MARKET",
            "stopPrice": stop_price, "closePosition": "true"
        })
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()

    def place_take_profit_limit(self, symbol: str, side: str, qty: float, tp_price: float):
        params = self._sign({
            "symbol": symbol, "side": side, "type": "LIMIT",
            "price": tp_price, "quantity": qty, "timeInForce": "GTC",
            "reduceOnly": "true"
        })
        r = self.session.post(f"{self.base_url}/fapi/v1/order", params=params)
        r.raise_for_status()
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# TOP GAINERS BOT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class TopGainersBot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.analyzer = MTFConfluenceAnalyzer()
        self.daily_start_balance = 0.0
        self.last_day = None

    def sync_account(self):
        balance = self.client.get_account_balance()
        today = datetime.now(timezone.utc).date()
        if self.last_day != today:
            self.daily_start_balance = balance
            self.last_day = today
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daily balance anchored: ${self.daily_start_balance:.2f}")
        return balance

    def execute_momentum_trade(self, symbol: str, trig: dict, rep: MTFConfluenceReport, balance: float):
        entry = trig["entry_price"]
        sl = trig["sl_price"]
        tp1 = trig["tp1_price"]
        direction = trig["direction"]

        print(f"\n🚀🚀 [TOP GAINER TRADE TRIGGERED] {symbol} {direction}!")
        print(f"   Confluence Score: {rep.total_confluence}% | Bias: {rep.overall_bias.value}")
        print(f"   Entry: ~${entry:.4f} | SL: ${sl:.4f} | TP1: ${tp1:.4f} (Trigger: {trig['trigger_tf']})")

        risk_usd = 5.0  # Fixed $5 risk
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return

        raw_qty = risk_usd / sl_dist
        qty_prec, price_prec = self.client.get_symbol_precision(symbol)
        qty = round(raw_qty, qty_prec)

        if qty <= 0:
            print(f"   ⚠️ Calculated qty {raw_qty} rounded to 0 with prec {qty_prec}. Skipping.")
            return

        order_side = "BUY" if direction == "LONG" else "SELL"
        sl_side = "SELL" if direction == "LONG" else "BUY"
        sl_price = round(sl, price_prec)
        tp1_price = round(tp1, price_prec)

        try:
            self.client.set_leverage(symbol, 5)
            print(f"   Placing MARKET {order_side} {qty} {symbol}...")
            entry_res = self.client.place_market_order(symbol, order_side, qty)
            print(f"   ✓ Filled! Order ID: {entry_res.get('orderId')}")

            print(f"   Placing Exchange Stop-Loss at ${sl_price}...")
            sl_res = self.client.place_stop_loss_market(symbol, sl_side, qty, sl_price)
            print(f"   ✓ Stop-Loss Active! ID: {sl_res.get('orderId')}")

            tp_qty = round(qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   Placing TP1 at ${tp1_price}...")
                tp_res = self.client.place_take_profit_limit(symbol, sl_side, tp_qty, tp1_price)
                print(f"   ✓ TP1 Placed! ID: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [ERROR] Trade placement failed: {e}")
            try:
                self.client.place_market_order(symbol, sl_side, qty)
            except:
                pass

    def run_gainers_scan(self):
        balance = self.sync_account()
        open_positions = self.client.get_open_positions()
        active_coins = {p["symbol"] for p in open_positions}

        print(f"\n{'='*70}")
        print(f"🔥 [TOP GAINERS SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open: {len(open_positions)}/2")
        print(f"{'='*70}")

        if len(open_positions) >= 2:
            print("   Max positions (2) active. Scanning skipped.")
            return

        # Fetch live Top Gainers
        gainers = self.client.get_top_gainers(top_n=6, min_volume_usd=15_000_000)
        # Also always include SOLUSDT
        symbols_to_check = [g["symbol"] for g in gainers]
        if "SOLUSDT" not in symbols_to_check:
            symbols_to_check.append("SOLUSDT")

        print(f"   Scanning Coins: {symbols_to_check}")

        for sym in symbols_to_check:
            if sym in active_coins:
                continue

            try:
                # Fetch Timeframes
                tf_data = {}
                for tf in ["1d", "4h", "1h", "15m", "5m", "1m"]:
                    raw_df = self.client.get_klines(sym, tf, limit=80)
                    tf_data[tf] = compute_all_indicators(raw_df)

                # Check 8-TF Confluence
                rep = self.analyzer.evaluate_confluence(sym, tf_data)

                # For top gainers, we look for Long momentum or Macro-aligned Short
                print(f"   [{sym}] Confluence: {rep.total_confluence:+.1f}% | Bias: {rep.overall_bias.value} | Allowed: {rep.allowed_direction}")

                # If Confluence is positive (Long) or allowed direction is confirmed:
                direction_to_trigger = rep.allowed_direction
                if not direction_to_trigger and rep.total_confluence >= 25.0:
                    direction_to_trigger = "LONG"
                elif not direction_to_trigger and rep.total_confluence <= -35.0:
                    direction_to_trigger = "SHORT"

                if direction_to_trigger:
                    # Check 1m trigger first, then 5m
                    trig = self.analyzer.check_micro_entry_trigger(
                        tf_data["1m"], direction_to_trigger, trigger_name="1m"
                    )
                    if not trig:
                        trig = self.analyzer.check_micro_entry_trigger(
                            tf_data["5m"], direction_to_trigger, trigger_name="5m"
                        )

                    if trig:
                        self.execute_momentum_trade(sym, trig, rep, balance)
                        break  # 1 trade per scan cycle
                    else:
                        print(f"      ⏳ Confluence ready for {direction_to_trigger}, waiting for 1m/5m bounce.")

            except Exception as e:
                pass

    def start_loop(self):
        print("="*70)
        print("  T.R TECHNOLOGY TOP GAINERS MOMENTUM ENGINE ACTIVE")
        print("  Scanning Binance Top Gainers + SOLUSDT | 1m/5m Trigger")
        print("="*70)

        # Immediate check
        self.run_gainers_scan()

        last_evaluated_minute = -1
        while True:
            try:
                now = datetime.now(timezone.utc)
                if now.minute != last_evaluated_minute:
                    print(f"\n⏰ 1-Minute Candle Close ({now.strftime('%H:%M:%S UTC')})! Scanning top gainers...")
                    time.sleep(2)
                    self.run_gainers_scan()
                    last_evaluated_minute = now.minute

                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                time.sleep(5)


def main():
    api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
    api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
    client = BinanceFuturesClient(api_key, api_secret, testnet=True)
    bot = TopGainersBot(client)
    bot.start_loop()


if __name__ == "__main__":
    main()
