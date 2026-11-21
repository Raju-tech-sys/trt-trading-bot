"""
T.R Technology — Full Universe Breakout & Breakdown Scanner
Scans all Binance Futures USDT pairs (> $10M volume) for:
- Top 24h Gainers & Losers
- Volatility Squeeze (Tightest consolidation boxes)
- Institutional Breakout & Breakdown candidates with volume surge & wick filters
"""
import time
import requests
import pandas as pd
from typing import List, Dict, Optional

class UniverseScanner:
    def __init__(self, min_volume_usd: float = 10_000_000, testnet: bool = True):
        self.min_volume_usd = min_volume_usd
        self.testnet = testnet
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-Universe-Scanner-v8.0"})
        self.testnet_symbols = set()
        self.last_testnet_refresh = 0
        self._refresh_testnet_symbols()

    def _refresh_testnet_symbols(self):
        now = time.time()
        if now - self.last_testnet_refresh > 3600 or not self.testnet_symbols:
            try:
                base = "https://testnet.binancefuture.com" if self.testnet else "https://fapi.binance.com"
                r = self.session.get(f"{base}/fapi/v1/exchangeInfo", timeout=8).json()
                self.testnet_symbols = {
                    s["symbol"] for s in r.get("symbols", [])
                    if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
                }
                self.last_testnet_refresh = now
            except Exception as e:
                print(f"[SCANNER] Error refreshing exchangeInfo: {e}")

    def fetch_market_overview(self) -> Dict:
        """Fetch 24hr tickers for all pairs from Binance mainnet (for real volume/momentum)."""
        self._refresh_testnet_symbols()
        try:
            r = self.session.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10).json()
            if not isinstance(r, list):
                return {"gainers": [], "losers": [], "liquid_universe": []}

            eligible = []
            for item in r:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                vol = float(item.get("quoteVolume", 0))
                if vol < self.min_volume_usd:
                    continue
                # If in testnet mode, symbol must be tradable on testnet
                if self.testnet and sym not in self.testnet_symbols:
                    continue

                eligible.append({
                    "symbol": sym,
                    "change": round(float(item.get("priceChangePercent", 0)), 2),
                    "volume_usd": vol,
                    "price": float(item.get("lastPrice", 0)),
                    "high": float(item.get("highPrice", 0)),
                    "low": float(item.get("lowPrice", 0)),
                })

            eligible.sort(key=lambda x: x["change"], reverse=True)
            gainers = eligible[:10]
            losers = list(reversed(eligible[-10:]))

            # Liquid universe sorted by 24h volume
            by_vol = sorted(eligible, key=lambda x: x["volume_usd"], reverse=True)

            return {
                "gainers": gainers,
                "losers": losers,
                "liquid_universe": by_vol,
                "total_eligible": len(eligible)
            }
        except Exception as e:
            print(f"[SCANNER] Market overview fetch failed: {e}")
            return {"gainers": [], "losers": [], "liquid_universe": [], "total_eligible": 0}

    def analyze_breakout_potential(self, symbol: str) -> Optional[Dict]:
        """Deep analysis of a single coin on 15m timeframe for institutional breakout/breakdown."""
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=30"
            r = self.session.get(url, timeout=4).json()
            if not isinstance(r, list) or len(r) < 25:
                return None

            df = pd.DataFrame(r, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)

            # Prior 16 candles box (4 hours of consolidation)
            prior = df.iloc[-17:-1]
            box_high = prior["high"].max()
            box_low = prior["low"].min()
            box_range = box_high - box_low
            mid = (box_high + box_low) / 2.0
            if mid <= 0:
                return None

            box_pct = (box_range / mid) * 100.0

            curr = df.iloc[-1]
            close = curr["close"]
            open_p = curr["open"]
            high = curr["high"]
            low = curr["low"]
            rng = high - low
            body = abs(close - open_p)
            disp = (body / rng) if rng > 0 else 0.0

            # Volume surge vs past 20 candles
            avg_vol = df.iloc[-21:-1]["volume"].mean()
            vol_surge = (curr["volume"] / avg_vol) if avg_vol > 0 else 1.0

            # Wick rejection check
            upper_wick = high - max(close, open_p)
            lower_wick = min(close, open_p) - low
            upper_wick_ratio = upper_wick / rng if rng > 0 else 1.0
            lower_wick_ratio = lower_wick / rng if rng > 0 else 1.0

            # Multi-timeframe trend check on 1H
            # Fetch 1H klines
            url_1h = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=25"
            r_1h = self.session.get(url_1h, timeout=4).json()
            htf_bias = "NEUTRAL"
            if isinstance(r_1h, list) and len(r_1h) >= 20:
                closes_1h = [float(x[4]) for x in r_1h]
                ema20_1h = pd.Series(closes_1h).ewm(span=20, adjust=False).mean().iloc[-1]
                if closes_1h[-1] > ema20_1h:
                    htf_bias = "BULLISH"
                elif closes_1h[-1] < ema20_1h:
                    htf_bias = "BEARISH"

            # 1. Bullish Breakout Criteria:
            # - Tight box (<= 3.8%)
            # - Close above box_high
            # - Solid displacement body (>= 55%)
            # - Institutional volume surge (>= 1.35x)
            # - Small upper wick (< 28%)
            # - 1H structure not opposing (BULLISH or NEUTRAL)
            is_bullish = (
                close > box_high and
                close > open_p and
                box_pct <= 3.8 and
                disp >= 0.55 and
                vol_surge >= 1.35 and
                upper_wick_ratio < 0.28 and
                htf_bias != "BEARISH"
            )

            # 2. Bearish Breakdown Criteria:
            # - Tight box (<= 3.8%)
            # - Close below box_low
            # - Solid displacement body (>= 55%)
            # - Institutional volume surge (>= 1.35x)
            # - Small lower wick (< 28%)
            # - 1H structure not opposing (BEARISH or NEUTRAL)
            is_bearish = (
                close < box_low and
                close < open_p and
                box_pct <= 3.8 and
                disp >= 0.55 and
                vol_surge >= 1.35 and
                lower_wick_ratio < 0.28 and
                htf_bias != "BULLISH"
            )

            dist_to_high = round(float(((box_high - close) / close) * 100.0), 2) if close > 0 else 0.0
            dist_to_low = round(float(((close - box_low) / close) * 100.0), 2) if close > 0 else 0.0

            return {
                "symbol": symbol,
                "price": float(close),
                "box_high": float(box_high),
                "box_low": float(box_low),
                "box_pct": round(float(box_pct), 2),
                "dist_to_high_pct": dist_to_high,
                "dist_to_low_pct": dist_to_low,
                "vol_surge": round(float(vol_surge), 2),
                "disp_pct": round(float(disp * 100), 1),
                "upper_wick_ratio": round(float(upper_wick_ratio), 2),
                "lower_wick_ratio": round(float(lower_wick_ratio), 2),
                "htf_bias": str(htf_bias),
                "is_bullish": bool(is_bullish),
                "is_bearish": bool(is_bearish),
                "score": round(float(vol_surge * (disp / 0.5) * (1.0 if box_pct <= 3.0 else 0.8)), 2)
            }
        except Exception:
            return None

    def scan_top_candidates(self, max_candidates: int = 30) -> Dict:
        """Scan top liquid coins + top movers to find actionable breakout candidates."""
        overview = self.fetch_market_overview()
        liquid = overview.get("liquid_universe", [])
        gainers = overview.get("gainers", [])
        losers = overview.get("losers", [])

        # Priority set: Top volume + Top gainers + Top losers
        pool_symbols = []
        for g in gainers[:6]:
            pool_symbols.append(g["symbol"])
        for l in losers[:6]:
            pool_symbols.append(l["symbol"])
        for item in liquid[:25]:
            if item["symbol"] not in pool_symbols:
                pool_symbols.append(item["symbol"])

        pool_symbols = pool_symbols[:max_candidates]

        breakout_signals = []
        squeezes = []

        for sym in pool_symbols:
            res = self.analyze_breakout_potential(sym)
            if res:
                if res["is_bullish"] or res["is_bearish"]:
                    breakout_signals.append(res)
                elif res["box_pct"] <= 3.2:
                    squeezes.append(res)
            time.sleep(0.04)  # Prevent rate limits

        breakout_signals.sort(key=lambda x: x["score"], reverse=True)
        squeezes.sort(key=lambda x: x["box_pct"])

        return {
            "overview": overview,
            "breakout_signals": breakout_signals,
            "squeezes": squeezes[:10],
            "scanned_count": len(pool_symbols)
        }
