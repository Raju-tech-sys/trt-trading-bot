"""
T.R Technology — Production Institutional Sniper Live Bot (Phase 6)
Multi-Level Institutional Framework:
1. Token Filter: High Volume (> $50M), Open Interest (OI) Confirmation, Neutral Funding Rate
2. HTF Structure: 4H, 1H, 15M Alignment (Higher Timeframe Trend Direction)
3. Fee-Crushing Target: Target Gain >= 1.5% & R:R >= 3.0 (Zero fee drag!)
4. Micro 1-Minute Sniper Trigger: 1m closed candle + Volume Surge (>= 1.3x)
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
from institutional_engine import InstitutionalSniperEngine, InstitutionalSignal


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
            "User-Agent": "TRT-Institutional-Bot-v4.0"
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

    def get_active_market_leaders(self, min_volume: float = 40_000_000) -> list:
        """Fetch high liquidity active tokens (Volume > $40M, top volatility)."""
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=8).json()
            candidates = []
            for item in r:
                sym = item.get("symbol", "")
                if sym.endswith("USDT") and "_" not in sym:
                    try:
                        vol = float(item["quoteVolume"])
                        pct = abs(float(item["priceChangePercent"]))
                        if vol >= min_volume:
                            candidates.append({
                                "symbol": sym,
                                "volume": vol,
                                "volatility": pct,
                                "price": float(item["lastPrice"])
                            })
                    except:
                        pass
            # Sort by highest volume + volatility
            candidates.sort(key=lambda x: x["volume"] * (x["volatility"] + 1), reverse=True)
            top_symbols = [c["symbol"] for c in candidates[:8]]
            for mandatory in ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]:
                if mandatory not in top_symbols:
                    top_symbols.append(mandatory)
            return top_symbols
        except Exception as e:
            return ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]

    def get_klines(self, symbol: str, interval: str, limit: int = 60) -> pd.DataFrame:
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
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "timestamp": int(time.time() * 1000)
        }
        import urllib.parse
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{query}&signature={sig}")
        r.raise_for_status()
        return r.json()

    def place_stop_loss_market(self, symbol: str, side: str, qty: float, stop_price: float):
        import urllib.parse
        params = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": "STOP_MARKET",
            "triggerPrice": stop_price,
            "quantity": qty,
            "timestamp": int(time.time() * 1000)
        }
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        r = self.session.post(f"{self.base_url}/fapi/v1/algoOrder?{query}&signature={sig}")
        r.raise_for_status()
        return r.json()

    def place_take_profit_limit(self, symbol: str, side: str, qty: float, tp_price: float):
        import urllib.parse
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "price": tp_price,
            "quantity": qty,
            "timeInForce": "GTC",
            "reduceOnly": "true",
            "timestamp": int(time.time() * 1000)
        }
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{query}&signature={sig}")
        r.raise_for_status()
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# INSTITUTIONAL BOT CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

class InstitutionalBot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.engine = InstitutionalSniperEngine(min_volume_24h_usd=30_000_000)
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

    def execute_sniper_trade(self, sig: InstitutionalSignal, balance: float):
        print(f"\n💎💎💎 [INSTITUTIONAL SNIPER TRADE TRIGGERED] {sig.symbol} {sig.direction}!")
        print(f"   Reason: {sig.reason}")
        print(f"   HTF Trend: {sig.htf_trend} | OI Trend: {sig.oi_trend}")
        print(f"   Entry: ~${sig.entry_price} | SL: ${sig.sl_price} | TP1: ${sig.tp1_price} | TP2: ${sig.tp2_price}")
        print(f"   Target Move: +{sig.target_gain_pct}% | R:R Ratio: {sig.rr_ratio}:1 | 1m Volume Surge: {sig.volume_surge}x")

        risk_usd = 5.0  # Fixed $5 risk
        sl_dist = abs(sig.entry_price - sig.sl_price)
        if sl_dist <= 0:
            return

        raw_qty = risk_usd / sl_dist
        qty_prec, price_prec = self.client.get_symbol_precision(sig.symbol)
        qty = round(raw_qty, qty_prec)

        if qty <= 0:
            print(f"   ⚠️ Calculated qty {raw_qty} rounded to 0. Skipping.")
            return

        order_side = "BUY" if sig.direction == "LONG" else "SELL"
        sl_side = "SELL" if sig.direction == "LONG" else "BUY"
        sl_price = round(sig.sl_price, price_prec)
        tp1_price = round(sig.tp1_price, price_prec)

        try:
            self.client.set_leverage(sig.symbol, 5)
            print(f"   1. Executing MARKET {order_side} {qty} {sig.symbol}...")
            entry_res = self.client.place_market_order(sig.symbol, order_side, qty)
            print(f"      ✓ Filled! Order ID: {entry_res.get('orderId')}")

            print(f"   2. Placing Exchange Stop-Loss at ${sl_price}...")
            sl_res = self.client.place_stop_loss_market(sig.symbol, sl_side, qty, sl_price)
            print(f"      ✓ Stop-Loss Active on Binance! ID: {sl_res.get('orderId')}")

            tp_qty = round(qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   3. Placing TP1 (50%) at ${tp1_price}...")
                tp_res = self.client.place_take_profit_limit(sig.symbol, sl_side, tp_qty, tp1_price)
                print(f"      ✓ TP1 Active! ID: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [ERROR] Order placement failed: {e}")
            try:
                self.client.place_market_order(sig.symbol, sl_side, qty)
            except:
                pass

    def run_institutional_cycle(self):
        balance = self.sync_account()
        open_positions = self.client.get_open_positions()
        active_coins = {p["symbol"] for p in open_positions}

        print(f"\n{'='*75}")
        print(f"🏛️ [INSTITUTIONAL SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open: {len(open_positions)}/2")
        print(f"{'='*75}")

        if len(open_positions) >= 2:
            print("   Max positions (2) active. Scanning skipped.")
            return

        leaders = self.client.get_active_market_leaders(min_volume=40_000_000)
        print(f"   Screened Institutional Tokens: {leaders}")

        for sym in leaders:
            if sym in active_coins:
                continue

            try:
                # Layer 1: Market Metrics (Volume, OI, Funding Rate)
                metrics = self.engine.get_token_market_metrics(sym)
                if not metrics:
                    continue

                # Layer 2: HTF Market Structure (4h, 1h, 15m)
                df_4h = compute_all_indicators(self.client.get_klines(sym, "4h", limit=50))
                df_1h = compute_all_indicators(self.client.get_klines(sym, "1h", limit=50))
                df_15m = compute_all_indicators(self.client.get_klines(sym, "15m", limit=50))

                htf = self.engine.analyze_htf_structure(df_4h, df_1h, df_15m)

                # Layer 3 & 4: 1m Sniper Trigger with Volume Surge
                df_1m = compute_all_indicators(self.client.get_klines(sym, "1m", limit=35))
                sig = self.engine.check_sniper_1m_trigger(df_1m, htf, metrics)

                vol_m = round(metrics["volume_24h_usd"] / 1e6, 1)
                oi_m = round(metrics["oi_usd"] / 1e6, 1)

                print(f"   [{sym:<9}] Vol: ${vol_m}M | OI: ${oi_m}M | Structure: 4h={htf['trend_4h']}, 1h={htf['trend_1h']}, 15m={htf['trend_15m']} | Aligned: {htf['aligned']}")

                if sig:
                    self.execute_sniper_trade(sig, balance)
                    break  # 1 position per scan tick
                else:
                    if htf["aligned"]:
                        print(f"             ⚡ HTF {htf['overall_direction']} ALIGNED! Waiting for 1m volume surge pullback.")
                    else:
                        print(f"             ⏳ HTF Mixed/Choppy. Protecting capital.")

            except Exception as e:
                pass

    def start_loop(self):
        print("="*75)
        print("  T.R TECHNOLOGY INSTITUTIONAL SNIPER ENGINE RUNNING")
        print("  Deep Token Screening: Volume + Open Interest (OI) + HTF Structure")
        print("  Trigger: 1-Minute Closed Candle + Volume Surge (Fee-Beating R:R >= 3.0)")
        print("="*75)

        self.run_institutional_cycle()

        last_evaluated_minute = -1
        while True:
            try:
                now = datetime.now(timezone.utc)
                if now.minute != last_evaluated_minute:
                    print(f"\n⏰ 1-Minute Closed ({now.strftime('%H:%M:%S UTC')})! Evaluating institutional setups...")
                    time.sleep(2)
                    self.run_institutional_cycle()
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
    bot = InstitutionalBot(client)
    bot.start_loop()


if __name__ == "__main__":
    main()
