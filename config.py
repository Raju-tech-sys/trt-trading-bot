"""
T.R Technology Trading Bot — Configuration (v1.0)
All parameters locked for initial backtest. Do NOT change without full re-backtest.
"""

# ─── Pairs ───────────────────────────────────────────────────────────────────
PAIRS = ["SOLUSDT", "INJUSDT"]
EXCHANGE = "binance"

# ─── Account ─────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 500.0

# ─── Fees & Slippage ────────────────────────────────────────────────────────
TAKER_FEE = 0.0005       # 0.05%
MAKER_FEE = 0.0002       # 0.02%
SLIPPAGE  = 0.0003       # 0.03%

# ─── Timeframes (v2.0 1h Swing Framework) ──────────────────────────────────
ENTRY_TF     = "1h"     # Changed from 15m to 1h to eliminate noise & fee drag
REGIME_TF    = "1h"     # Regime checked on 1h
DIRECTION_TF = "4h"     # 4h EMA50/200 trend direction filter

# ─── Indicator Parameters ───────────────────────────────────────────────────
EMA_FAST   = 20
EMA_MID    = 50
EMA_SLOW   = 200
ADX_PERIOD = 14
ATR_PERIOD = 14
BB_PERIOD  = 20
BB_STD     = 2
RSI_PERIOD = 14

# ─── Regime Switch (ADX on 1h) ──────────────────────────────────────────────
ADX_TREND_THRESHOLD    = 25
ADX_SIDEWAYS_THRESHOLD = 20
HYSTERESIS_HOURS       = 4

# ─── Funding Rate Filter ────────────────────────────────────────────────────
FUNDING_RATE_LIMIT = 0.0005     # 0.05% per 8h

# ─── Module A: Trend Pullback (v1.1 Optimized) ─────────────────────────────
MOD_A_SL_ATR_MULT  = 2.0       # Widened from 1.5 to 2.0 to avoid market noise
MOD_A_TP1_R        = 1.5       # TP1 at 1.5R (50% close, SL to BE)
MOD_A_TP2_R        = 2.5       # Adjusted TP2 to 2.5R for higher hit rate
MOD_A_TP1_CLOSE    = 0.5       # Close 50% at TP1
MOD_A_RISK_PCT     = 0.01      # 1% risk ($5)
MOD_A_REENTRY_ATR  = 1.0       # Re-entry distance filter
MOD_A_USE_LIMIT    = True      # Use limit order (maker fee 0.02% instead of 0.05%)
MOD_A_RSI_FILTER   = True      # RSI > 50 for Long, RSI < 50 for Short

# ─── Module B: Range ────────────────────────────────────────────────────────
MOD_B_RANGE_CANDLES    = 25
MOD_B_MIN_RANGE_ATR    = 1.5
MOD_B_RSI_OVERSOLD     = 30
MOD_B_RSI_OVERBOUGHT   = 70
MOD_B_SL_ATR_MULT      = 1.0
MOD_B_RISK_PCT         = 0.005 # 0.5%
MOD_B_RANGE_BREAK_ATR  = 1.0

# ─── Position Limits ────────────────────────────────────────────────────────
MAX_TOTAL_POSITIONS   = 2
MAX_POSITIONS_PER_COIN = 1

# ─── Risk Controls ──────────────────────────────────────────────────────────
DAILY_LOSS_LIMIT_PCT      = 0.03
CONSECUTIVE_LOSS_PAUSE    = 5
VOLUME_FILTER_THRESHOLD   = 0.5

# ─── Health Check ────────────────────────────────────────────────────────────
HEALTH_CHECK_TRADES       = 30
DRAWDOWN_HALF_SIZE_PCT    = 0.10
DRAWDOWN_STOP_PCT         = 0.15
LIVE_BACKTEST_DIVERGE_PCT = 0.20

# ─── Backtest Settings ──────────────────────────────────────────────────────
OUT_OF_SAMPLE_RATIO = 0.30
WALK_FORWARD_PERIODS = 3
MIN_TRADES_PER_MODULE = 100
MIN_PROFIT_FACTOR = 1.3
MAX_DRAWDOWN_PCT = 0.15
