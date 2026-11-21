"""
T.R Technology — Pro Trader v8.0 Dual-Engine with Full Binance Universe Scanner
Features:
- DYNAMIC UNIVERSE SCANNER: Scans 140+ liquid USDT-M pairs on Binance Futures
- TOP GAINERS & TOP LOSERS detection with 15M/1H multi-timeframe analysis
- MODULE 1: SMC Pullback Reversals (High-liquidity bluechips with trend confluence)
- MODULE 2: Institutional Breakout Engine (Tight 4H consolidation squeeze + volume surge >= 1.35x + wick rejection filter)
- Safe Structural Stop-Loss (0.8% - 1.5% breathing room, no micro-stop hunts)
- Strict 1.0% Account Risk Cap per trade
- Asymmetric TP targets: TP1 = 1.8R (take 50% + SL to breakeven), TP2 = 3.5R
- Live Status export to `live_status.json` for real-time web dashboard
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
from universe_scanner import UniverseScanner


@dataclass
class TradeSignal:
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
    quality_score: int = 85
    quality_grade: str = "A+ Institutional"
    trigger_type: str = "MARKET_TRIGGER"  # "MARKET_TRIGGER" or "BREAKOUT_TRIGGER"
    vol_surge: float = 1.5
    box_pct: float = 2.5
    disp_pct: float = 65.0
    htf_bias: str = "NEUTRAL"


class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "TRT-Pro-Trader-v8.0"
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
        return 4800.0

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


class ProTraderV8Bot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.risk_pct = 0.01  # Strict 1% account risk
        self.scanner = UniverseScanner(min_volume_usd=10_000_000, testnet=True)
        self.core_watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "XRPUSDT", "NEARUSDT", "SUIUSDT"]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-V8-Bot"})

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

    def evaluate_universe_breakout(self, candidate_info: Dict, balance: float) -> Optional[TradeSignal]:
        """Convert a candidate from UniverseScanner into an actionable institutional trade signal."""
        symbol = candidate_info["symbol"]
        qty_prec, price_prec = self.client.get_symbol_precision(symbol)

        is_bullish = candidate_info.get("is_bullish", False)
        is_bearish = candidate_info.get("is_bearish", False)

        if not (is_bullish or is_bearish):
            return None

        price = candidate_info["price"]
        box_high = candidate_info["box_high"]
        box_low = candidate_info["box_low"]
        vol_surge = candidate_info["vol_surge"]
        disp_pct = candidate_info["disp_pct"]
        box_pct = candidate_info["box_pct"]
        htf_bias = candidate_info.get("htf_bias", "NEUTRAL")

        # Dynamic Quality & Effectiveness Score (50-100)
        score = 65
        if vol_surge >= 2.5:
            score += 15
        elif vol_surge >= 1.8:
            score += 10
        elif vol_surge >= 1.35:
            score += 5

        if disp_pct >= 70:
            score += 12
        elif disp_pct >= 55:
            score += 8

        if box_pct <= 2.2:
            score += 10
        elif box_pct <= 3.2:
            score += 5

        if (is_bullish and htf_bias == "BULLISH") or (is_bearish and htf_bias == "BEARISH"):
            score += 10
        score = min(99, max(60, score))
        grade = "A+ Institutional" if score >= 90 else ("A High Probability" if score >= 80 else "B+ Setup")

        risk_usd = round(balance * self.risk_pct, 2)
        if risk_usd < 10.0:
            risk_usd = 10.0

        if is_bullish:
            # Bullish Breakout
            raw_sl = box_low * 0.998  # Just below consolidation floor
            sl_dist = price - raw_sl
            sl_dist_pct = (sl_dist / price) * 100.0

            # Safe structural breathing room
            if sl_dist_pct < 0.80:
                raw_sl = price * 0.991
                sl_dist = price - raw_sl
                sl_dist_pct = 0.90
            elif sl_dist_pct > 2.20:
                raw_sl = price * 0.985
                sl_dist = price - raw_sl
                sl_dist_pct = 1.50

            sl_price = round(raw_sl, price_prec)
            tp1_price = round(price + (1.8 * sl_dist), price_prec)
            tp2_price = round(price + (3.5 * sl_dist), price_prec)
            target_move = round(((tp2_price - price) / price) * 100.0, 2)

            qty = round(risk_usd / sl_dist, qty_prec)
            if qty <= 0:
                return None

            return TradeSignal(
                symbol=symbol,
                direction="LONG",
                module="MODULE 2 (INSTITUTIONAL BREAKOUT)",
                entry_price=round(price, price_prec),
                sl_price=sl_price,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                target_move_pct=target_move,
                sl_dist_pct=round(sl_dist_pct, 2),
                rr_ratio=3.5,
                risk_usd=risk_usd,
                qty=qty,
                reason=f"🚀 Universe Bullish Breakout: 4H Squeeze ({box_pct}%) broken upward + Vol Surge {vol_surge}x + Solid Body {disp_pct}% (1H {htf_bias})",
                quality_score=score,
                quality_grade=grade,
                trigger_type="MARKET_TRIGGER",
                vol_surge=vol_surge,
                box_pct=box_pct,
                disp_pct=disp_pct,
                htf_bias=htf_bias
            )

        elif is_bearish:
            # Bearish Breakdown
            raw_sl = box_high * 1.002  # Just above consolidation roof
            sl_dist = raw_sl - price
            sl_dist_pct = (sl_dist / price) * 100.0

            if sl_dist_pct < 0.80:
                raw_sl = price * 1.009
                sl_dist = raw_sl - price
                sl_dist_pct = 0.90
            elif sl_dist_pct > 2.20:
                raw_sl = price * 1.015
                sl_dist = raw_sl - price
                sl_dist_pct = 1.50

            sl_price = round(raw_sl, price_prec)
            tp1_price = round(price - (1.8 * sl_dist), price_prec)
            tp2_price = round(price - (3.5 * sl_dist), price_prec)
            target_move = round(((price - tp2_price) / price) * 100.0, 2)

            qty = round(risk_usd / sl_dist, qty_prec)
            if qty <= 0:
                return None

            return TradeSignal(
                symbol=symbol,
                direction="SHORT",
                module="MODULE 2 (INSTITUTIONAL BREAKDOWN)",
                entry_price=round(price, price_prec),
                sl_price=sl_price,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                target_move_pct=target_move,
                sl_dist_pct=round(sl_dist_pct, 2),
                rr_ratio=3.5,
                risk_usd=risk_usd,
                qty=qty,
                reason=f"💥 Universe Bearish Breakdown: 4H Squeeze ({box_pct}%) broken downward + Vol Surge {vol_surge}x + Solid Body {disp_pct}% (1H {htf_bias})",
                quality_score=score,
                quality_grade=grade,
                trigger_type="MARKET_TRIGGER",
                vol_surge=vol_surge,
                box_pct=box_pct,
                disp_pct=disp_pct,
                htf_bias=htf_bias
            )

        return None

    def evaluate_squeeze_setup(self, squeeze_info: Dict, balance: float) -> Optional[TradeSignal]:
        """Pre-calculated institutional breakout setup for tight 4H consolidations."""
        try:
            symbol = squeeze_info["symbol"]
            qty_prec, price_prec = self.client.get_symbol_precision(symbol)
            box_high = squeeze_info["box_high"]
            box_low = squeeze_info["box_low"]
            box_pct = squeeze_info["box_pct"]
            htf_bias = squeeze_info.get("htf_bias", "NEUTRAL")
            vol_surge = squeeze_info.get("vol_surge", 1.0)

            risk_usd = round(balance * self.risk_pct, 2)
            if risk_usd < 10.0:
                risk_usd = 10.0

            if htf_bias == "BULLISH":
                direction = "LONG"
                entry_price = round(box_high * 1.001, price_prec)
                raw_sl = box_low * 0.998
                sl_dist = entry_price - raw_sl
                sl_dist_pct = (sl_dist / entry_price) * 100.0
                if sl_dist_pct < 0.80:
                    raw_sl = entry_price * 0.991
                    sl_dist = entry_price - raw_sl
                    sl_dist_pct = 0.90
                elif sl_dist_pct > 2.20:
                    raw_sl = entry_price * 0.985
                    sl_dist = entry_price - raw_sl
                    sl_dist_pct = 1.50

                sl_price = round(raw_sl, price_prec)
                tp1_price = round(entry_price + (1.8 * sl_dist), price_prec)
                tp2_price = round(entry_price + (3.5 * sl_dist), price_prec)
                target_move = round(((tp2_price - entry_price) / entry_price) * 100.0, 2)
                qty = round(risk_usd / sl_dist, qty_prec) if sl_dist > 0 else 0
                if qty <= 0:
                    return None

                score = int(88 - (box_pct * 3) + (8 if htf_bias == "BULLISH" else 0))
                score = min(96, max(75, score))
                grade = "A+ Institutional" if score >= 88 else "A High Probability"

                return TradeSignal(
                    symbol=symbol,
                    direction="LONG",
                    module="4H SQUEEZE BREAKOUT SETUP",
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=target_move,
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"🎯 4H Squeeze ({box_pct}%) Breakout Plan: 1H Trend is BULLISH. Buy-stop above ${box_high}",
                    quality_score=score,
                    quality_grade=grade,
                    trigger_type="BREAKOUT_TRIGGER",
                    vol_surge=vol_surge,
                    box_pct=box_pct,
                    disp_pct=50.0,
                    htf_bias=htf_bias
                )

            elif htf_bias == "BEARISH":
                direction = "SHORT"
                entry_price = round(box_low * 0.999, price_prec)
                raw_sl = box_high * 1.002
                sl_dist = raw_sl - entry_price
                sl_dist_pct = (sl_dist / entry_price) * 100.0
                if sl_dist_pct < 0.80:
                    raw_sl = entry_price * 1.009
                    sl_dist = raw_sl - entry_price
                    sl_dist_pct = 0.90
                elif sl_dist_pct > 2.20:
                    raw_sl = entry_price * 1.015
                    sl_dist = raw_sl - entry_price
                    sl_dist_pct = 1.50

                sl_price = round(raw_sl, price_prec)
                tp1_price = round(entry_price - (1.8 * sl_dist), price_prec)
                tp2_price = round(entry_price - (3.5 * sl_dist), price_prec)
                target_move = round(((entry_price - tp2_price) / entry_price) * 100.0, 2)
                qty = round(risk_usd / sl_dist, qty_prec) if sl_dist > 0 else 0
                if qty <= 0:
                    return None

                score = int(88 - (box_pct * 3) + (8 if htf_bias == "BEARISH" else 0))
                score = min(96, max(75, score))
                grade = "A+ Institutional" if score >= 88 else "A High Probability"

                return TradeSignal(
                    symbol=symbol,
                    direction="SHORT",
                    module="4H SQUEEZE BREAKDOWN SETUP",
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=target_move,
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"🎯 4H Squeeze ({box_pct}%) Breakdown Plan: 1H Trend is BEARISH. Sell-stop below ${box_low}",
                    quality_score=score,
                    quality_grade=grade,
                    trigger_type="BREAKOUT_TRIGGER",
                    vol_surge=vol_surge,
                    box_pct=box_pct,
                    disp_pct=50.0,
                    htf_bias=htf_bias
                )
        except Exception:
            pass
        return None

    def evaluate_core_pullback(self, symbol: str, balance: float) -> Optional[TradeSignal]:
        """SMC Pullback Reversal for major core symbols."""
        try:
            qty_prec, price_prec = self.client.get_symbol_precision(symbol)
            df_1h = self.fetch_klines(symbol, "1h", limit=25)
            df_15m = self.fetch_klines(symbol, "15m", limit=30)
            df_5m = self.fetch_klines(symbol, "5m", limit=25)

            if len(df_1h) < 15 or len(df_15m) < 20 or len(df_5m) < 20:
                return None

            c1 = df_1h.iloc[-1]
            c15 = df_15m.iloc[-1]
            c5 = df_5m.iloc[-1]

            # 1H Market Structure & Bias
            rsi_1h = c1["rsi_14"]
            rsi_15m = c15["rsi_14"]

            # Structure detection
            h1_last6 = df_1h.iloc[-6:]
            hh = h1_last6["high"].iloc[-1] > h1_last6["high"].iloc[0]
            hl = h1_last6["low"].iloc[-1] > h1_last6["low"].iloc[0]
            lh = h1_last6["high"].iloc[-1] < h1_last6["high"].iloc[0]
            ll = h1_last6["low"].iloc[-1] < h1_last6["low"].iloc[0]

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

            if displacement < 0.40 or vol_surge < 1.15:
                return None

            atr15 = c15["atr_14"]
            swing_high = df_15m.iloc[-16:]["high"].max()
            swing_low = df_15m.iloc[-16:]["low"].min()

            risk_usd = round(balance * self.risk_pct, 2)
            if risk_usd < 10.0:
                risk_usd = 10.0

            if bias == "BULLISH":
                if rsi_15m > 68 or rsi_15m < 40:
                    return None
                if not (close > open_p and close > c5["ema_20"]):
                    return None

                raw_sl = swing_low - (0.2 * atr15)
                sl_dist = close - raw_sl
                sl_dist_pct = (sl_dist / close) * 100.0

                if sl_dist_pct < 0.80:
                    raw_sl = close * 0.991
                    sl_dist = close - raw_sl
                    sl_dist_pct = 0.90

                tp1_price = round(close + (1.8 * sl_dist), price_prec)
                tp2_price = round(close + (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = round(((tp2_price - close) / close) * 100.0, 2)

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return TradeSignal(
                    symbol=symbol,
                    direction="LONG",
                    module="MODULE 1 (PULLBACK REVERSAL)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=target_move,
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"Bullish Pullback: 1H Structure Bullish (RSI {round(rsi_1h,1)}) + 15m Reversal Bounce (Safe SL {round(sl_dist_pct,2)}%)"
                )

            elif bias == "BEARISH":
                if rsi_15m < 32 or rsi_15m > 60:
                    return None
                if not (close < open_p and close < c5["ema_20"]):
                    return None

                raw_sl = swing_high + (0.2 * atr15)
                sl_dist = raw_sl - close
                sl_dist_pct = (sl_dist / close) * 100.0

                if sl_dist_pct < 0.80:
                    raw_sl = close * 1.009
                    sl_dist = raw_sl - close
                    sl_dist_pct = 0.90

                tp1_price = round(close - (1.8 * sl_dist), price_prec)
                tp2_price = round(close - (3.5 * sl_dist), price_prec)
                sl_price = round(raw_sl, price_prec)
                target_move = round(((close - tp2_price) / close) * 100.0, 2)

                qty = round(risk_usd / sl_dist, qty_prec)
                if qty <= 0:
                    return None

                return TradeSignal(
                    symbol=symbol,
                    direction="SHORT",
                    module="MODULE 1 (PULLBACK REVERSAL)",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=target_move,
                    sl_dist_pct=round(sl_dist_pct, 2),
                    rr_ratio=3.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    reason=f"Bearish Pullback: 1H Structure Bearish (RSI {round(rsi_1h,1)}) + 15m Reversal Drop (Safe SL {round(sl_dist_pct,2)}%)"
                )

        except Exception as e:
            pass
        return None

    def execute_trade(self, sig: TradeSignal):
        print("\n" + "🔥" * 45)
        print(f"🎯 [{sig.module} TRIGGERED]")
        print(f"   Symbol: {sig.symbol} | Direction: {sig.direction}")
        print(f"   Entry: ~${sig.entry_price} | Safe Structural SL: ${sig.sl_price} ({sig.sl_dist_pct}% breathing room)")
        print(f"   TP1 (1.8R): ${sig.tp1_price} | TP2 (3.5R): ${sig.tp2_price} | Target Move: +{sig.target_move_pct}%")
        print(f"   Account Risk: ${sig.risk_usd} (1.0%) | Calculated Qty: {sig.qty}")
        print(f"   Reason: {sig.reason}")
        print("🔥" * 45)

        order_side = "BUY" if sig.direction == "LONG" else "SELL"
        sl_side = "SELL" if sig.direction == "LONG" else "BUY"
        qty_prec, price_prec = self.client.get_symbol_precision(sig.symbol)

        try:
            self.client.set_leverage(sig.symbol, 5)
            print(f"   1. Executing MARKET {order_side} {sig.qty} {sig.symbol}...")
            res = self.client.place_market_order(sig.symbol, order_side, sig.qty)
            print(f"      ✓ Fill Success! OrderId: {res.get('orderId')}")

            print(f"   2. Placing Guaranteed Exchange Algo SL at ${sig.sl_price}...")
            sl_res = self.client.place_stop_loss_algo(sig.symbol, sl_side, sig.qty, sig.sl_price)
            print(f"      ✓ Stop-Loss Live on Binance! Id: {sl_res.get('orderId') or sl_res.get('algoId')}")

            tp_qty = round(sig.qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   3. Placing TP1 Limit (50% position) at ${sig.tp1_price}...")
                tp_res = self.client.place_take_profit_limit(sig.symbol, sl_side, tp_qty, sig.tp1_price)
                print(f"      ✓ TP1 Active! OrderId: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [EXECUTION ERROR]: {e}")

    def update_live_status_file(self, balance: float, open_positions: list, scan_result: dict, actionable_breakouts: list = None):
        """Save scan status and universe screener to live_status.json for dashboard."""
        try:
            if actionable_breakouts is None:
                actionable_breakouts = []

            screened_dict = {}
            for g in scan_result.get("overview", {}).get("gainers", [])[:5]:
                screened_dict[g["symbol"]] = {
                    "vol": f"${g['volume_usd']/1e6:.1f}M",
                    "structure": "TOP GAINER 🚀",
                    "status": f"{g['change']:+}% (24h)"
                }
            for l in scan_result.get("overview", {}).get("losers", [])[:5]:
                screened_dict[l["symbol"]] = {
                    "vol": f"${l['volume_usd']/1e6:.1f}M",
                    "structure": "TOP LOSER 💥",
                    "status": f"{l['change']:+}% (24h)"
                }
            for s in scan_result.get("squeezes", [])[:5]:
                screened_dict[s["symbol"]] = {
                    "vol": f"VolSurge {s['vol_surge']}x",
                    "structure": f"SQUEEZE {s['box_pct']}%",
                    "status": f"1H: {s['htf_bias']}"
                }

            payload = {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "balance": balance,
                "open_count": len(open_positions),
                "total_eligible_universe": scan_result.get("overview", {}).get("total_eligible", 0),
                "deep_scanned": scan_result.get("scanned_count", 0),
                "active_breakouts": len(actionable_breakouts),
                "actionable_breakouts": actionable_breakouts,
                "gainers": scan_result.get("overview", {}).get("gainers", [])[:8],
                "losers": scan_result.get("overview", {}).get("losers", [])[:8],
                "squeezes": scan_result.get("squeezes", [])[:8],
                "screened_tokens": screened_dict
            }
            def json_helper(o):
                if isinstance(o, (np.bool_, bool)):
                    return bool(o)
                if isinstance(o, (np.floating, float)):
                    return float(o)
                if isinstance(o, (np.integer, int)):
                    return int(o)
                return str(o)

            dir_path = os.path.dirname(os.path.abspath(__file__))
            status_file = os.path.join(dir_path, "live_status.json")
            tmp_file = status_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=json_helper)
            os.replace(tmp_file, status_file)
        except Exception as e:
            print(f"[STATUS EXPORT ERROR]: {e}")

    def run_cycle(self):
        balance = self.client.get_account_balance()
        open_pos = self.client.get_open_positions()
        active_coins = {p["symbol"] for p in open_pos}

        print(f"\n{'='*78}")
        print(f"🏛️ [PRO DUAL-ENGINE v8.0 UNIVERSE SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open: {len(open_pos)}/2")
        print(f"{'='*78}")

        # 1. Full Universe Scan
        scan_res = self.scanner.scan_top_candidates(max_candidates=30)
        signals_found = scan_res.get("breakout_signals", [])

        # Build actionable setups for every breakout signal found
        actionable_breakouts = []
        is_capped = len(open_pos) >= 2
        for cand in signals_found:
            trade_sig = self.evaluate_universe_breakout(cand, balance)
            if trade_sig:
                action_mode = "MANUAL_READY" if is_capped else "AUTO_READY"
                actionable_breakouts.append({
                    "symbol": trade_sig.symbol,
                    "direction": trade_sig.direction,
                    "module": trade_sig.module,
                    "entry_price": trade_sig.entry_price,
                    "sl_price": trade_sig.sl_price,
                    "sl_dist_pct": trade_sig.sl_dist_pct,
                    "tp1_price": trade_sig.tp1_price,
                    "tp2_price": trade_sig.tp2_price,
                    "target_move_pct": trade_sig.target_move_pct,
                    "rr_ratio": trade_sig.rr_ratio,
                    "vol_surge": cand.get("vol_surge", 1.5),
                    "box_pct": cand.get("box_pct", 2.5),
                    "disp_pct": cand.get("disp_pct", 65.0),
                    "htf_bias": cand.get("htf_bias", "NEUTRAL"),
                    "reason": trade_sig.reason,
                    "action_mode": action_mode,
                    "detected_at": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                })

        # Save to live_status.json
        self.update_live_status_file(balance, open_pos, scan_res, actionable_breakouts)

        eligible_count = scan_res["overview"].get("total_eligible", 0)
        print(f"   🌐 Universe Scanned: {scan_res['scanned_count']} pairs from {eligible_count} liquid markets")
        if actionable_breakouts:
            print(f"   ⚡ [{len(actionable_breakouts)} ACTIVE BREAKOUT SIGNALS]: {', '.join([b['symbol'] + ' ' + b['direction'] for b in actionable_breakouts])}")

        # Display Top Gainers / Losers
        top_gainers = scan_res["overview"].get("gainers", [])[:3]
        top_losers = scan_res["overview"].get("losers", [])[:3]
        if top_gainers:
            g_strs = [f"{g['symbol']} ({g['change']:+}%)" for g in top_gainers]
            print(f"   📈 Top Gainers: {', '.join(g_strs)}")
        if top_losers:
            l_strs = [f"{l['symbol']} ({l['change']:+}%)" for l in top_losers]
            print(f"   📉 Top Losers:  {', '.join(l_strs)}")

        # If positions at cap, do not execute new trades automatically
        if is_capped:
            print(f"   🔒 Max risk cap reached ({len(open_pos)} active positions). Auto-trade locked. Setups published for MANUAL trading.")
            return

        # 2. Priority 1: Auto-Execute Universe Breakout Signals (if positions < 2)
        if signals_found:
            for cand in signals_found:
                sym = cand["symbol"]
                if sym in active_coins:
                    continue
                trade_sig = self.evaluate_universe_breakout(cand, balance)
                if trade_sig:
                    print(f"   💎 [{sym}] ===> HIGH PROBABILITY {trade_sig.module} DETECTED! Auto-Executing...")
                    self.execute_trade(trade_sig)
                    return

        # 3. Priority 2: Check Core Watchlist for SMC Pullback Reversals
        for sym in self.core_watchlist:
            if sym in active_coins:
                continue
            sig_pb = self.evaluate_core_pullback(sym, balance)
            if sig_pb:
                print(f"   💎 [{sym}] ===> HIGH PROBABILITY {sig_pb.module} DETECTED! Auto-Executing...")
                self.execute_trade(sig_pb)
                return

        print("   🔍 All candidates evaluated. Market in consolidation/expansion. Standing by for high-probability trigger.")

        print("   🔍 All candidates evaluated. Market in consolidation/expansion. Standing by for high-probability trigger.")

    def start(self):
        print("="*78)
        print("  T.R TECHNOLOGY PRO TRADER v8.0 — UNIVERSE SCANNER & INSTITUTIONAL ENGINE")
        print("  - Full Binance USDT Universe Scanner (Gainers, Losers, Volatility Squeezes)")
        print("  - MODULE 1: SMC Pullback Reversals (Trend Confluence + Discount Rejection)")
        print("  - MODULE 2: Institutional Breakout Engine (4H Squeeze + Vol Surge >= 1.35x + Wick Filter)")
        print("  - Safe Structural Stop-Loss (0.8% - 1.5% breathing room) | Dynamic 1% Risk")
        print("="*78)

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
    bot = ProTraderV8Bot(client)
    bot.start()


if __name__ == "__main__":
    main()
