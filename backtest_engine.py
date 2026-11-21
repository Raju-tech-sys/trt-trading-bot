"""
T.R Technology — Backtest Engine
Core engine: regime detection, signal generation, position management, fees & slippage.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict
from enum import Enum

import config as cfg
from indicators import compute_all_indicators
from regime import Regime, compute_regime_series, get_regime_at_time
from modules import ModuleA, ModuleB, Signal, Direction, OrderType


@dataclass
class Position:
    id: int
    coin: str
    module: str
    direction: Direction
    entry_price: float
    entry_time: pd.Timestamp
    size: float
    remaining_size: float
    sl_price: float
    original_sl: float
    tp_prices: List[float]
    tp_close_pcts: List[float]
    tp_index: int = 0
    entry_fee: float = 0.0
    atr_at_entry: float = 0.0
    adx_at_entry: float = 0.0
    rsi_at_entry: float = 0.0
    sl_moved_to_be: bool = False


@dataclass
class TradeResult:
    trade_id: int
    coin: str
    module: str
    direction: str
    entry_time: object
    exit_time: object
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    size: float
    leverage: float
    fee_paid: float
    slippage_cost: float
    result_r: float
    result_usd: float
    pnl_after_fees: float
    adx_1h: float
    atr_15m: float
    rsi_14: float
    funding_rate: float
    regime: str
    exit_reason: str


class BacktestEngine:
    def __init__(self, capital: float = None):
        self.initial_capital = capital or cfg.INITIAL_CAPITAL
        self.capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.module_a = ModuleA(cfg)
        self.module_b = ModuleB(cfg)
        self.positions: List[Position] = []
        self.trades: List[TradeResult] = []
        self.trade_counter = 0
        self._daily_pnl: Dict[str, float] = {}
        self._consecutive_losses = 0
        self._paused = False
        self._pause_until = None
        self._current_regime = Regime.NO_TRADE

    def reset(self):
        self.capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.positions.clear()
        self.trades.clear()
        self.trade_counter = 0
        self._daily_pnl.clear()
        self._consecutive_losses = 0
        self._paused = False
        self._pause_until = None
        self._current_regime = Regime.NO_TRADE
        self.module_a.reset()
        self.module_b.reset()

    def _fee_rate(self, ot: OrderType) -> float:
        return cfg.MAKER_FEE if ot == OrderType.LIMIT else cfg.TAKER_FEE

    def _slip(self, price: float, direction: Direction, is_entry: bool) -> float:
        s = price * cfg.SLIPPAGE
        if is_entry:
            return price + s if direction == Direction.LONG else price - s
        return price - s if direction == Direction.LONG else price + s

    def _get_funding(self, fdf: pd.DataFrame, ts: pd.Timestamp) -> float:
        if fdf.empty:
            return 0.0
        idx = fdf["time"].searchsorted(ts, side="right")
        return fdf.iloc[idx - 1]["funding_rate"] if idx > 0 else 0.0

    def _no_trade(self, df_15m: pd.DataFrame, idx: int, fr: float) -> bool:
        row = df_15m.iloc[idx]
        ts = row["open_time"]

        if self._paused:
            # If paused due to consecutive losses, simulate manual review after 24h
            if self._pause_until is not None and ts >= self._pause_until:
                self._paused = False
                self._pause_until = None
                self._consecutive_losses = 0
            else:
                return True

        if len(self.positions) >= cfg.MAX_TOTAL_POSITIONS:
            return True

        dk = str(ts.date())
        if self._daily_pnl.get(dk, 0.0) <= -(cfg.DAILY_LOSS_LIMIT_PCT * self.capital):
            return True

        if self._consecutive_losses >= cfg.CONSECUTIVE_LOSS_PAUSE:
            self._paused = True
            self._pause_until = ts + pd.Timedelta(hours=24)
            return True
        if abs(fr) > cfg.FUNDING_RATE_LIMIT:
            return True
        if idx >= 20:
            avg_v = df_15m.iloc[idx-20:idx]["volume"].mean()
            if avg_v > 0 and row["volume"] < cfg.VOLUME_FILTER_THRESHOLD * avg_v:
                return True
        return False

    def _coin_full(self, coin: str) -> bool:
        return sum(1 for p in self.positions if p.coin == coin) >= cfg.MAX_POSITIONS_PER_COIN

    def _make_result(self, pos: Position, exit_price: float, exit_time: pd.Timestamp,
                     size: float, reason: str, candle: pd.Series) -> TradeResult:
        if pos.direction == Direction.LONG:
            raw_pnl = (exit_price - pos.entry_price) * size
        else:
            raw_pnl = (pos.entry_price - exit_price) * size

        entry_n = pos.entry_price * size
        exit_n = exit_price * size
        efr = self._fee_rate(OrderType.LIMIT if pos.module == "B" else OrderType.MARKET)
        xfr = self._fee_rate(OrderType.MARKET)
        total_fee = entry_n * efr + exit_n * xfr
        slip_cost = (entry_n + exit_n) * cfg.SLIPPAGE
        pnl = raw_pnl - total_fee

        sl_dist = abs(pos.entry_price - pos.original_sl)
        if sl_dist > 0:
            rr = (exit_price - pos.entry_price) / sl_dist
            if pos.direction == Direction.SHORT:
                rr = -rr
        else:
            rr = 0.0

        lev = (pos.entry_price * pos.size) / self.capital if self.capital > 0 else 1.0

        return TradeResult(
            trade_id=pos.id,
            coin=pos.coin,
            module=pos.module,
            direction=pos.direction.value,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            sl_price=pos.original_sl,
            tp_price=pos.tp_prices[0] if pos.tp_prices else 0.0,
            size=size,
            leverage=round(lev, 2),
            fee_paid=total_fee,
            slippage_cost=slip_cost,
            result_r=round(rr, 4),
            result_usd=round(pnl, 4),
            pnl_after_fees=round(pnl, 4),
            adx_1h=pos.adx_at_entry,
            atr_15m=pos.atr_at_entry,
            rsi_14=pos.rsi_at_entry,
            funding_rate=0.0,
            regime=self._current_regime.value,
            exit_reason=reason
        )

    def _update_positions(self, candle: pd.Series, coin: str) -> List[TradeResult]:
        results, remaining = [], []
        for pos in self.positions:
            if pos.coin != coin:
                remaining.append(pos)
                continue
            h, l, ts = candle["high"], candle["low"], candle["open_time"]
            
            # SL check
            sl_hit = (pos.direction == Direction.LONG and l <= pos.sl_price) or \
                     (pos.direction == Direction.SHORT and h >= pos.sl_price)
            if sl_hit:
                ep = self._slip(pos.sl_price, pos.direction, False)
                results.append(self._make_result(pos, ep, ts, pos.remaining_size, "SL_HIT", candle))
                continue

            # TP check
            if pos.tp_index < len(pos.tp_prices):
                tp = pos.tp_prices[pos.tp_index]
                tp_hit = (pos.direction == Direction.LONG and h >= tp) or \
                         (pos.direction == Direction.SHORT and l <= tp)
                if tp_hit:
                    cpct = pos.tp_close_pcts[pos.tp_index]
                    csz = pos.remaining_size * cpct
                    ep = self._slip(tp, pos.direction, False)
                    pos.remaining_size -= csz
                    pos.tp_index += 1
                    if pos.module == "A" and pos.tp_index == 1 and not pos.sl_moved_to_be:
                        pos.sl_price = pos.entry_price
                        pos.sl_moved_to_be = True
                    results.append(self._make_result(pos, ep, ts, csz, f"TP{pos.tp_index}", candle))
                    if pos.remaining_size > 1e-10:
                        remaining.append(pos)
                    continue

            remaining.append(pos)

        self.positions = remaining
        return results

    def _open_position(self, sig: Signal, coin: str, ts: pd.Timestamp) -> Optional[Position]:
        self.trade_counter += 1
        ep = self._slip(sig.entry_price, sig.direction, True)
        risk_usd = sig.risk_pct * self.capital
        sl_d = abs(ep - sig.sl_price)
        if sl_d <= 0:
            return None
        size = risk_usd / sl_d
        fee = ep * size * self._fee_rate(sig.order_type)
        pos = Position(
            id=self.trade_counter,
            coin=coin,
            module=sig.module,
            direction=sig.direction,
            entry_price=ep,
            entry_time=ts,
            size=size,
            remaining_size=size,
            sl_price=sig.sl_price,
            original_sl=sig.sl_price,
            tp_prices=sig.tp_prices,
            tp_close_pcts=sig.tp_close_pcts,
            tp_index=0,
            entry_fee=fee,
            atr_at_entry=sig.atr_at_entry,
            adx_at_entry=sig.adx_at_entry,
            rsi_at_entry=sig.rsi_at_entry
        )
        self.positions.append(pos)
        return pos

    def _regime_change(self, new_r: Regime, candle: pd.Series, coin: str) -> List[TradeResult]:
        if new_r == self._current_regime:
            return []
        results, remaining = [], []
        for pos in self.positions:
            if pos.coin == coin:
                ep = self._slip(candle["close"], pos.direction, False)
                results.append(self._make_result(pos, ep, candle["open_time"],
                    pos.remaining_size, "REGIME_CHANGE", candle))
            else:
                remaining.append(pos)
        self.positions = remaining
        self._current_regime = new_r
        self.module_a.reset()
        self.module_b.reset()
        return results

    def _process(self, results: List[TradeResult], ts: pd.Timestamp):
        for r in results:
            self.capital += r.pnl_after_fees
            if self.capital > self.peak_capital:
                self.peak_capital = self.capital
            dk = str(ts.date()) if hasattr(ts, 'date') else str(ts)[:10]
            self._daily_pnl[dk] = self._daily_pnl.get(dk, 0.0) + r.pnl_after_fees
            if r.pnl_after_fees < 0:
                self._consecutive_losses += 1
            else:
                self._consecutive_losses = 0
            dd = (self.peak_capital - self.capital) / self.peak_capital if self.peak_capital > 0 else 0
            if dd >= cfg.DRAWDOWN_STOP_PCT:
                self._paused = True

    def run(self, data: dict, coin: str, start_idx: int = 0, end_idx: int = None) -> List[TradeResult]:
        entry_tf = getattr(cfg, "ENTRY_TF", "1h")
        regime_tf = getattr(cfg, "REGIME_TF", "4h")
        direction_tf = getattr(cfg, "DIRECTION_TF", "4h")

        df_entry = data[entry_tf]
        df_regime = data[regime_tf]
        df_dir = data[direction_tf]
        fdf = data["funding"]

        regime_s = compute_regime_series(
            df_regime,
            hysteresis_hours=cfg.HYSTERESIS_HOURS,
            adx_trend_th=cfg.ADX_TREND_THRESHOLD,
            adx_sideways_th=cfg.ADX_SIDEWAYS_THRESHOLD
        )
        if end_idx is None:
            end_idx = len(df_entry)

        all_res = []
        warmup = max(start_idx, 200)

        for idx in range(warmup, end_idx):
            candle = df_entry.iloc[idx]
            ts = candle["open_time"]
            regime = get_regime_at_time(regime_s, ts)

            if regime != self._current_regime:
                cr = self._regime_change(regime, candle, coin)
                all_res.extend(cr)
                self._process(cr, ts)

            pr = self._update_positions(candle, coin)
            all_res.extend(pr)
            self._process(pr, ts)

            if self._coin_full(coin):
                continue

            fr = self._get_funding(fdf, ts)
            if self._no_trade(df_entry, idx, fr):
                continue

            sig = None
            if regime == Regime.TREND:
                sig = self.module_a.check_signal(df_entry, df_dir, idx, coin)
            elif regime == Regime.SIDEWAYS:
                sig = self.module_b.check_signal(df_entry, idx, coin)

            if sig:
                self._open_position(sig, coin, ts)

        # Close remaining positions at end of backtest data
        if self.positions:
            lc = df_entry.iloc[end_idx - 1]
            for pos in [p for p in self.positions if p.coin == coin]:
                r = self._make_result(pos, lc["close"], lc["open_time"],
                    pos.remaining_size, "END_OF_DATA", lc)
                all_res.append(r)
            self.positions = [p for p in self.positions if p.coin != coin]
            self._process([r for r in all_res if r.exit_reason == "END_OF_DATA"], lc["open_time"])

        return all_res
