"""
strategies/sell/__init__.py
───────────────────────────
This file contains all 20 SELL strategies.
Each strategy is a separate class that looks at price data in a
different way and decides whether to vote SELL or do nothing.
All 20 run at the same time on every price update alongside the
20 buy strategies.
The ALL_SELL_STRATEGIES list at the bottom registers all of them
so the strategy engine can find and run them automatically.
Note: S05, S06, and S20 are RISK strategies — they exit trades
based on price movement, not market signals.
"""

from __future__ import annotations
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, Signal
from indicators.rsi       import compute_rsi
from indicators.macd      import compute_macd, bearish_crossover
from indicators.ema       import compute_ema, ema_crossover_bearish
from indicators.bollinger import compute_bbands, touch_upper_band
from indicators.atr       import compute_stochastic, compute_adx, compute_vwap, compute_cci


# S01 — RSI Overbought Sell
# RSI measures if price has risen too far too fast (scale 0-100).
# When RSI peaks above 70 (overbought) then falls back below 67,
# buyers are exhausted and sellers are returning — vote SELL.
class RSIOverboughtSell(BaseStrategy):
    name = "S01_RSIOverboughtSell"; category = "swing"
    def __init__(self, period=14, overbought=70.0, revert=67.0):
        self.period, self.overbought, self.revert = period, overbought, revert
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"], self.period)
        if rsi.iloc[-2] > self.overbought and rsi.iloc[-1] <= self.revert:
            return self._sell(0.75, f"RSI reverting from {rsi.iloc[-2]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


# S02 — MACD Bearish Crossover
# MACD tracks the difference between two moving averages.
# When the fast line crosses BELOW the slow line, short-term
# momentum is turning bearish — vote SELL.
class MACDBearishCrossover(BaseStrategy):
    name = "S02_MACDBearishCrossover"; category = "swing"
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast, self.slow, self.signal = fast, slow, signal
    def evaluate(self, df):
        if len(df) < self.slow + self.signal: return self._no_signal("insufficient data")
        if bearish_crossover(df["close"], fast=self.fast, slow=self.slow, signal_period=self.signal).iloc[-1]:
            r = compute_macd(df["close"], self.fast, self.slow, self.signal)
            return self._sell(0.80, "MACD crossed below signal", macd=round(r.macd.iloc[-1],6))
        return self._no_signal()


# S03 — EMA Bearish Crossover
# Two moving averages at different speeds are compared.
# When the faster one crosses BELOW the slower one,
# the short-term trend has turned downward — vote SELL.
class EMABearishCrossover(BaseStrategy):
    name = "S03_EMABearishCrossover"; category = "swing"
    def __init__(self, fast=9, slow=21):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        if ema_crossover_bearish(df["close"], self.fast, self.slow).iloc[-1]:
            return self._sell(0.72, f"EMA{self.fast} crossed below EMA{self.slow}")
        return self._no_signal()


# S04 — Bollinger Upper Touch Sell
# Bollinger Bands mark statistically extreme price levels.
# When price touches the upper band (very overbought) then
# closes back inside, it signals a reversal downward — vote SELL.
class BollingerUpperTouchSell(BaseStrategy):
    name = "S04_BollingerUpperTouch"; category = "swing"
    def __init__(self, period=20, std_dev=2.0):
        self.period, self.std_dev = period, std_dev
    def evaluate(self, df):
        if len(df) < self.period: return self._no_signal()
        bb = compute_bbands(df["close"], self.period, self.std_dev)
        if touch_upper_band(df["close"], self.period, self.std_dev).iloc[-2] and \
                df["close"].iloc[-1] < bb.upper.iloc[-1]:
            return self._sell(0.70, "Rejection from upper Bollinger Band", pct_b=round(bb.pct_b.iloc[-1],3))
        return self._no_signal()


# S05 — Stop Loss Trigger Sell (RISK STRATEGY)
# This is NOT a market signal — it is a safety rule.
# If price drops 2% below the entry price, exit the trade
# immediately to prevent a small loss becoming a large one.
# entry_price must be set by calling set_entry() when a trade opens.
class StopLossTriggerSell(BaseStrategy):
    name = "S05_StopLossTrigger"; category = "risk"
    def __init__(self, stop_pct=0.02):
        self.stop_pct = stop_pct
        self.entry_price: float | None = None  # Set when a trade is opened
    def set_entry(self, price: float) -> None:
        # Called by the trade executor to record the entry price
        self.entry_price = price
    def evaluate(self, df):
        if self.entry_price is None: return self._no_signal("no entry set")
        current = df["close"].iloc[-1]
        # Calculate how much price has dropped from entry
        drop = (self.entry_price - current) / self.entry_price
        if drop >= self.stop_pct:
            return self._sell(1.0, f"Stop-loss: {drop*100:.2f}% drop from {self.entry_price:.5f}")
        return self._no_signal()


# S06 — Trailing Stop Sell (RISK STRATEGY)
# This is NOT a market signal — it is a profit protection rule.
# It tracks the highest price since entry. If price then drops
# 1.5% from that peak, it exits to lock in most of the profit.
# Lets winners run while protecting gains when price reverses.
class TrailingStopSell(BaseStrategy):
    name = "S06_TrailingStop"; category = "risk"
    def __init__(self, trail_pct=0.015):
        self.trail_pct = trail_pct
        self._peak: float | None = None  # Tracks the highest price seen since entry
    def evaluate(self, df):
        price = df["close"].iloc[-1]
        # Update the peak if price has moved higher
        if self._peak is None or price > self._peak:
            self._peak = price
        # Calculate how far price has dropped from the peak
        drop = (self._peak - price) / self._peak
        if drop >= self.trail_pct:
            return self._sell(0.95, f"Trailing stop: {drop*100:.2f}% from peak {self._peak:.5f}")
        return self._no_signal()


# S07 — Stochastic Overbought Sell
# Stochastic compares close price to recent high/low range.
# When both lines are above 80 (overbought) and the fast line
# crosses below the slow line, momentum is turning down — vote SELL.
class StochasticOverboughtSell(BaseStrategy):
    name = "S07_StochasticOverboughtSell"; category = "scalp"
    def __init__(self, k=14, d=3, threshold=80.0):
        self.k, self.d, self.threshold = k, d, threshold
    def evaluate(self, df):
        if len(df) < self.k + self.d: return self._no_signal()
        k, d = compute_stochastic(df, self.k, self.d)
        if (k.iloc[-2] > d.iloc[-2]) and (k.iloc[-1] < d.iloc[-1]) and (k.iloc[-1] > self.threshold):
            return self._sell(0.73, f"Stoch K={k.iloc[-1]:.1f} crossed below D in overbought")
        return self._no_signal()


# S08 — Inside Bar Breakdown Sell
# An inside bar is when a candle stays within the range of the
# previous candle — showing indecision. When price then breaks
# below the mother bar low, sellers have won — vote SELL.
class InsideBarBreakdownSell(BaseStrategy):
    name = "S08_InsideBarBreakdownSell"; category = "scalp"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal()
        m, ins, cur = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        is_inside   = ins["high"] <= m["high"] and ins["low"] >= m["low"]
        breaks_down = cur["close"] < m["low"]
        if is_inside and breaks_down:
            return self._sell(0.68, "Inside bar bearish breakdown")
        return self._no_signal()


# S09 — Shooting Star Sell
# A shooting star has a small body near the bottom and a long upper shadow.
# It shows buyers pushed price up hard but sellers pushed it all the way
# back down — strong rejection of higher prices — vote SELL.
class ShootingStarSell(BaseStrategy):
    name = "S09_ShootingStar"; category = "swing"
    def __init__(self, body_ratio=0.3, shadow_ratio=2.0):
        self.body_ratio, self.shadow_ratio = body_ratio, shadow_ratio
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        r = df.iloc[-1]
        body  = abs(r["close"] - r["open"])
        total = r["high"] - r["low"]
        upper = r["high"] - max(r["open"], r["close"])
        lower = min(r["open"], r["close"]) - r["low"]
        if total == 0: return self._no_signal()
        if (body < self.body_ratio * total and
                upper > self.shadow_ratio * body and lower <= body):
            return self._sell(0.65, "Shooting star candlestick pattern")
        return self._no_signal()


# S10 — Bearish Engulfing Sell
# A bullish candle is completely swallowed by the next bearish candle.
# This shows sellers overwhelmed all previous buying in one move —
# a strong reversal signal — vote SELL.
class BearishEngulfingSell(BaseStrategy):
    name = "S10_BearishEngulfing"; category = "swing"
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (prev["close"] > prev["open"] and curr["close"] < curr["open"] and
                curr["open"] > prev["close"] and curr["close"] < prev["open"]):
            return self._sell(0.77, "Bearish engulfing pattern")
        return self._no_signal()


# S11 — Death Cross Sell
# The most feared long-term bearish signal in trading.
# When the 50 EMA (medium-term) crosses BELOW the 200 EMA (long-term),
# it signals a major downtrend is starting — vote SELL.
class DeathCrossSell(BaseStrategy):
    name = "S11_DeathCross"; category = "swing"
    def __init__(self, fast=50, slow=200):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        ef = compute_ema(df["close"], self.fast)
        es = compute_ema(df["close"], self.slow)
        if ef.iloc[-2] > es.iloc[-2] and ef.iloc[-1] <= es.iloc[-1]:
            return self._sell(0.85, "Death Cross: 50 EMA crossed below 200 EMA")
        return self._no_signal()


# S12 — VWAP Rejection Sell
# VWAP is where most trading happened today — institutions watch it.
# When price tries to rise above VWAP from below but fails and falls
# back, it signals institutional sellers rejecting the level — vote SELL.
class VWAPRejectionSell(BaseStrategy):
    name = "S12_VWAPRejectionSell"; category = "scalp"
    def __init__(self, tolerance=0.0005):
        self.tolerance = tolerance
    def evaluate(self, df):
        if len(df) < 20: return self._no_signal()
        try:
            vwap = compute_vwap(df)
        except Exception:
            return self._no_signal()
        price, v = df["close"].iloc[-1], vwap.iloc[-1]
        if abs(price - v) / v < self.tolerance and price < v and \
                compute_rsi(df["close"]).iloc[-1] > 45:
            return self._sell(0.71, f"VWAP rejection at {v:.5f}")
        return self._no_signal()


# S13 — RSI Bearish Divergence Sell
# Price makes a higher high but RSI makes a lower high.
# This means buyers are getting weaker even as price rises —
# hidden exhaustion that typically precedes a reversal — vote SELL.
class RSIBearishDivergenceSell(BaseStrategy):
    name = "S13_RSIBearishDivergence"; category = "swing"
    def __init__(self, period=14, lookback=20):
        self.period, self.lookback = period, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + self.period: return self._no_signal()
        rsi   = compute_rsi(df["close"], self.period)
        price = df["close"]
        high_idx = price.iloc[-self.lookback:].idxmax()
        if price.iloc[-1] >= price[high_idx] and rsi.iloc[-1] < rsi[high_idx] and rsi.iloc[-1] > 60:
            return self._sell(0.82, "Bearish RSI divergence detected")
        return self._no_signal()


# S14 — Evening Star Sell
# Three candles tell the story: Bar 1 strong buying, Bar 2 indecision,
# Bar 3 strong selling that closes below Bar 1 midpoint.
# This is a complete buyer exhaustion pattern — vote SELL.
class EveningStarSell(BaseStrategy):
    name = "S14_EveningStar"; category = "swing"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal()
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if (c1["close"] > c1["open"] and
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and
                c3["close"] < c3["open"] and
                c3["close"] < (c1["open"] + c1["close"]) / 2):
            return self._sell(0.78, "Evening Star reversal pattern")
        return self._no_signal()


# S15 — Lower Highs Pattern Sell
# Every bar is making a lower high and lower low than the one before.
# This is the textbook definition of a downtrend — confirmed momentum
# across multiple bars — vote SELL.
class LowerHighsSell(BaseStrategy):
    name = "S15_LowerHighsPattern"; category = "swing"
    def __init__(self, lookback=5):
        self.lookback = lookback
    def evaluate(self, df):
        if len(df) < self.lookback * 2: return self._no_signal()
        highs = df["high"].iloc[-self.lookback:]
        lows  = df["low"].iloc[-self.lookback:]
        if (all(highs.iloc[i] < highs.iloc[i-1] for i in range(1, len(highs))) and
                all(lows.iloc[i] < lows.iloc[i-1] for i in range(1, len(lows)))):
            return self._sell(0.72, f"Lower highs & lows over {self.lookback} bars")
        return self._no_signal()


# S16 — CCI Overbought Sell
# CCI measures how far price has deviated from its statistical average.
# When CCI rises above +100 (extreme high) then crosses back below it,
# the extreme is ending and price reverts downward — vote SELL.
class CCIOverboughtSell(BaseStrategy):
    name = "S16_CCIOverboughtSell"; category = "swing"
    def __init__(self, period=20, threshold=100.0):
        self.period, self.threshold = period, threshold
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal()
        cci = compute_cci(df, self.period)
        if cci.iloc[-2] > self.threshold and cci.iloc[-1] <= self.threshold:
            return self._sell(0.71, f"CCI fell from overbought ({self.threshold})")
        return self._no_signal()


# S17 — Momentum Breakdown Sell
# Price breaks to a new 20-bar low AND volume is above average.
# Volume confirmation means institutional sellers are participating —
# the breakdown is genuine not a fake-out — vote SELL.
class MomentumBreakdownSell(BaseStrategy):
    name = "S17_MomentumBreakdown"; category = "scalp"
    def __init__(self, vol_mult=1.5, lookback=20):
        self.vol_mult, self.lookback = vol_mult, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + 2: return self._no_signal()
        avg_vol  = df["tick_volume"].iloc[-self.lookback:-1].mean()
        curr_vol = df["tick_volume"].iloc[-1]
        low_20   = df["low"].iloc[-self.lookback:-1].min()
        if df["close"].iloc[-1] < low_20 and curr_vol > self.vol_mult * avg_vol:
            return self._sell(0.83, f"Volume surge ({curr_vol:.0f}) + downside breakout")
        return self._no_signal()


# S18 — Resistance Rejection Sell
# Calculates where price has historically stalled and reversed
# (90th percentile high). When price returns to this zone and starts
# falling, sellers step in at a proven level — vote SELL.
class ResistanceRejectionSell(BaseStrategy):
    name = "S18_ResistanceRejection"; category = "swing"
    def __init__(self, lookback=50, tolerance=0.002):
        self.lookback, self.tolerance = lookback, tolerance
    def evaluate(self, df):
        if len(df) < self.lookback: return self._no_signal()
        resistance = df["high"].iloc[-self.lookback:-5].quantile(0.9)
        price = df["close"].iloc[-1]
        if abs(price - resistance) / resistance < self.tolerance and \
                df["close"].iloc[-1] < df["close"].iloc[-2]:
            return self._sell(0.70, f"Rejected from resistance {resistance:.5f}")
        return self._no_signal()


# S19 — Bollinger Squeeze Breakdown Sell
# When Bollinger Bands narrow (squeeze), volatility is compressed.
# When price then breaks below the lower band, the compressed energy
# releases downward — the start of a strong bearish move — vote SELL.
class BollingerSqueezeBreakdownSell(BaseStrategy):
    name = "S19_BollingerSqueezeBreakdown"; category = "swing"
    def __init__(self, period=20, squeeze_threshold=0.05):
        self.period, self.squeeze_threshold = period, squeeze_threshold
    def evaluate(self, df):
        if len(df) < self.period + 5: return self._no_signal()
        bb = compute_bbands(df["close"], self.period)
        squeezed = (bb.bandwidth.iloc[-5:-1] < self.squeeze_threshold).all()
        if squeezed and df["close"].iloc[-1] < bb.lower.iloc[-1]:
            return self._sell(0.80, "Bollinger squeeze bearish breakdown")
        return self._no_signal()


# S20 — Take Profit Sell (RISK STRATEGY)
# This is NOT a market signal — it is a profit locking rule.
# When a trade gains 3% above the entry price, exit automatically
# to lock in the profit before the market can take it back.
# entry_price must be set by calling set_entry() when a trade opens.
class TakeProfitSell(BaseStrategy):
    name = "S20_TakeProfitReached"; category = "risk"
    def __init__(self, target_pct=0.03):
        self.target_pct = target_pct
        self.entry_price: float | None = None  # Set when a trade is opened
    def set_entry(self, price: float) -> None:
        # Called by the trade executor to record the entry price
        self.entry_price = price
    def evaluate(self, df):
        if self.entry_price is None: return self._no_signal("no entry set")
        current = df["close"].iloc[-1]
        # Calculate how much price has gained from entry
        gain = (current - self.entry_price) / self.entry_price
        if gain >= self.target_pct:
            return self._sell(1.0, f"Take-profit: {gain*100:.2f}% gain from {self.entry_price:.5f}")
        return self._no_signal()


# ── Strategy Registry ─────────────────────────────────────────────────────────
# This list registers all 20 sell strategies in one place.
# The strategy engine imports ALL_SELL_STRATEGIES and runs every
# strategy in this list on every price update automatically.
# To add a new strategy, create the class above and add it here.
# S05, S06, S20 are risk strategies — they always run regardless
# of market conditions to protect open positions.
ALL_SELL_STRATEGIES: list[BaseStrategy] = [
    RSIOverboughtSell(), MACDBearishCrossover(), EMABearishCrossover(),
    BollingerUpperTouchSell(), StopLossTriggerSell(), TrailingStopSell(),
    StochasticOverboughtSell(), InsideBarBreakdownSell(), ShootingStarSell(),
    BearishEngulfingSell(), DeathCrossSell(), VWAPRejectionSell(),
    RSIBearishDivergenceSell(), EveningStarSell(), LowerHighsSell(),
    CCIOverboughtSell(), MomentumBreakdownSell(), ResistanceRejectionSell(),
    BollingerSqueezeBreakdownSell(), TakeProfitSell(),
]