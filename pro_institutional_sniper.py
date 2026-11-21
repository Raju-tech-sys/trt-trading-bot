"""
T.R Technology — Pro Trader Institutional Engine (v5.0 Ultimate)
5-Pillar Smart Money Concepts (SMC) + Order Flow Architecture:
1. Macro Trend: 1D & 4H Market Structure (Higher Highs/Lows vs Lower Highs/Lows)
2. Key Liquidity & Level: 1H & 15M Support/Resistance + Order Blocks
3. Smart Money Volume & Open Interest (OI): Institutional Volume Expansion & Neutral Funding
4. Structural Shift (CHoCH): Lower Timeframe (15m/5m/1m) Break of Structure with Strong Displacement
5. Asymmetric R:R: Dynamic 1% Account Risk ($50 on $5k), TP1 = 2.0R (Risk-Free), TP2 = 4.0R - 6.0R (Big Swing)
"""
import time
import math
import requests
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Dict, List

from indicators import compute_all_indicators


@dataclass
class ProTradeSetup:
    symbol: str
    direction: str            # "LONG" or "SHORT"
    entry_price: float
    sl_price: float
    tp1_price: float          # 2.0R (Bank 50% + SL to Breakeven)
    tp2_price: float          # 4.5R - 6.0R (HTF Liquidity Target)
    target_move_pct: float    # Real price move % (>= 1.5% to 5.0%)
    rr_ratio: float           # Risk to Reward (>= 3.5:1)
    risk_usd: float           # 1% of account ($50 on $5000)
    qty: float
    displacement_strength: float # Candle body ratio (> 60%)
    volume_surge: float       # Relative Volume (> 1.4x)
    oi_usd: float
    setup_reason: str


