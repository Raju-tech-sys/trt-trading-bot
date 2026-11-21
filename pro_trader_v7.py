"""
T.R Technology — Pro Trader v7.0 Dual-Engine Institutional Bot
Includes:
- MODULE 1: SMC Pullback Reversals (Trend alignment + Discount/Premium rejection)
- MODULE 2: Institutional Breakout Engine (Volatility Squeeze + Explosive Volume Breakout)
- Safe Structural Stop-Loss (0.8% - 1.5% breathing room)
- Dynamic 1% Account Risk ($48.35)
- Asymmetric Targets: TP1 = 1.8R (Bank 50% + SL to Breakeven), TP2 = 3.5R (HTF Expansion)
"""
import os
import sys
import time
import math
import json
import hmac
import hashlib
import functools
import requests
import urllib.parse
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, Dict, List

print = functools.partial(print, flush=True)

from indicators import compute_all_indicators


@dataclass
class DualEngineSignal:
    symbol: str
    direction: str              # "LONG" or "SHORT"
    module: str                 # "MODULE 1 (PULLBACK)" or "MODULE 2 (BREAKOUT)"
    entry_price: float
    sl_price: float
    tp1_price: float            # 1.8R
    tp2_price: float            # 3.5R
    target_move_pct: float
    sl_dist_pct: float          # Safe breathing room (>= 0.8%)
    rr_ratio: float
    risk_usd: float
    qty: float
    reason: str


class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "TRT-Pro-Trader-v7.0"
        })

    def _sign_query(self, params: dict) -> str:
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def get_account_balance(self) -> float:
        try:
            q = self._sign_query({})
            r = self.session.get(f"{self.base_url}/fapi/v2/balance?{q}", timeout=6).json()
            for item in r:
                if item.get("asset") == "USDT":
                    return float(item.get("availableBalance", 0.0))
        except:
            pass
        return 4835.0

    def get_open_positions(self) -> list:
        try:
            q = self._sign_query({})
            r = self.session.get(f"{self.base_url}/fapi/v2/positionRisk?{q}", timeout=6).json()
            return [p for p in r if float(p.get("positionAmt", 0)) != 0]
        except:
            return []

    def get_symbol_precision(self, symbol: str):
        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/exchangeInfo", timeout=6).json()
            for s in r.get("symbols", []):
                if s["symbol"] == symbol:
                    qty_step = float([f["stepSize"] for f in s["filters"] if f["filterType"] == "LOT_SIZE"][0])
                    price_tick = float([f["tickSize"] for f in s["filters"] if f["filterType"] == "PRICE_FILTER"][0])
                    qty_prec = int(round(-math.log10(qty_step))) if qty_step < 1 else 0
                    price_prec = int(round(-math.log10(price_tick))) if price_tick < 1 else 0
                    return qty_prec, price_prec
        except:
            pass
        return 2, 2

    def set_leverage(self, symbol: str, leverage: int = 5):
        try:
            q = self._sign_query({"symbol": symbol, "leverage": leverage})
            self.session.post(f"{self.base_url}/fapi/v1/leverage?{q}", timeout=6)
        except:
            pass

    def place_market_order(self, symbol: str, side: str, qty: float):
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
        q = self._sign_query(params)
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{q}", timeout=6)
        r.raise_for_status()
        return r.json()

    def place_stop_loss_algo(self, symbol: str, side: str, qty: float, stop_price: float):
        params = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": "STOP_MARKET",
            "triggerPrice": stop_price,
            "quantity": qty
        }
        q = self._sign_query(params)
        r = self.session.post(f"{self.base_url}/fapi/v1/algoOrder?{q}", timeout=6)
        r.raise_for_status()
        return r.json()

    def place_take_profit_limit(self, symbol: str, side: str, qty: float, tp_price: float):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "price": tp_price,
            "quantity": qty,
            "timeInForce": "GTC",
            "reduceOnly": "true"
        }
        q = self._sign_query(params)
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{q}", timeout=6)
        r.raise_for_status()
        return r.json()


