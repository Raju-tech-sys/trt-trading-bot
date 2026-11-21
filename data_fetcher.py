"""
T.R Technology — Historical Data Fetcher (Binance USDT-M Perpetual)
Downloads and caches OHLCV + funding rate data for backtesting.
"""
import os
import time
import requests
import pandas as pd


BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"{symbol}_{interval}.parquet")


def fetch_klines(symbol, interval, start_date, end_date, use_cache=True):
    """
    Fetch historical klines from Binance Futures.
    Downloads in batches of 1500, caches to parquet.
    """
    _ensure_cache_dir()
    cache_file = _cache_path(symbol, interval)

    if use_cache and os.path.exists(cache_file):
        df = pd.read_parquet(cache_file)
        start_ts = pd.Timestamp(start_date, tz="UTC")
        end_ts = pd.Timestamp(end_date, tz="UTC")
        if df["open_time"].min() <= start_ts and df["open_time"].max() >= end_ts - pd.Timedelta(days=1):
            mask = (df["open_time"] >= start_ts) & (df["open_time"] <= end_ts)
            print(f"  [Cache HIT] {symbol} {interval}: {mask.sum()} candles")
            return df[mask].reset_index(drop=True)
        print(f"  [Cache PARTIAL] {symbol} {interval}: fetching more data")

    start_ms = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_date, tz="UTC").timestamp() * 1000)

    all_data = []
    current_start = start_ms
    req_count = 0
    print(f"  Fetching {symbol} {interval} from {start_date} to {end_date}...")

    while current_start < end_ms:
        params = {
            "symbol": symbol, "interval": interval,
            "startTime": current_start, "endTime": end_ms, "limit": 1500
        }
        for attempt in range(5):
            try:
                resp = requests.get(BINANCE_FUTURES_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise RuntimeError(f"Failed to fetch {symbol} {interval}: {e}")
                time.sleep(2 ** attempt)

        if not data:
            break

        all_data.extend(data)
        current_start = data[-1][6] + 1  # close_time + 1ms
        req_count += 1

        if req_count % 10 == 0:
            time.sleep(1)
            print(f"    ... {len(all_data)} candles so far")

    if not all_data:
        raise ValueError(f"No data returned for {symbol} {interval}")

    df = pd.DataFrame(all_data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])

    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]].copy()
    df = df.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)

    df.to_parquet(cache_file, index=False)
    print(f"  [DONE] {symbol} {interval}: {len(df)} candles cached")
    return df


def fetch_funding_rates(symbol, start_date, end_date, use_cache=True):
    """Fetch historical funding rates from Binance Futures."""
    _ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_funding.parquet")

    if use_cache and os.path.exists(cache_file):
        df = pd.read_parquet(cache_file)
        start_ts = pd.Timestamp(start_date, tz="UTC")
        end_ts = pd.Timestamp(end_date, tz="UTC")
        if not df.empty and df["time"].min() <= start_ts:
            mask = (df["time"] >= start_ts) & (df["time"] <= end_ts)
            print(f"  [Cache HIT] {symbol} funding: {mask.sum()} records")
            return df[mask].reset_index(drop=True)

    start_ms = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_date, tz="UTC").timestamp() * 1000)

    all_data = []
    current_start = start_ms
    print(f"  Fetching {symbol} funding rates...")

    while current_start < end_ms:
        params = {
            "symbol": symbol, "startTime": current_start,
            "endTime": end_ms, "limit": 1000
        }
        for attempt in range(5):
            try:
                resp = requests.get(BINANCE_FUNDING_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise RuntimeError(f"Failed to fetch funding: {e}")
                time.sleep(2 ** attempt)

        if not data:
            break

        all_data.extend(data)
        current_start = data[-1]["fundingTime"] + 1

    if not all_data:
        print(f"  [WARN] No funding data for {symbol}")
        return pd.DataFrame(columns=["time", "funding_rate"])

    df = pd.DataFrame(all_data)
    df["time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df = df[["time", "funding_rate"]].drop_duplicates(subset="time") \
        .sort_values("time").reset_index(drop=True)

    df.to_parquet(cache_file, index=False)
    print(f"  [DONE] {symbol} funding: {len(df)} records")
    return df


def load_all_data(symbols, start_date, end_date):
    """Load all required data for backtesting (15m, 1h, 4h, funding)."""
    data = {}
    for sym in symbols:
        print(f"\nLoading data for {sym}:")
        data[sym] = {
            "15m": fetch_klines(sym, "15m", start_date, end_date),
            "1h":  fetch_klines(sym, "1h",  start_date, end_date),
            "4h":  fetch_klines(sym, "4h",  start_date, end_date),
            "funding": fetch_funding_rates(sym, start_date, end_date),
        }
    return data
