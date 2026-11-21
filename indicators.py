"""
T.R Technology — Technical Indicator Calculations
Only the indicators specified in the rule file.
"""
import numpy as np
import pandas as pd


def ema(series, period):
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def atr(df, period=14):
    """Average True Range (Wilder's smoothing)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    alpha = 1.0 / period
    return tr.ewm(alpha=alpha, adjust=False).mean()


def adx(df, period=14):
    """Average Directional Index (Wilder's smoothing)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index
    )

    alpha = 1.0 / period
    atr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    return dx.ewm(alpha=alpha, adjust=False).mean()


def bollinger_bands(df, period=20, std_dev=2.0):
    """Bollinger Bands. Returns (upper, middle, lower)."""
    middle = sma(df["close"], period)
    std = df["close"].rolling(window=period).std()
    return middle + std_dev * std, middle, middle - std_dev * std


def rsi(series, period=14):
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss
    rs = rs.replace([np.inf, -np.inf], 100.0)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_all_indicators(df):
    """Add all indicator columns to a candle DataFrame."""
    df = df.copy()
    df["ema_20"]  = ema(df["close"], 20)
    df["ema_50"]  = ema(df["close"], 50)
    df["ema_200"] = ema(df["close"], 200)
    df["adx_14"]  = adx(df, 14)
    df["atr_14"]  = atr(df, 14)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(df, 20, 2.0)
    df["rsi_14"]  = rsi(df["close"], 14)
    return df
