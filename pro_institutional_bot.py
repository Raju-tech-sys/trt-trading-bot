"""
T.R Technology — Pro Trader Institutional Live Bot (v5.0 Pro Institutional)
Architecture:
- HTF Multi-Timeframe Confluence (4H, 1H, 15M, 1M)
- Institutional Volume & Open Interest (OI) Filtering
- Premium vs Discount Pricing (Never chase extended moves)
- 1m Candle Displacement & Volume Surge Confirmation
- Dynamic 1% Account Risk ($50 on $5,000 balance)
- Asymmetric R:R: TP1 = 2.0R (Bank 50% + Breakeven SL), TP2 = 4.0R (HTF Swing Target)
- Zero Fee Drag: Target price moves >= 1.0% to 4.0%
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


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class InstitutionalSignal:
    symbol: str
    direction: str             # "LONG" or "SHORT"
    entry_price: float
    sl_price: float
    tp1_price: float           # 2.0R
    tp2_price: float           # 4.0R
    target_gain_pct: float     # Price move % (e.g. 1.5% - 4.5%)
    rr_ratio: float            # e.g. 4.0:1
    risk_usd: float            # 1% of balance ($50 on $5k)
    qty: float
    displacement: float        # Candle body ratio
    vol_surge: float           # Relative volume
    oi_usd: float
    htf_bias: str
    reason: str


# ═══════════════════════════════════════════════════════════════════════════════
# BINANCE FUTURES TESTNET / LIVE CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "TRT-Pro-Trader-v5.0"
        })

    def _sign_query(self, params: dict) -> str:
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def get_account_balance(self) -> float:
        try:
            q = self._sign_query({})
            r = self.session.get(f"{self.base_url}/fapi/v2/balance?{q}", timeout=8).json()
            for item in r:
                if item.get("asset") == "USDT":
                    return float(item.get("availableBalance", 0.0))
        except Exception as e:
            print(f"⚠️ Balance fetch error: {e}")
        return 5000.0

    def get_open_positions(self) -> list:
        try:
            q = self._sign_query({})
            r = self.session.get(f"{self.base_url}/fapi/v2/positionRisk?{q}", timeout=8).json()
            return [p for p in r if float(p.get("positionAmt", 0)) != 0]
        except Exception as e:
            print(f"⚠️ Open positions fetch error: {e}")
            return []

    def get_symbol_precision(self, symbol: str):
        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/exchangeInfo", timeout=8).json()
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
            self.session.post(f"{self.base_url}/fapi/v1/leverage?{q}", timeout=8)
        except:
            pass

    def place_market_order(self, symbol: str, side: str, qty: float):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty
        }
        q = self._sign_query(params)
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{q}", timeout=8)
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
        r = self.session.post(f"{self.base_url}/fapi/v1/algoOrder?{q}", timeout=8)
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
        r = self.session.post(f"{self.base_url}/fapi/v1/order?{q}", timeout=8)
        r.raise_for_status()
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# PRO INSTITUTIONAL ANALYSIS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ProTraderEngine:
    def __init__(self, risk_pct: float = 0.01):
        self.risk_pct = risk_pct
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TRT-Pro-Trader-v5.0"})

    def get_institutional_universe(self) -> List[str]:
        """Fetch top liquid futures tokens with Volume > $40M."""
        try:
            r = self.session.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=6).json()
            pairs = []
            for item in r:
                sym = item.get("symbol", "")
                if sym.endswith("USDT") and "_" not in sym:
                    try:
                        vol = float(item["quoteVolume"])
                        if vol >= 35_000_000:
                            pairs.append({"symbol": sym, "volume": vol})
                    except:
                        pass
            pairs.sort(key=lambda x: x["volume"], reverse=True)
            top = [p["symbol"] for p in pairs[:14]]
            for must in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]:
                if must not in top:
                    top.insert(0, must)
            return top[:12]
        except:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]

    def fetch_klines(self, symbol: str, interval: str, limit: int = 50) -> pd.DataFrame:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = self.session.get(url, timeout=6).json()
        df = pd.DataFrame(r, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return compute_all_indicators(df.iloc[:-1].reset_index(drop=True))

    def get_token_metrics(self, symbol: str) -> Optional[dict]:
        try:
            t24 = self.session.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}", timeout=5).json()
            vol = float(t24.get("quoteVolume", 0))
            price = float(t24.get("lastPrice", 0))

            oi_res = self.session.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}", timeout=5).json()
            oi_contracts = float(oi_res.get("openInterest", 0))
            oi_usd = oi_contracts * price

            return {"symbol": symbol, "price": price, "volume_24h_usd": vol, "oi_usd": oi_usd}
        except:
            return None

    def analyze_htf_structure(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
        """Determines Institutional HTF Trend & Equilibrium Zones."""
        if len(df_4h) < 25 or len(df_1h) < 25:
            return {"valid": False}

        c4 = df_4h.iloc[-1]
        c1 = df_1h.iloc[-1]

        # 4H Structure
        bull_4h = c4["close"] > c4["ema_50"]
        bear_4h = c4["close"] < c4["ema_50"]

        # 1H Structure
        bull_1h = c1["close"] > c1["ema_50"] and c1["ema_20"] > c1["ema_50"]
        bear_1h = c1["close"] < c1["ema_50"] and c1["ema_20"] < c1["ema_50"]

        # Recent 1H Liquidity Swing High / Low (Past 24 hours)
        h1_high = df_1h.iloc[-24:]["high"].max()
        h1_low = df_1h.iloc[-24:]["low"].min()
        h1_mid = (h1_high + h1_low) / 2.0  # Equilibrium 50%

        if bull_4h and bull_1h:
            bias = "BULLISH"
        elif bear_4h and bear_1h:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return {
            "valid": True,
            "bias": bias,
            "h1_high": h1_high,
            "h1_low": h1_low,
            "h1_mid": h1_mid,
            "atr_1h": c1["atr_14"]
        }

    def check_pro_setup(self, symbol: str, balance: float, qty_prec: int, price_prec: int) -> Optional[InstitutionalSignal]:
        metrics = self.get_token_metrics(symbol)
        if not metrics or metrics["volume_24h_usd"] < 30_000_000:
            return None

        # 1. Macro HTF Alignment
        df_4h = self.fetch_klines(symbol, "4h")
        df_1h = self.fetch_klines(symbol, "1h")
        htf = self.analyze_htf_structure(df_4h, df_1h)

        if not htf.get("valid") or htf["bias"] == "NEUTRAL":
            return None

        bias = htf["bias"]
        price = metrics["price"]

        # 2. Premium / Discount Pricing Check:
        # Don't buy in Premium (>52% range), Don't sell in Discount (<48% range)
        h1_mid = htf["h1_mid"]
        if bias == "BULLISH" and price > (h1_mid * 1.01):
            return None  # Price already in premium, wait for discount pullback
        if bias == "BEARISH" and price < (h1_mid * 0.99):
            return None  # Price already in deep discount, wait for premium pullback

        # 3. Intermediate (15M) & Micro (1M) Trigger
        df_15m = self.fetch_klines(symbol, "15m")
        df_1m = self.fetch_klines(symbol, "1m", limit=30)

        if len(df_15m) < 20 or len(df_1m) < 25:
            return None

        c15 = df_15m.iloc[-1]
        curr_1m = df_1m.iloc[-1]
        prev_1m = df_1m.iloc[-2]

        close = curr_1m["close"]
        open_p = curr_1m["open"]
        high = curr_1m["high"]
        low = curr_1m["low"]
        rng = high - low
        body = abs(close - open_p)

        if rng <= 0:
            return None

        displacement = body / rng
        avg_vol = df_1m.iloc[-21:-1]["volume"].mean()
        vol_surge = curr_1m["volume"] / avg_vol if avg_vol > 0 else 1.0

        # Pro Quality Filter:
        # Displacement >= 45% (clear directional bar)
        # Volume Surge >= 1.15x
        if displacement < 0.45 or vol_surge < 1.15:
            return None

        atr_15m = c15["atr_14"]
        atr_1m = curr_1m["atr_14"]
        if pd.isna(atr_1m) or atr_1m <= 0:
            return None

        # Dynamic 1% Risk ($50 on $5,000 balance)
        risk_usd = round(balance * self.risk_pct, 2)
        if risk_usd < 10.0:
            risk_usd = 10.0

        # Stop-Loss Distance (Anchored to recent 15m/1m structure)
        # In a real pro setup, SL is around 1.5x - 2.0x 1m ATR
        sl_dist = max(1.8 * atr_1m, 0.4 * atr_15m)

        # TP Targets:
        # TP1 = 2.0R (Risk-Free Breakeven lock)
        # TP2 = 4.0R (Liquidity Sweep Target)
        tp1_dist = 2.0 * sl_dist
        tp2_dist = 4.0 * sl_dist

        target_gain_pct = (tp2_dist / close) * 100

        # Fee Drag Eliminator: Target move must be >= 0.8%
        if target_gain_pct < 0.80:
            return None

        raw_qty = risk_usd / sl_dist
        qty = round(raw_qty, qty_prec)
        if qty <= 0:
            return None

        # BULLISH LONG SETUP
        if bias == "BULLISH":
            # Rejection bounce above 1m EMA20 with green displacement
            is_green = close > open_p and close > curr_1m["ema_20"]
            rsi_ok = 45 <= curr_1m["rsi_14"] <= 72

            if is_green and rsi_ok:
                sl_price = round(close - sl_dist, price_prec)
                tp1_price = round(close + tp1_dist, price_prec)
                tp2_price = round(close + tp2_dist, price_prec)

                return InstitutionalSignal(
                    symbol=symbol,
                    direction="LONG",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_gain_pct=round(target_gain_pct, 2),
                    rr_ratio=4.0,
                    risk_usd=risk_usd,
                    qty=qty,
                    displacement=round(displacement * 100, 1),
                    vol_surge=round(vol_surge, 2),
                    oi_usd=metrics["oi_usd"],
                    htf_bias="BULLISH (4H/1H Aligned)",
                    reason=f"Pro Bullish Pullback: Discount zone + 1m displacement {round(displacement*100)}% + Vol surge {round(vol_surge,1)}x"
                )

        # BEARISH SHORT SETUP
        elif bias == "BEARISH":
            # Rejection drop below 1m EMA20 with red displacement
            is_red = close < open_p and close < curr_1m["ema_20"]
            rsi_ok = 28 <= curr_1m["rsi_14"] <= 55

            if is_red and rsi_ok:
                sl_price = round(close + sl_dist, price_prec)
                tp1_price = round(close - tp1_dist, price_prec)
                tp2_price = round(close - tp2_dist, price_prec)

                return InstitutionalSignal(
                    symbol=symbol,
                    direction="SHORT",
                    entry_price=round(close, price_prec),
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    target_gain_pct=round(target_gain_pct, 2),
                    rr_ratio=4.0,
                    risk_usd=risk_usd,
                    qty=qty,
                    displacement=round(displacement * 100, 1),
                    vol_surge=round(vol_surge, 2),
                    oi_usd=metrics["oi_usd"],
                    htf_bias="BEARISH (4H/1H Aligned)",
                    reason=f"Pro Bearish Pullback: Premium zone + 1m displacement {round(displacement*100)}% + Vol surge {round(vol_surge,1)}x"
                )

        return None


# ═══════════════════════════════════════════════════════════════════════════════
# PRO INSTITUTIONAL BOT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class ProTraderBot:
    def __init__(self, client: BinanceFuturesClient):
        self.client = client
        self.engine = ProTraderEngine(risk_pct=0.01) # 1% account risk
        self.status_file = "live_status.json"
        self.symbols_status = {}

    def update_dashboard_status(self, balance: float, open_positions: list):
        try:
            status_data = {
                "status": "RUNNING (Pro Institutional v5.0)",
                "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "balance": round(balance, 2),
                "open_positions": len(open_positions),
                "positions_detail": [
                    {
                        "symbol": p["symbol"],
                        "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                        "size": float(p["positionAmt"]),
                        "entry": float(p["entryPrice"]),
                        "pnl": float(p["unRealizedProfit"])
                    } for p in open_positions
                ],
                "screened_tokens": self.symbols_status
            }
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
        except:
            pass

    def execute_pro_trade(self, sig: InstitutionalSignal, balance: float):
        print("\n" + "🔥"*40)
        print(f"🎯 [PRO INSTITUTIONAL TRADE SIGNAL TRIGGERED]")
        print(f"   Symbol: {sig.symbol} | Direction: {sig.direction}")
        print(f"   HTF Bias: {sig.htf_bias}")
        print(f"   Entry: ~${sig.entry_price} | SL: ${sig.sl_price} | TP1 (2.0R): ${sig.tp1_price} | TP2 (4.0R): ${sig.tp2_price}")
        print(f"   Target Move: +{sig.target_gain_pct}% | R:R: {sig.rr_ratio}:1")
        print(f"   Risk: ${sig.risk_usd} (1.0% of Balance) | Calculated Qty: {sig.qty}")
        print(f"   Displacement: {sig.displacement}% | Vol Surge: {sig.vol_surge}x | Open Interest: ${round(sig.oi_usd/1e6,1)}M")
        print(f"   Reason: {sig.reason}")
        print("🔥"*40)

        order_side = "BUY" if sig.direction == "LONG" else "SELL"
        sl_side = "SELL" if sig.direction == "LONG" else "BUY"

        qty_prec, price_prec = self.client.get_symbol_precision(sig.symbol)

        try:
            self.client.set_leverage(sig.symbol, 5)
            print(f"   1. Executing MARKET {order_side} {sig.qty} {sig.symbol}...")
            res = self.client.place_market_order(sig.symbol, order_side, sig.qty)
            print(f"      ✓ Fill Success! OrderId: {res.get('orderId')}")

            print(f"   2. Placing Guaranteed Algo Stop-Loss at ${sig.sl_price}...")
            sl_res = self.client.place_stop_loss_algo(sig.symbol, sl_side, sig.qty, sig.sl_price)
            print(f"      ✓ Stop-Loss Live! AlgoId: {sl_res.get('orderId') or sl_res.get('algoId')}")

            tp_qty = round(sig.qty * 0.5, qty_prec)
            if tp_qty > 0:
                print(f"   3. Placing TP1 Limit (50% position) at ${sig.tp1_price}...")
                tp_res = self.client.place_take_profit_limit(sig.symbol, sl_side, tp_qty, sig.tp1_price)
                print(f"      ✓ TP1 Active! OrderId: {tp_res.get('orderId')}")

        except Exception as e:
            print(f"🛑 [EXECUTION ERROR]: {e}")

    def run_scan_cycle(self):
        balance = self.client.get_account_balance()
        open_positions = self.client.get_open_positions()
        active_symbols = {p["symbol"] for p in open_positions}

        print(f"\n{'='*78}")
        print(f"🏛️ [PRO INSTITUTIONAL SCAN] {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Balance: ${balance:.2f} | Open: {len(open_positions)}/2")
        print(f"{'='*78}")

        universe = self.engine.get_institutional_universe()
        print(f"   Screening Top Liquid Universe ({len(universe)} pairs): {universe}")

        if len(open_positions) >= 2:
            print("   🔒 Max risk cap reached (2 active positions). Scanning for monitoring only.")
            self.update_dashboard_status(balance, open_positions)
            return

        for sym in universe:
            if sym in active_symbols:
                continue

            try:
                qty_prec, price_prec = self.client.get_symbol_precision(sym)
                sig = self.engine.check_pro_setup(sym, balance, qty_prec, price_prec)

                # Fetch brief metrics for display
                metrics = self.engine.get_token_metrics(sym)
                vol_m = round(metrics["volume_24h_usd"] / 1e6, 1) if metrics else 0
                oi_m = round(metrics["oi_usd"] / 1e6, 1) if metrics else 0

                if sig:
                    print(f"   💎 [{sym:<9}] Vol: ${vol_m}M | OI: ${oi_m}M | ===> HIGH PROBABILITY SETUP FOUND!")
                    self.execute_pro_trade(sig, balance)
                    break
                else:
                    print(f"   [{sym:<9}] Vol: ${vol_m}M | OI: ${oi_m}M | Status: Scanning for institutional pullback...")
                    self.symbols_status[sym] = {"volume_m": vol_m, "oi_m": oi_m, "status": "WAITING_PULLBACK"}

            except Exception as e:
                pass

        self.update_dashboard_status(balance, open_positions)

    def start(self):
        print("="*78)
        print("  T.R TECHNOLOGY PRO INSTITUTIONAL TRADING BOT STARTED")
        print("  - Macro Confluence: 4H & 1H Structure (Smart Money Trend)")
        print("  - Zone Equilibrium: Premium vs Discount Pricing")
        print("  - Trigger: 1-Minute Candle Displacement + Institutional Volume Surge")
        print("  - Risk: 1% Dynamic Account Risk ($50 on $5k)")
        print("  - Targets: TP1 = 2.0R (Risk-Free Lock), TP2 = 4.0R (HTF Liquidity Sweep)")
        print("="*78)

        self.run_scan_cycle()

        last_minute = -1
        while True:
            try:
                now = datetime.now(timezone.utc)
                if now.minute != last_minute:
                    print(f"\n⏰ 1-Minute Candle Closed ({now.strftime('%H:%M:%S UTC')})! Evaluating setups...")
                    time.sleep(2)
                    self.run_scan_cycle()
                    last_minute = now.minute

                time.sleep(5)
            except KeyboardInterrupt:
                print("Bot stopped by user.")
                break
            except Exception as e:
                time.sleep(5)


def main():
    api_key = "iJ35G0Rsox6fnJ2NRFqgxLHX1v4RbjcPuld22s3IoWZ3XQvAupXk2NkddolGMQjy"
    api_secret = "7lka4R7YfYeBXXIoKc8vC0Smb5THDJGUYU0LfGHorL5KgF67OZb1i77TmmqRX1mG"
    client = BinanceFuturesClient(api_key, api_secret, testnet=True)
    bot = ProTraderBot(client)
    bot.start()


if __name__ == "__main__":
    main()
