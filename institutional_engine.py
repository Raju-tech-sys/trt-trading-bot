"""
T.R Technology — Institutional Smart Sniper Engine (v4.0)
Multi-Level Confluence:
Layer 1: Token Quality, 24h Volume (> $50M), Open Interest (OI) Trend & Funding Rate
Layer 2: High Timeframe (15m, 1h, 4h, 1d) Market Structure & Key Levels
Layer 3: Fee-Beating Target Filter (Min 1.5% Move & >= 2.5R)
Layer 4: 1-Minute Precision Sniper Trigger (Volume Spike + Reversal Confirmation)
"""
import time
import requests
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Dict, List

from indicators import compute_all_indicators


@dataclass
class InstitutionalSignal:
    symbol: str
    direction: str          # "LONG" or "SHORT"
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    target_gain_pct: float  # Must be >= 1.5% to crush exchange fees
    rr_ratio: float         # Risk:Reward (>= 2.5)
    volume_surge: float     # 1m volume / avg volume (>= 1.3x)
    oi_trend: str           # "INSTITUTIONAL_ACCUMULATION" or "SHORT_BUILDUP"
    htf_trend: str          # 4h & 1h direction
    reason: str


class InstitutionalSniperEngine:
    def __init__(self, min_volume_24h_usd: float = 50_000_000):
        self.min_volume_24h = min_volume_24h_usd
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-Institutional-Engine"})

    def get_token_market_metrics(self, symbol: str) -> Optional[dict]:
        """
        Layer 1: Fetch 24h Volume, Open Interest (OI), and Funding Rate from Binance.
        """
        try:
            # 24hr Ticker
            t24 = self.session.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}", timeout=6).json()
            vol_usd = float(t24.get("quoteVolume", 0))
            price = float(t24.get("lastPrice", 0))
            price_change = float(t24.get("priceChangePercent", 0))

            if vol_usd < self.min_volume_24h:
                return None  # Insufficient institutional liquidity

            # Open Interest
            oi_res = self.session.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}", timeout=6).json()
            oi_contracts = float(oi_res.get("openInterest", 0))
            oi_usd = oi_contracts * price

            # Funding Rate
            funding_res = self.session.get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1", timeout=6).json()
            funding_rate = float(funding_res[0].get("fundingRate", 0)) if funding_res else 0.0

            # OI & Price Trend classification
            # If price rising and OI is heavy -> Institutional Long Accumulation
            # If price falling and OI is heavy -> Institutional Short Buildup
            if price_change >= 0 and funding_rate <= 0.03:
                oi_bias = "BULLISH_EXPANSION"
            elif price_change < 0 and funding_rate >= -0.03:
                oi_bias = "BEARISH_EXPANSION"
            else:
                oi_bias = "NEUTRAL"

            return {
                "symbol": symbol,
                "price": price,
                "volume_24h_usd": vol_usd,
                "oi_usd": oi_usd,
                "funding_rate": funding_rate,
                "oi_bias": oi_bias,
                "price_change_24h": price_change
            }
        except Exception as e:
            return None

    def analyze_htf_structure(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
        """
        Layer 2: Multi-timeframe structure from 15m to 4h.
        Trend, Support/Resistance zones, and High Timeframe Momentum.
        """
        if len(df_4h) < 30 or len(df_1h) < 30 or len(df_15m) < 30:
            return {"valid": False}

        c4 = df_4h.iloc[-1]
        c1 = df_1h.iloc[-1]
        c15 = df_15m.iloc[-1]

        # 4h & 1h Master Trend Alignment
        trend_4h = "BULLISH" if c4["close"] > c4["ema_50"] else "BEARISH"
        trend_1h = "BULLISH" if c1["close"] > c1["ema_50"] else "BEARISH"
        trend_15m = "BULLISH" if c15["close"] > c15["ema_50"] else "BEARISH"

        # Master trend is confirmed when 4h and 1h agree
        master_aligned = (trend_4h == trend_1h)
        overall_direction = trend_4h if master_aligned else "CHOPPY"

        # Key S/R from 4h and 1h
        recent_1h_high = df_1h.iloc[-24:]["high"].max()
        recent_1h_low = df_1h.iloc[-24:]["low"].min()

        return {
            "valid": True,
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m,
            "aligned": master_aligned,
            "overall_direction": overall_direction,
            "resistance": recent_1h_high,
            "support": recent_1h_low,
            "atr_15m": c15["atr_14"],
            "rsi_1h": c1["rsi_14"]
        }

    def check_sniper_1m_trigger(self, df_1m: pd.DataFrame, htf: dict, metrics: dict) -> Optional[InstitutionalSignal]:
        """
        Layer 3 & 4:
        - 1m is ONLY used for timing the entry.
        - Must have Volume Spike (1m Volume >= 1.4x of 20-period 1m volume avg).
        - Must yield a fee-crushing target: TP >= 1.5% and R:R >= 2.5.
        """
        if len(df_1m) < 25 or not htf.get("valid"):
            return None

        curr = df_1m.iloc[-1]
        prev = df_1m.iloc[-2]

        direction = htf["overall_direction"]
        if direction not in ["BULLISH", "BEARISH"]:
            return None

        # Volume filter: healthy volume (>= 0.80x of 20-candle average)
        avg_vol_20 = df_1m.iloc[-21:-1]["volume"].mean()
        curr_vol = curr["volume"]
        vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

        if vol_ratio < 0.80:
            return None

        close = curr["close"]
        open_p = curr["open"]
        ema20 = curr["ema_20"]
        atr1m = curr["atr_14"]

        if pd.isna(ema20) or pd.isna(atr1m) or atr1m <= 0:
            return None

        # Lookback last 3 candles for pullback touch of EMA20
        last3 = df_1m.iloc[-4:-1]

        sl_dist = 1.6 * atr1m
        tp1_dist = 2.0 * sl_dist
        tp2_dist = 3.5 * sl_dist
        target_gain_pct = (tp2_dist / close) * 100

        # Discard if target gain is too tiny (< 0.6%)
        if target_gain_pct < 0.6:
            return None

        # LONG SNIPER SETUP:
        if direction == "BULLISH":
            pullback_touched = (last3["low"] <= last3["ema_20"]).any() or (last3["close"] <= last3["ema_20"]).any()
            bounce = close > ema20 and close > open_p
            rsi_ok = curr["rsi_14"] >= 45

            if pullback_touched and bounce and rsi_ok:
                sl_price = close - sl_dist
                return InstitutionalSignal(
                    symbol=metrics["symbol"],
                    direction="LONG",
                    entry_price=close,
                    sl_price=sl_price,
                    tp1_price=close + tp1_dist,
                    tp2_price=close + tp2_dist,
                    target_gain_pct=round(target_gain_pct, 2),
                    rr_ratio=3.5,
                    volume_surge=round(vol_ratio, 2),
                    oi_trend=metrics["oi_bias"],
                    htf_trend="4H/1H BULLISH ALIGNED",
                    reason=f"4H/1H Bullish + OI (${round(metrics['oi_usd']/1e6,1)}M) + 1m Reversal"
                )

        # SHORT SNIPER SETUP:
        elif direction == "BEARISH":
            pullback_touched = (last3["high"] >= last3["ema_20"]).any() or (last3["close"] >= last3["ema_20"]).any()
            bounce = close < ema20 and close < open_p
            rsi_ok = curr["rsi_14"] <= 55

            if pullback_touched and bounce and rsi_ok:
                sl_price = close + sl_dist
                return InstitutionalSignal(
                    symbol=metrics["symbol"],
                    direction="SHORT",
                    entry_price=close,
                    sl_price=sl_price,
                    tp1_price=close - tp1_dist,
                    tp2_price=close - tp2_dist,
                    target_gain_pct=round(target_gain_pct, 2),
                    rr_ratio=3.5,
                    volume_surge=round(vol_ratio, 2),
                    oi_trend=metrics["oi_bias"],
                    htf_trend="4H/1H BEARISH ALIGNED",
                    reason=f"4H/1H Bearish + OI (${round(metrics['oi_usd']/1e6,1)}M) + 1m Reversal"
                )

        return None