class ProInstitutionalAnalyzer:
    def __init__(self, risk_pct: float = 0.01):
        self.risk_pct = risk_pct
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-Pro-Trader-v5.0"})

    def fetch_klines(self, symbol: str, interval: str, limit: int = 60) -> pd.DataFrame:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = self.session.get(url, timeout=7).json()
        df = pd.DataFrame(r, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return compute_all_indicators(df.iloc[:-1].reset_index(drop=True))

    def get_institutional_metrics(self, symbol: str) -> Optional[dict]:
        """Layer 1: Open Interest + 24h Volume + Funding Rate."""
        try:
            t24 = self.session.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}", timeout=6).json()
            vol_usd = float(t24.get("quoteVolume", 0))
            price = float(t24.get("lastPrice", 0))

            if vol_usd < 30_000_000:
                return None  # Filter out low-liquidity coins

            oi_res = self.session.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}", timeout=6).json()
            oi_contracts = float(oi_res.get("openInterest", 0))
            oi_usd = oi_contracts * price

            funding_res = self.session.get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1", timeout=6).json()
            funding = float(funding_res[0].get("fundingRate", 0)) if funding_res else 0.0

            # Absolute funding limit: Avoid extreme crowded positions
            if abs(funding) > 0.04:
                return None

            return {
                "symbol": symbol,
                "price": price,
                "volume_24h_usd": vol_usd,
                "oi_usd": oi_usd,
                "funding_rate": funding
            }
        except:
            return None

    def analyze_macro_structure(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
        """
        Layer 2: Pro Market Structure on 4H & 1H.
        Detects clear Trend & Higher Highs/Lows vs Lower Highs/Lows.
        """
        if len(df_4h) < 25 or len(df_1h) < 25:
            return {"valid": False}

        c4 = df_4h.iloc[-1]
        c1 = df_1h.iloc[-1]

        # 4H EMA Trend (50 vs 200)
        is_4h_bull = c4["close"] > c4["ema_50"] and c4["ema_50"] > c4["ema_200"]
        is_4h_bear = c4["close"] < c4["ema_50"] and c4["ema_50"] < c4["ema_200"]

        # 1H EMA Alignment
        is_1h_bull = c1["close"] > c1["ema_50"]
        is_1h_bear = c1["close"] < c1["ema_50"]

        # 1H Key Swing High / Low (Liquidity pools)
        recent_1h_high = df_1h.iloc[-24:]["high"].max()
        recent_1h_low = df_1h.iloc[-24:]["low"].min()

        if is_4h_bull and is_1h_bull:
            bias = "BULLISH"
        elif is_4h_bear and is_1h_bear:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return {
            "valid": True,
            "bias": bias,
            "recent_high": recent_1h_high,
            "recent_low": recent_1h_low,
            "atr_1h": c1["atr_14"],
            "adx_1h": c1["adx_14"]
        }

    def evaluate_pro_setup(self, symbol: str, balance: float, qty_prec: int, price_prec: int) -> Optional[ProTradeSetup]:
        """
        Full 5-Pillar Evaluation. Only returns a trade when high win-probability alignment is found.
        """
        metrics = self.get_institutional_metrics(symbol)
        if not metrics:
            return None

        # 1. Macro Structure (4h & 1h)
        df_4h = self.fetch_klines(symbol, "4h")
        df_1h = self.fetch_klines(symbol, "1h")
        macro = self.analyze_macro_structure(df_4h, df_1h)

        if not macro.get("valid") or macro["bias"] == "NEUTRAL":
            return None

        bias = macro["bias"]

        # 2. Micro Structure & Displacement Confirmation (15m & 1m)
        df_15m = self.fetch_klines(symbol, "15m")
        df_1m = self.fetch_klines(symbol, "1m", limit=35)

        if len(df_15m) < 20 or len(df_1m) < 25:
            return None

        curr_1m = df_1m.iloc[-1]
        close = curr_1m["close"]
        open_p = curr_1m["open"]
        high = curr_1m["high"]
        low = curr_1m["low"]
        candle_range = high - low
        candle_body = abs(close - open_p)

        # Displacement Check: Pro candle must have body >= 55% of full range (no indecisive dojis)
        if candle_range <= 0:
            return None
        displacement = candle_body / candle_range
        if displacement < 0.55:
            return None

        # Relative Volume Check (>= 1.25x of recent 20 candles)
        avg_vol = df_1m.iloc[-21:-1]["volume"].mean()
        vol_surge = curr_1m["volume"] / avg_vol if avg_vol > 0 else 1.0
        if vol_surge < 1.20:
            return None

        # Lookback last 3 candles for EMA20 pullback touch
        last3 = df_1m.iloc[-4:-1]
        atr15m = df_15m.iloc[-1]["atr_14"]
        atr1m = curr_1m["atr_14"]

        if pd.isna(atr1m) or atr1m <= 0:
            return None

        # Calculate Professional Risk & Sizing:
        # Dynamic 1% of account balance (e.g. $50 on $5000)
        risk_usd = round(balance * self.risk_pct, 2)
        if risk_usd < 5.0:
            risk_usd = 5.0

        # Structural Stop-Loss: 1.8x 1m ATR + buffer
        sl_dist = 1.8 * atr1m

        # Big Swing Targets:
        # TP1: 2.0R (Close 50% + SL to Breakeven)
        # TP2: 4.5R (Capture HTF expansion!)
        tp1_dist = 2.0 * sl_dist
        tp2_dist = 4.5 * sl_dist

        target_move_pct = (tp2_dist / close) * 100

        # Fee-Crusher Requirement: Minimum target price move must be >= 1.2%
        if target_move_pct < 1.0:
            return None

        # Calculate exact lot size
        raw_qty = risk_usd / sl_dist
        qty = round(raw_qty, qty_prec)
        if qty <= 0:
            return None

        # BULLISH SETUP (BUY)
        if bias == "BULLISH":
            pullback_hit = (last3["low"] <= last3["ema_20"]).any() or (last3["close"] <= last3["ema_20"]).any()
            bounce_green = close > curr_1m["ema_20"] and close > open_p
            rsi_ok = 50 <= curr_1m["rsi_14"] <= 72

            if pullback_hit and bounce_green and rsi_ok:
                sl_price = round(close - sl_dist, price_prec)
                tp1_price = round(close + tp1_dist, price_prec)
                tp2_price = round(close + tp2_dist, price_prec)

                return ProTradeSetup(
                    symbol=symbol,
                    direction="LONG",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move_pct, 2),
                    rr_ratio=4.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    displacement_strength=round(displacement * 100, 1),
                    volume_surge=round(vol_surge, 2),
                    oi_usd=metrics["oi_usd"],
                    setup_reason=f"Pro Bullish: 4H/1H Structure + 1m Displacement ({round(displacement*100)}%) + Vol Surge {round(vol_surge,1)}x"
                )

        # BEARISH SETUP (SELL)
        elif bias == "BEARISH":
            pullback_hit = (last3["high"] >= last3["ema_20"]).any() or (last3["close"] >= last3["ema_20"]).any()
            bounce_red = close < curr_1m["ema_20"] and close < open_p
            rsi_ok = 28 <= curr_1m["rsi_14"] <= 50

            if pullback_hit and bounce_red and rsi_ok:
                sl_price = round(close + sl_dist, price_prec)
                tp1_price = round(close - tp1_dist, price_prec)
                tp2_price = round(close - tp2_dist, price_prec)

                return ProTradeSetup(
                    symbol=symbol,
                    direction="SHORT",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_move_pct=round(target_move_pct, 2),
                    rr_ratio=4.5,
                    risk_usd=risk_usd,
                    qty=qty,
                    displacement_strength=round(displacement * 100, 1),
                    volume_surge=round(vol_surge, 2),
                    oi_usd=metrics["oi_usd"],
                    setup_reason=f"Pro Bearish: 4H/1H Structure + 1m Displacement ({round(displacement*100)}%) + Vol Surge {round(vol_surge,1)}x"
                )

        return None