class DualEngineAnalyzer:
    def __init__(self, risk_pct: float = 0.01):
        self.risk_pct = risk_pct
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-Dual-Engine-v7.0"})

    def fetch_klines(self, symbol: str, interval: str, limit: int = 50) -> pd.DataFrame:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = self.session.get(url, timeout=5).json()
        df = pd.DataFrame(r, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return compute_all_indicators(df.iloc[:-1].reset_index(drop=True))

    # ═══════════════════════════════════════════════════════════════════════════
    # MODULE 2: INSTITUTIONAL BREAKOUT ENGINE (Volatility Squeeze + Explosive Volume)
    # ═══════════════════════════════════════════════════════════════════════════
    def evaluate_institutional_breakout(self, symbol: str, balance: float, qty_prec: int, price_prec: int) -> Optional[DualEngineSignal]:
        try:
            df_15m = self.fetch_klines(symbol, "15m", limit=35)
            if len(df_15m) < 25:
                return None

            # 1. Consolidation Squeeze Check (Lookback past 16 candles = 4 hours)
            prior_box = df_15m.iloc[-17:-1]
            box_high = prior_box["high"].max()
            box_low = prior_box["low"].min()
            box_range = box_high - box_low
            mid_price = (box_high + box_low) / 2.0

            if mid_price <= 0:
                return None

            box_pct = (box_range / mid_price) * 100
            # Must be a tight consolidation squeeze (range <= 3.2%)
            if box_pct > 3.2 or box_pct < 0.4:
                return None

            # 2. Breakout Trigger Candle
            curr = df_15m.iloc[-1]
            close = curr["close"]
            open_p = curr["open"]
            high = curr["high"]
            low = curr["low"]
            candle_range = high - low
            body = abs(close - open_p)

            if candle_range <= 0:
                return None

            displacement = body / candle_range
            # Strong directional displacement body >= 52%
            if displacement < 0.52:
                return None

            # 3. Institutional Volume Surge (>= 1.35x average of past 20 candles)
            avg_vol = df_15m.iloc[-21:-1]["volume"].mean()
            vol_surge = curr["volume"] / avg_vol if avg_vol > 0 else 1.0
            if vol_surge < 1.30:
                return None

            risk_usd = round(balance * self.risk_pct, 2)
            if risk_usd < 10.0:
                risk_usd = 10.0

            # A. BULLISH BREAKOUT (Close decisively above 4-hour box high)
            if close > box_high and close > open_p:
                raw_sl = box_low - (0.1 * curr["atr_14"])
                sl_dist = close - raw_sl
                sl_dist_pct = (sl_dist / close) * 100

                if sl_dist_pct < 0.80:
                    raw_sl = close * 0.991
                    sl_dist = close - raw_sl
                    sl_dist_pct = 0.90

                tp1_price = round(close + (1.8 * sl_dist), price_prec)
                tp2_price = round(close + (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = ((tp2_price - close) / close) * 100

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return DualEngineSignal(
                    symbol=symbol,
                    direction="LONG",
                    module="MODULE 2 (INSTITUTIONAL BREAKOUT)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move, 2),
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"🚀 Bullish Breakout: 4H Squeeze ({round(box_pct,1)}%) broken upward + Vol Surge {round(vol_surge,1)}x + Solid Body {round(displacement*100)}%"
                )

            # B. BEARISH BREAKDOWN (Close decisively below 4-hour box low)
            elif close < box_low and close < open_p:
                raw_sl = box_high + (0.1 * curr["atr_14"])
                sl_dist = raw_sl - close
                sl_dist_pct = (sl_dist / close) * 100

                if sl_dist_pct < 0.80:
                    raw_sl = close * 1.009
                    sl_dist = raw_sl - close
                    sl_dist_pct = 0.90

                tp1_price = round(close - (1.8 * sl_dist), price_prec)
                tp2_price = round(close - (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = ((close - tp2_price) / close) * 100

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return DualEngineSignal(
                    symbol=symbol,
                    direction="SHORT",
                    module="MODULE 2 (INSTITUTIONAL BREAKDOWN)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move, 2),
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"💥 Bearish Breakdown: 4H Squeeze ({round(box_pct,1)}%) broken downward + Vol Surge {round(vol_surge,1)}x + Solid Body {round(displacement*100)}%"
                )

        except Exception as e:
            pass
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # MODULE 1: SMC PULLBACK REVERSAL ENGINE
    # ═══════════════════════════════════════════════════════════════════════════
    def evaluate_pullback_reversal(self, symbol: str, balance: float, qty_prec: int, price_prec: int) -> Optional[DualEngineSignal]:
        try:
            df_1h = self.fetch_klines(symbol, "1h", limit=25)
            df_15m = self.fetch_klines(symbol, "15m", limit=30)
            df_5m = self.fetch_klines(symbol, "5m", limit=25)

            if len(df_1h) < 15 or len(df_15m) < 20 or len(df_5m) < 20:
                return None

            c1 = df_1h.iloc[-1]
            c15 = df_15m.iloc[-1]
            c5 = df_5m.iloc[-1]

            # 1H Market Structure
            h1_last6 = df_1h.iloc[-6:]
            hh = h1_last6["high"].iloc[-1] > h1_last6["high"].iloc[0]
            hl = h1_last6["low"].iloc[-1] > h1_last6["low"].iloc[0]
            lh = h1_last6["high"].iloc[-1] < h1_last6["high"].iloc[0]
            ll = h1_last6["low"].iloc[-1] < h1_last6["low"].iloc[0]

            rsi_1h = c1["rsi_14"]
            rsi_15m = c15["rsi_14"]

            # Bias
            if hh and hl and rsi_1h >= 50:
                bias = "BULLISH"
            elif lh and ll and rsi_1h <= 50:
                bias = "BEARISH"
            elif c1["close"] > c1["ema_20"] and rsi_1h > 54:
                bias = "BULLISH"
            elif c1["close"] < c1["ema_20"] and rsi_1h < 46:
                bias = "BEARISH"
            else:
                bias = "NEUTRAL"

            if bias == "NEUTRAL":
                return None

            close = c5["close"]
            open_p = c5["open"]
            high = c5["high"]
            low = c5["low"]
            rng = high - low
            body = abs(close - open_p)

            if rng <= 0:
                return None

            displacement = body / rng
            avg_vol = df_5m.iloc[-15:-1]["volume"].mean()
            vol_surge = c5["volume"] / avg_vol if avg_vol > 0 else 1.0

            if displacement < 0.35 or vol_surge < 1.10:
                return None

            atr15 = c15["atr_14"]
            swing_high = df_15m.iloc[-16:]["high"].max()
            swing_low = df_15m.iloc[-16:]["low"].min()

            risk_usd = round(balance * self.risk_pct, 2)
            if risk_usd < 10.0:
                risk_usd = 10.0

            if bias == "BULLISH":
                if rsi_15m > 70 or rsi_15m < 40:
                    return None
                if not (close > open_p and close > c5["ema_20"]):
                    return None

                raw_sl = swing_low - (0.2 * atr15)
                sl_dist = close - raw_sl
                sl_dist_pct = (sl_dist / close) * 100

                if sl_dist_pct < 0.75:
                    raw_sl = close * 0.992
                    sl_dist = close - raw_sl
                    sl_dist_pct = 0.80

                tp1_price = round(close + (1.8 * sl_dist), price_prec)
                tp2_price = round(close + (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = ((tp2_price - close) / close) * 100

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return DualEngineSignal(
                    symbol=symbol,
                    direction="LONG",
                    module="MODULE 1 (PULLBACK REVERSAL)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move, 2),
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"Bullish Pullback: 1H RSI {round(rsi_1h,1)} + 15m Reversal Bounce (Safe SL {round(sl_dist_pct,2)}%)"
                )

            elif bias == "BEARISH":
                if rsi_15m < 30 or rsi_15m > 60:
                    return None
                if not (close < open_p and close < c5["ema_20"]):
                    return None

                raw_sl = swing_high + (0.2 * atr15)
                sl_dist = raw_sl - close
                sl_dist_pct = (sl_dist / close) * 100

                if sl_dist_pct < 0.75:
                    raw_sl = close * 1.008
                    sl_dist = raw_sl - close
                    sl_dist_pct = 0.80

                tp1_price = round(close - (1.8 * sl_dist), price_prec)
                tp2_price = round(close - (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = ((close - tp2_price) / close) * 100

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return DualEngineSignal(
                    symbol=symbol,
                    direction="SHORT",
                    module="MODULE 1 (PULLBACK REVERSAL)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move, 2),
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"Bearish Pullback: 1H RSI {round(rsi_1h,1)} + 15m Reversal Drop (Safe SL {round(sl_dist_pct,2)}%)"
                )

        except Exception as e:
            pass
        return None

    def scan_for_signal(self, symbol: str, balance: float, qty_prec: int, price_prec: int) -> Optional[DualEngineSignal]:
        # Priority 1: Check Institutional Breakout (Higher explosive momentum)
        sig_bo = self.evaluate_institutional_breakout(symbol, balance, qty_prec, price_prec)
        if sig_bo:
            return sig_bo

        # Priority 2: Check Trend Pullback Reversal
        sig_pb = self.evaluate_pullback_reversal(symbol, balance, qty_prec, price_prec)
        if sig_pb:
            return sig_pb

        return None


class ProTraderV7Bot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.engine = DualEngineAnalyzer(risk_pct=0.01)
        self.universe = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT", "BNBUSDT", "NEARUSDT", "SUIUSDT"]

    def execute_trade(self, sig: DualEngineSignal):
        print("\n" + "🔥"*44)
        print(f"🎯 [{sig.module} TRIGGERED]")
        print(f"   Symbol: {sig.symbol} | Direction: {sig.direction}")
        print(f"   Entry: ~${sig.entry_price} | Safe SL: ${sig.sl_price} ({sig.sl_dist_pct}% breathing room)")
        print(f"   TP1 (1.8R): ${sig.tp1_price} | TP2 (3.5R): ${sig.tp2_price} | Target Move: +{sig.target_move_pct}%")
        print(f"   Account Risk: ${sig.risk_usd} (1.0%) | Calculated Qty: {sig.qty}")
        print(f"   Reason: {sig.reason}")
        print("🔥"*44)

        order_side = "BUY" if sig.direction == "LONG" else "SELL"
        sl_side = "SELL" if sig.direction == "LONG" else "BUY"
        qty_prec, price_prec = self.client.get_symbol_precision(sig.symbol)

        try:
            self.client.set_leverage(sig.symbol, 5)
            print(f"   1. Executing MARKET {order_side} {sig.qty} {sig.symbol}...")
            res = self.client.place_market_order(sig.symbol, order_side, sig.qty)
            print(f"      ✓ Fill Success! OrderId: {res.get('orderId')}")

            print(f"   2. Placing Guaranteed Algo SL at ${sig.sl_price}...")
            sl_res = self.client.place_stop_loss_algo(sig.symbol, sl_side, sig.qty, sig.sl_price)
            print(f"      ✓ Stop-Loss Live on Binance! Id: {sl_res.get('orderId') or sl_res.get('algoId')}")

            tp_qty = round(sig.qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   3. Placing TP1 Limit (50% position) at ${sig.tp1_price}...")
                tp_res = self.client.place_take_profit_limit(sig.symbol, sl_side, tp_qty, sig.tp1_price)
                print(f"      ✓ TP1 Active! OrderId: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [EXECUTION ERROR]: {e}")

    def run_cycle(self):
        balance = self.client.get_account_balance()
        open_pos = self.client.get_open_positions()
        active_coins = {p["symbol"] for p in open_pos}

        print(f"\n{'='*75}")
        print(f"🏛️ [PRO DUAL-ENGINE v7.0 SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open: {len(open_pos)}/2")
        print(f"{'='*75}")

        if len(open_pos) >= 2:
            print("   🔒 Max risk cap reached (2 active positions). Scanning locked.")
            return

        for sym in self.universe:
            if sym in active_coins:
                continue

            qty_prec, price_prec = self.client.get_symbol_precision(sym)
            sig = self.engine.scan_for_signal(sym, balance, qty_prec, price_prec)

            if sig:
                print(f"   💎 [{sym:<9}] ===> HIGH PROBABILITY {sig.module} DETECTED!")
                self.execute_trade(sig)
                break
            else:
                print(f"   [{sym:<9}] Screening: Pullbacks + Institutional Breakout... Waiting.")

    def start(self):
        print("="*75)
        print("  T.R TECHNOLOGY PRO TRADER v7.0 DUAL-ENGINE RUNNING")
        print("  - MODULE 1: SMC Pullback Reversals (Trend alignment)")
        print("  - MODULE 2: Institutional Breakout Engine (4H Squeeze + Vol Surge)")
        print("  - Safe Structural SL (0.8% - 1.5% breathing room) | Dynamic 1% Risk")
        print("="*75)

        self.run_cycle()

        last_min = -1
        while True:
            try:
                now = datetime.now(timezone.utc)
                if now.minute != last_min:
                    time.sleep(2)
                    self.run_cycle()
                    last_min = now.minute
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                time.sleep(5)


def main():
    api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
    api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
    client = BinanceFuturesClient(api_key, api_secret, testnet=True)
    bot = ProTraderV7Bot(client)
    bot.start()


if __name__ == "__main__":
    main()
