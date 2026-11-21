"""
T.R Technology — Multi-Timeframe (MTF) Confluence Engine
Analyzes 8 Timeframes: 1M, 1W, 1D, 4H, 1H, 30M, 15M, 5M
Entry Trigger: 5m / 15m closed candles only when Macro & Micro are in full confluence.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from enum import Enum

from indicators import compute_all_indicators


class Bias(Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class TimeframeAnalysis:
    tf: str
    close: float
    ema20: float
    ema50: float
    ema200: float
    rsi14: float
    adx14: float
    atr14: float
    bias: Bias
    score: float  # -1.0 (max bearish) to +1.0 (max bullish)


@dataclass
class MTFConfluenceReport:
    symbol: str
    macro_score: float     # 1M, 1W, 1D combined (-1.0 to +1.0)
    mid_score: float       # 4H, 1H, 30M combined
    micro_score: float     # 15M, 5M combined
    total_confluence: float # weighted total score (-100% to +100%)
    overall_bias: Bias
    allowed_direction: Optional[str]  # "LONG", "SHORT", or None
    tf_details: Dict[str, TimeframeAnalysis]
    reasons: list


class MTFConfluenceAnalyzer:
    """
    Evaluates 8 timeframes:
    - Macro: 1M, 1W, 1D (Weight: 40%) - Sets the master direction
    - Intermediate: 4H, 1H, 30M (Weight: 35%) - Confirms trend continuation
    - Micro Trigger: 15M, 5M (Weight: 25%) - Precise low-risk entry
    """

    TIMEFRAMES = ["1M", "1w", "1d", "4h", "1h", "15m", "5m", "1m"]

    # Weight distribution across horizons
    TF_WEIGHTS = {
        "1M": 0.10,
        "1w": 0.15,
        "1d": 0.15,
        "4h": 0.15,
        "1h": 0.12,
        "15m": 0.15,
        "5m": 0.10,
        "1m": 0.08
    }

    def analyze_single_tf(self, df: pd.DataFrame, tf: str) -> TimeframeAnalysis:
        """Analyze trend, momentum, and strength for a single timeframe."""
        if len(df) < 50:
            row = df.iloc[-1]
            return TimeframeAnalysis(
                tf=tf, close=row["close"], ema20=row["close"],
                ema50=row["close"], ema200=row["close"],
                rsi14=50.0, adx14=20.0, atr14=0.0,
                bias=Bias.NEUTRAL, score=0.0
            )

        row = df.iloc[-1]
        close = row["close"]
        ema20 = row.get("ema_20", close)
        ema50 = row.get("ema_50", close)
        ema200 = row.get("ema_200", close)
        rsi = row.get("rsi_14", 50.0)
        adx = row.get("adx_14", 20.0)
        atr = row.get("atr_14", 0.0)

        # Scoring components:
        score = 0.0

        # 1. EMA Alignment (40% of score)
        if close > ema20 > ema50:
            score += 0.35
            if not pd.isna(ema200) and close > ema200:
                score += 0.15
        elif close < ema20 < ema50:
            score -= 0.35
            if not pd.isna(ema200) and close < ema200:
                score -= 0.15

        # 2. RSI Momentum (30% of score)
        if rsi > 55:
            score += 0.25 if rsi < 75 else 0.10  # overbought slight caution
        elif rsi < 45:
            score -= 0.25 if rsi > 25 else -0.10  # oversold slight caution

        # 3. ADX Trend Strength Multiplier (20% of score)
        if adx >= 25:
            # Strong trend accelerates the existing direction
            score *= 1.2
        elif adx < 18:
            # Weak sideways dampens score
            score *= 0.7

        # Clip between -1.0 and +1.0
        score = max(-1.0, min(1.0, score))

        # Classify bias
        if score >= 0.5:
            bias = Bias.STRONG_BULLISH
        elif score >= 0.2:
            bias = Bias.BULLISH
        elif score <= -0.5:
            bias = Bias.STRONG_BEARISH
        elif score <= -0.2:
            bias = Bias.BEARISH
        else:
            bias = Bias.NEUTRAL

        return TimeframeAnalysis(
            tf=tf, close=close, ema20=ema20,
            ema50=ema50, ema200=ema200,
            rsi14=rsi, adx14=adx, atr14=atr,
            bias=bias, score=round(score, 3)
        )

    def evaluate_confluence(self, symbol: str, tf_data: Dict[str, pd.DataFrame]) -> MTFConfluenceReport:
        """
        Evaluate full MTF matrix across all 8 timeframes.
        Returns detailed report and trading clearance.
        """
        analyses = {}
        weighted_score = 0.0
        total_weight = 0.0

        macro_score = 0.0
        macro_weight = 0.0

        mid_score = 0.0
        mid_weight = 0.0

        micro_score = 0.0
        micro_weight = 0.0

        for tf, df in tf_data.items():
            if df is None or len(df) == 0:
                continue

            analysis = self.analyze_single_tf(df, tf)
            analyses[tf] = analysis
            w = self.TF_WEIGHTS.get(tf, 0.10)
            weighted_score += analysis.score * w
            total_weight += w

            # Group into Macro, Mid, Micro
            if tf in ["1M", "1w", "1d"]:
                macro_score += analysis.score * w
                macro_weight += w
            elif tf in ["4h", "1h"]:
                mid_score += analysis.score * w
                mid_weight += w
            elif tf in ["15m", "5m", "1m"]:
                micro_score += analysis.score * w
                micro_weight += w

        macro_norm = macro_score / macro_weight if macro_weight > 0 else 0.0
        mid_norm = mid_score / mid_weight if mid_weight > 0 else 0.0
        micro_norm = micro_score / micro_weight if micro_weight > 0 else 0.0
        final_confluence = (weighted_score / total_weight) * 100 if total_weight > 0 else 0.0

        # Confluence Rules:
        # Long allowed ONLY if Macro > 0 AND Mid > 0 AND Total Confluence >= +40%
        # Short allowed ONLY if Macro < 0 AND Mid < 0 AND Total Confluence <= -40%
        allowed = None
        reasons = []

        if final_confluence >= 40.0:
            if macro_norm >= 0.15 and mid_norm >= 0.15:
                allowed = "LONG"
                reasons.append(f"Full Bullish Confluence (+{final_confluence:.1f}%). Macro & Mid aligned.")
            else:
                reasons.append(f"Bullish score (+{final_confluence:.1f}%), but Macro/Mid divergence.")
        elif final_confluence <= -40.0:
            if macro_norm <= -0.15 and mid_norm <= -0.15:
                allowed = "SHORT"
                reasons.append(f"Full Bearish Confluence ({final_confluence:.1f}%). Macro & Mid aligned.")
            else:
                reasons.append(f"Bearish score ({final_confluence:.1f}%), but Macro/Mid divergence.")
        else:
            reasons.append(f"Neutral / Choppy Confluence ({final_confluence:.1f}%). No trade.")

        if final_confluence >= 50:
            ob = Bias.STRONG_BULLISH
        elif final_confluence >= 25:
            ob = Bias.BULLISH
        elif final_confluence <= -50:
            ob = Bias.STRONG_BEARISH
        elif final_confluence <= -25:
            ob = Bias.BEARISH
        else:
            ob = Bias.NEUTRAL

        return MTFConfluenceReport(
            symbol=symbol,
            macro_score=round(macro_norm, 3),
            mid_score=round(mid_norm, 3),
            micro_score=round(micro_norm, 3),
            total_confluence=round(final_confluence, 1),
            overall_bias=ob,
            allowed_direction=allowed,
            tf_details=analyses,
            reasons=reasons
        )

    def check_micro_entry_trigger(self, df_trigger: pd.DataFrame, direction: str,
                                 trigger_name: str = "1m", sl_atr_mult: float = 1.8) -> Optional[dict]:
        """
        Check for precision trigger on 1m, 5m, or 15m closed candle.
        Long: Pullback to EMA20 + Bullish bounce close + RSI >= 45
        Short: Pullback to EMA20 + Bearish bounce close + RSI <= 55
        """
        if len(df_trigger) < 3:
            return None

        curr = df_trigger.iloc[-1]
        prev = df_trigger.iloc[-2]

        close = curr["close"]
        open_p = curr["open"]
        ema20 = curr["ema_20"]
        atr = curr["atr_14"]
        rsi = curr["rsi_14"]

        if pd.isna(ema20) or pd.isna(atr) or atr <= 0:
            return None

        sl_dist = sl_atr_mult * atr

        if direction == "LONG":
            pullback = prev["low"] <= prev["ema_20"] or prev["close"] <= prev["ema_20"]
            bounce = close > ema20 and close > open_p
            rsi_ok = rsi >= 45.0
            if pullback and bounce and rsi_ok:
                return {
                    "direction": "LONG",
                    "entry_price": close,
                    "sl_price": close - sl_dist,
                    "tp1_price": close + 1.5 * sl_dist,
                    "tp2_price": close + 2.5 * sl_dist,
                    "atr": atr,
                    "trigger_tf": trigger_name
                }

        elif direction == "SHORT":
            pullback = prev["high"] >= prev["ema_20"] or prev["close"] >= prev["ema_20"]
            bounce = close < ema20 and close < open_p
            rsi_ok = rsi <= 55.0
            if pullback and bounce and rsi_ok:
                return {
                    "direction": "SHORT",
                    "entry_price": close,
                    "sl_price": close + sl_dist,
                    "tp1_price": close - 1.5 * sl_dist,
                    "tp2_price": close - 2.5 * sl_dist,
                    "atr": atr,
                    "trigger_tf": trigger_name
                }

        return None
