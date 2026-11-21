"""
T.R Technology — Regime Detection
ADX-based regime switch with hysteresis on the 1h timeframe.
"""
import pandas as pd
from enum import Enum


class Regime(Enum):
    TREND = "TREND"          # ADX >= 25 → Module A
    SIDEWAYS = "SIDEWAYS"    # ADX < 20  → Module B
    NO_TRADE = "NO_TRADE"    # 20 <= ADX < 25


def classify_regime_raw(adx_value, adx_trend_th=25, adx_sideways_th=20):
    """Classify regime from a single ADX reading (no hysteresis)."""
    if adx_value >= adx_trend_th:
        return Regime.TREND
    elif adx_value < adx_sideways_th:
        return Regime.SIDEWAYS
    else:
        return Regime.NO_TRADE


def compute_regime_series(df_1h, hysteresis_hours=4,
                          adx_trend_th=25, adx_sideways_th=20):
    """
    Compute regime for each 1h candle with hysteresis.
    Regime only switches if the new regime holds for >= hysteresis_hours
    consecutive 1h candles.
    """
    adx_values = df_1h["adx_14"].values
    n = len(adx_values)

    raw = [classify_regime_raw(v, adx_trend_th, adx_sideways_th) for v in adx_values]

    confirmed = [Regime.NO_TRADE] * n
    time_index = pd.DatetimeIndex(df_1h["open_time"])
    if n == 0:
        return pd.Series(confirmed, index=time_index)

    current = raw[0]
    pending = None
    pending_count = 0

    for i in range(n):
        r = raw[i]
        if r == current:
            pending, pending_count = None, 0
            confirmed[i] = current
        elif r == pending:
            pending_count += 1
            if pending_count >= hysteresis_hours:
                current = pending
                pending, pending_count = None, 0
            confirmed[i] = current
        else:
            pending, pending_count = r, 1
            confirmed[i] = current

    return pd.Series(confirmed, index=time_index)


def get_regime_at_time(regime_series, timestamp):
    """Fast lookup for regime active at a given timestamp."""
    idx = regime_series.index.searchsorted(timestamp, side="right") - 1
    if idx < 0:
        return Regime.NO_TRADE
    return regime_series.iloc[idx]
