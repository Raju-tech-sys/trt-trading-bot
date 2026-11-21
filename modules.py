"""
T.R Technology — Module A (Trend Pullback) & Module B (Range) Signal Logic
All signals on CLOSED 15m candles only.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Signal:
    """A trade entry signal."""
    module: str
    direction: Direction
    entry_price: float
    sl_price: float
    tp_prices: List[float]
    tp_close_pcts: List[float]
    risk_pct: float
    order_type: OrderType
    atr_at_entry: float
    adx_at_entry: float
    rsi_at_entry: float
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE A: TREND PULLBACK
# ═══════════════════════════════════════════════════════════════════════════════

class ModuleA:
    """
    Trend Pullback Module.
    Direction: 4h EMA50 vs EMA200.
    Entry: 15m pullback to EMA20, bullish/bearish bounce confirmed.
    SL: 1.5 ATR. TP: 1.5R (50% close, SL→BE) then 3R (remaining).
    """

    def __init__(self, config):
        self.sl_atr_mult = config.MOD_A_SL_ATR_MULT
        self.tp1_r = config.MOD_A_TP1_R
        self.tp2_r = config.MOD_A_TP2_R
        self.tp1_close = config.MOD_A_TP1_CLOSE
        self.risk_pct = config.MOD_A_RISK_PCT
        self.reentry_atr = config.MOD_A_REENTRY_ATR
        self.use_limit = getattr(config, "MOD_A_USE_LIMIT", False)
        self.rsi_filter = getattr(config, "MOD_A_RSI_FILTER", False)
        self._last_pullback_entry = {}  # coin → (price, atr)

    def reset(self):
        self._last_pullback_entry.clear()

    def get_direction_filter(self, df_4h, timestamp):
        """Check 4h EMA50 vs EMA200. Returns None if recent crossover."""
        idx = df_4h["open_time"].searchsorted(timestamp, side="right")
        if idx < 3:
            return None

        last3 = df_4h.iloc[idx - 3 : idx]
        ema50_now = last3["ema_50"].iloc[-1]
        ema200_now = last3["ema_200"].iloc[-1]

        # Check crossover in last 2 candles
        signs_prev = np.sign(
            last3["ema_50"].iloc[:-1].values - last3["ema_200"].iloc[:-1].values
        )
        sign_now = np.sign(ema50_now - ema200_now)

        if any(s != sign_now for s in signs_prev if s != 0):
            return None  # Recent crossover — no trade

        if ema50_now > ema200_now:
            return Direction.LONG
        elif ema50_now < ema200_now:
            return Direction.SHORT
        return None

    def _is_reentry(self, coin, price, atr_val):
        """Prevent duplicate entry on the same pullback."""
        if coin not in self._last_pullback_entry:
            return False
        last_p, last_a = self._last_pullback_entry[coin]
        return abs(price - last_p) < self.reentry_atr * last_a

    def check_signal(self, df_15m, df_4h, idx, coin):
        """Check for Module A entry at closed 15m candle index."""
        if idx < 2:
            return None

        row = df_15m.iloc[idx]
        prev = df_15m.iloc[idx - 1]
        timestamp = row["open_time"]

        direction = self.get_direction_filter(df_4h, timestamp)
        if direction is None:
            return None

        close = row["close"]
        ema20 = row["ema_20"]
        prev_close = prev["close"]
        prev_ema20 = prev["ema_20"]
        atr_val = row["atr_14"]
        adx_val = row.get("adx_14", 0)
        rsi_val = row["rsi_14"]

        if pd.isna(ema20) or pd.isna(atr_val) or atr_val <= 0:
            return None

        signal = None

        if direction == Direction.LONG:
            # RSI momentum filter for Long
            if self.rsi_filter and rsi_val <= 50:
                return None

            # Pullback: prev touched or went below EMA20
            pullback = prev_close <= prev_ema20 or prev["low"] <= prev_ema20
            # Bounce: bullish candle closes above EMA20
            bounce = close > ema20 and close > row["open"]

            if pullback and bounce and not self._is_reentry(coin, close, atr_val):
                sl_dist = self.sl_atr_mult * atr_val
                signal = Signal(
                    module="A",
                    direction=Direction.LONG,
                    entry_price=close,
                    sl_price=close - sl_dist,
                    tp_prices=[
                        close + self.tp1_r * sl_dist,
                        close + self.tp2_r * sl_dist
                    ],
                    tp_close_pcts=[self.tp1_close, 1.0],
                    risk_pct=self.risk_pct,
                    order_type=OrderType.LIMIT if self.use_limit else OrderType.MARKET,
                    atr_at_entry=atr_val,
                    adx_at_entry=adx_val,
                    rsi_at_entry=rsi_val,
                    reason="Trend pullback long: EMA20 bounce"
                )

        elif direction == Direction.SHORT:
            # RSI momentum filter for Short
            if self.rsi_filter and rsi_val >= 50:
                return None

            pullback = prev_close >= prev_ema20 or prev["high"] >= prev_ema20
            bounce = close < ema20 and close < row["open"]

            if pullback and bounce and not self._is_reentry(coin, close, atr_val):
                sl_dist = self.sl_atr_mult * atr_val
                signal = Signal(
                    module="A",
                    direction=Direction.SHORT,
                    entry_price=close,
                    sl_price=close + sl_dist,
                    tp_prices=[
                        close - self.tp1_r * sl_dist,
                        close - self.tp2_r * sl_dist
                    ],
                    tp_close_pcts=[self.tp1_close, 1.0],
                    risk_pct=self.risk_pct,
                    order_type=OrderType.LIMIT if self.use_limit else OrderType.MARKET,
                    atr_at_entry=atr_val,
                    adx_at_entry=adx_val,
                    rsi_at_entry=rsi_val,
                    reason="Trend pullback short: EMA20 bounce"
                )

        if signal:
            self._last_pullback_entry[coin] = (close, atr_val)

        return signal


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE B: RANGE
# ═══════════════════════════════════════════════════════════════════════════════

class ModuleB:
    """
    Range Module.
    Range detection: ADX(1h)<20, price in recent high/low, height >= 1.5 ATR.
    Entry: BB band touch + RSI extreme + confirming close.
    TP: Bollinger mid band. SL: 1 ATR beyond range boundary.
    """

    def __init__(self, config):
        self.range_candles = config.MOD_B_RANGE_CANDLES
        self.min_range_atr = config.MOD_B_MIN_RANGE_ATR
        self.rsi_oversold = config.MOD_B_RSI_OVERSOLD
        self.rsi_overbought = config.MOD_B_RSI_OVERBOUGHT
        self.sl_atr_mult = config.MOD_B_SL_ATR_MULT
        self.risk_pct = config.MOD_B_RISK_PCT
        self.range_break_atr = config.MOD_B_RANGE_BREAK_ATR
        self._range_high = None
        self._range_low = None
        self._range_valid = False

    def reset(self):
        self._range_high = self._range_low = None
        self._range_valid = False

    def _detect_range(self, df_15m, idx):
        """Detect if price is in a valid range."""
        if idx < self.range_candles:
            return False, 0.0, 0.0

        lookback = df_15m.iloc[idx - self.range_candles: idx + 1]
        rh = lookback["high"].max()
        rl = lookback["low"].min()
        atr_val = df_15m.iloc[idx]["atr_14"]

        if pd.isna(atr_val) or atr_val <= 0:
            return False, 0.0, 0.0
        # Range height must be >= 1.5 x ATR
        if rh - rl < self.min_range_atr * atr_val:
            return False, 0.0, 0.0
        # Price must be within range
        if df_15m.iloc[idx]["close"] > rh or df_15m.iloc[idx]["close"] < rl:
            return False, 0.0, 0.0

        return True, rh, rl

    def _check_range_break(self, df_15m, idx):
        """Check if range has been broken."""
        if not self._range_valid:
            return False
        row = df_15m.iloc[idx]
        atr_val = row["atr_14"]
        if pd.isna(atr_val):
            return False
        return (row["close"] > self._range_high + self.range_break_atr * atr_val or
                row["close"] < self._range_low - self.range_break_atr * atr_val)

    def check_signal(self, df_15m, idx, coin):
        """Check for Module B entry at closed 15m candle index."""
        if idx < self.range_candles + 1:
            return None

        # Check range break first
        if self._check_range_break(df_15m, idx):
            self._range_valid = False
            return None

        # Detect / update range
        is_range, rh, rl = self._detect_range(df_15m, idx)
        if not is_range:
            self._range_valid = False
            return None

        self._range_high = rh
        self._range_low = rl
        self._range_valid = True

        row = df_15m.iloc[idx]
        close = row["close"]
        open_p = row["open"]
        bb_lower = row["bb_lower"]
        bb_upper = row["bb_upper"]
        bb_mid = row["bb_mid"]
        rsi_val = row["rsi_14"]
        atr_val = row["atr_14"]
        adx_val = row.get("adx_14", 0)

        if any(pd.isna(v) for v in [bb_lower, bb_upper, bb_mid, rsi_val, atr_val]):
            return None

        # Long: price touches BB lower + RSI < 30 + bullish close
        if row["low"] <= bb_lower and rsi_val < self.rsi_oversold and close > open_p:
            sl = self._range_low - self.sl_atr_mult * atr_val
            if bb_mid <= close:
                return None  # TP must be above entry
            return Signal(
                module="B", direction=Direction.LONG,
                entry_price=close, sl_price=sl,
                tp_prices=[bb_mid], tp_close_pcts=[1.0],
                risk_pct=self.risk_pct, order_type=OrderType.LIMIT,
                atr_at_entry=atr_val, adx_at_entry=adx_val,
                rsi_at_entry=rsi_val,
                reason="Range long: BB lower + RSI oversold"
            )

        # Short: price touches BB upper + RSI > 70 + bearish close
        if row["high"] >= bb_upper and rsi_val > self.rsi_overbought and close < open_p:
            sl = self._range_high + self.sl_atr_mult * atr_val
            if bb_mid >= close:
                return None  # TP must be below entry
            return Signal(
                module="B", direction=Direction.SHORT,
                entry_price=close, sl_price=sl,
                tp_prices=[bb_mid], tp_close_pcts=[1.0],
                risk_pct=self.risk_pct, order_type=OrderType.LIMIT,
                atr_at_entry=atr_val, adx_at_entry=adx_val,
                rsi_at_entry=rsi_val,
                reason="Range short: BB upper + RSI overbought"
            )

        return None
