"""
strategies/buy/__init__.py
──────────────────────────
This file contains all 20 BUY strategies.
Each strategy is a separate class that looks at price data in a
different way and decides whether to vote BUY or do nothing.
All 20 run at the same time on every price update.
The ALL_BUY_STRATEGIES list at the bottom registers all of them
so the strategy engine can find and run them automatically.
"""

from __future__ import annotations
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, Signal
from indicators.rsi       import compute_rsi
from indicators.macd      import compute_macd, bullish_crossover
from indicators.ema       import compute_ema, ema_crossover_bullish, price_above_ema
from indicators.bollinger import compute_bbands, touch_lower_band
from indicators.atr       import compute_atr, compute_stochastic, compute_adx, compute_vwap, compute_cci


# ─────────────────────────────────────────────────────────────────────────────
# B01 — RSI Oversold Bounce
# RSI measures if price has fallen too far too fast (scale 0-100).
# When RSI drops below 30 (oversold) then bounces back above 33,
# it signals buyers are returning — vote BUY.
class RSIOversoldBounce(BaseStrategy):
    name = "B01_RSIOversoldBounce"; category = "swing"
    def __init__(self, period=14, oversold=30.0, recover=33.0):
        self.period, self.oversold, self.recover = period, oversold, recover
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"], self.period)
        if rsi.iloc[-2] < self.oversold and rsi.iloc[-1] >= self.recover:
            return self._buy(0.75, f"RSI recovering from {rsi.iloc[-2]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


# B02 — MACD Bullish Crossover
# MACD tracks the difference between two moving averages.
# When the fast line crosses ABOVE the slow line, short-term
# momentum is turning bullish — vote BUY.
class MACDBullishCrossover(BaseStrategy):
    name = "B02_MACDBullishCrossover"; category = "swing"
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast, self.slow, self.signal = fast, slow, signal
    def evaluate(self, df):
        if len(df) < self.slow + self.signal: return self._no_signal("insufficient data")
        if bullish_crossover(df["close"], fast=self.fast, slow=self.slow, signal_period=self.signal).iloc[-1]:
            r = compute_macd(df["close"], self.fast, self.slow, self.signal)
            return self._buy(0.80, "MACD crossed above signal", macd=round(r.macd.iloc[-1],6))
        return self._no_signal()


# B03 — EMA Bullish Crossover
# Two moving averages at different speeds are compared.
# When the faster one crosses ABOVE the slower one,
# the short-term trend has turned upward — vote BUY.
class EMABullishCrossover(BaseStrategy):
    name = "B03_EMABullishCrossover"; category = "swing"
    def __init__(self, fast=9, slow=21):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        if ema_crossover_bullish(df["close"], self.fast, self.slow).iloc[-1]:
            return self._buy(0.72, f"EMA{self.fast} crossed above EMA{self.slow}")
        return self._no_signal()


# B04 — Bollinger Band Lower Touch Buy
# Bollinger Bands mark statistically extreme price levels.
# When price touches the lower band (very oversold) then
# closes back inside, it signals a bounce upward — vote BUY.
class BollingerLowerTouchBuy(BaseStrategy):
    name = "B04_BollingerLowerTouch"; category = "swing"
    def __init__(self, period=20, std_dev=2.0):
        self.period, self.std_dev = period, std_dev
    def evaluate(self, df):
        if len(df) < self.period: return self._no_signal("insufficient data")
        bb = compute_bbands(df["close"], self.period, self.std_dev)
        if touch_lower_band(df["close"], self.period, self.std_dev).iloc[-2] and \
                df["close"].iloc[-1] > bb.lower.iloc[-1]:
            return self._buy(0.70, "Bounce off lower Bollinger Band", pct_b=round(bb.pct_b.iloc[-1],3))
        return self._no_signal()


# B05 — Price Above 200 EMA Buy
# The 200 EMA defines the long-term trend direction.
# If price is above it (uptrend) and RSI dips below 40 (pullback),
# it is a safe "buy the dip in an uptrend" setup — vote BUY.
class PriceAbove200EMABuy(BaseStrategy):
    name = "B05_PriceAbove200EMA"; category = "swing"
    def __init__(self, ema_period=200, rsi_threshold=40.0):
        self.ema_period, self.rsi_threshold = ema_period, rsi_threshold
    def evaluate(self, df):
        if len(df) < self.ema_period: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"])
        if price_above_ema(df["close"], self.ema_period).iloc[-1] and rsi.iloc[-1] < self.rsi_threshold:
            return self._buy(0.78, f"Uptrend pullback: RSI={rsi.iloc[-1]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


# B06 — Stochastic Oversold Buy
# Stochastic compares close price to recent high/low range.
# When both lines are below 20 (oversold) and the fast line
# crosses above the slow line, momentum is turning up — vote BUY.
class StochasticOversoldBuy(BaseStrategy):
    name = "B06_StochasticOversoldBuy"; category = "scalp"
    def __init__(self, k=14, d=3, threshold=20.0):
        self.k, self.d, self.threshold = k, d, threshold
    def evaluate(self, df):
        if len(df) < self.k + self.d: return self._no_signal("insufficient data")
        k, d = compute_stochastic(df, self.k, self.d)
        if (k.iloc[-2] < d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]) and (k.iloc[-1] < self.threshold):
            return self._buy(0.73, f"Stoch K={k.iloc[-1]:.1f} crossed D in oversold")
        return self._no_signal()


# B07 — Inside Bar Breakout Buy
# An inside bar is when a candle stays within the range of the
# previous candle — showing indecision. When price then breaks
# above the mother bar high, buyers have won — vote BUY.
class InsideBarBreakoutBuy(BaseStrategy):
    name = "B07_InsideBarBreakoutBuy"; category = "scalp"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal("insufficient data")
        m, ins, cur = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        is_inside   = ins["high"] <= m["high"] and ins["low"] >= m["low"]
        breaks_up   = cur["close"] > m["high"]
        if is_inside and breaks_up:
            return self._buy(0.68, "Inside bar bullish breakout")
        return self._no_signal()


# B08 — Hammer Candle Buy
# A hammer has a small body near the top and a long lower shadow.
# It shows sellers pushed price down hard but buyers pushed it
# all the way back up — strong rejection of lower prices — vote BUY.
class HammerCandleBuy(BaseStrategy):
    name = "B08_HammerCandle"; category = "swing"
    def __init__(self, body_ratio=0.3, shadow_ratio=2.0):
        self.body_ratio, self.shadow_ratio = body_ratio, shadow_ratio
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        r = df.iloc[-1]
        body  = abs(r["close"] - r["open"])
        total = r["high"] - r["low"]
        lower = min(r["open"], r["close"]) - r["low"]
        upper = r["high"] - max(r["open"], r["close"])
        if total == 0: return self._no_signal()
        if (body < self.body_ratio * total and
                lower > self.shadow_ratio * body and upper <= body):
            return self._buy(0.65, "Hammer candlestick pattern")
        return self._no_signal()


# B09 — ADX Trend Pullback Buy
# ADX measures how strong a trend is (above 25 = strong trend).
# When ADX confirms a strong uptrend and price pulls back to the
# EMA then bounces, it is a safe trend entry — vote BUY.
class ADXTrendPullbackBuy(BaseStrategy):
    name = "B09_ADXTrendPullbackBuy"; category = "swing"
    def __init__(self, adx_period=14, adx_threshold=25, ema_period=21):
        self.adx_period, self.adx_threshold, self.ema_period = adx_period, adx_threshold, ema_period
    def evaluate(self, df):
        if len(df) < max(self.adx_period, self.ema_period) + 2: return self._no_signal("insufficient data")
        adx = compute_adx(df, self.adx_period)
        ema = compute_ema(df["close"], self.ema_period)
        at_ema = abs(df["close"].iloc[-1] - ema.iloc[-1]) / ema.iloc[-1] < 0.001
        if adx.iloc[-1] > self.adx_threshold and at_ema and ema.iloc[-1] > ema.iloc[-3]:
            return self._buy(0.76, f"ADX={adx.iloc[-1]:.1f} strong uptrend pullback to EMA")
        return self._no_signal()


# B10 — VWAP Bounce Buy
# VWAP is the volume-weighted average price — where most trading
# happened today. Big institutions watch this level. When price
# dips to VWAP from above and holds, buyers step in — vote BUY.
class VWAPBounceBuy(BaseStrategy):
    name = "B10_VWAPBounceBuy"; category = "scalp"
    def __init__(self, tolerance=0.0005):
        self.tolerance = tolerance
    def evaluate(self, df):
        if len(df) < 20: return self._no_signal("insufficient data")
        try:
            vwap = compute_vwap(df)
        except Exception:
            return self._no_signal("VWAP error")
        price, v = df["close"].iloc[-1], vwap.iloc[-1]
        if abs(price - v) / v < self.tolerance and price > v and \
                compute_rsi(df["close"]).iloc[-1] < 55:
            return self._buy(0.71, f"VWAP bounce at {v:.5f}")
        return self._no_signal()


# B11 — Triple EMA Trend Buy
# Three EMAs at different speeds all stacked in order (fast > mid > slow)
# means all timeframes agree the trend is up. When price pulls back
# to the fastest EMA in this aligned structure — vote BUY.
class TripleEMABuy(BaseStrategy):
    name = "B11_TripleEMATrend"; category = "swing"
    def __init__(self, fast=5, mid=13, slow=34):
        self.fast, self.mid, self.slow = fast, mid, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        ef = compute_ema(df["close"], self.fast)
        em = compute_ema(df["close"], self.mid)
        es = compute_ema(df["close"], self.slow)
        at_fast = abs(df["close"].iloc[-1] - ef.iloc[-1]) / ef.iloc[-1] < 0.0015
        if ef.iloc[-1] > em.iloc[-1] > es.iloc[-1] and at_fast:
            return self._buy(0.74, "Triple EMA bullish alignment + pullback")
        return self._no_signal()


# B12 — Bullish Engulfing Buy
# A bearish candle is completely swallowed by the next bullish candle.
# This shows buyers overwhelmed all previous selling in one move —
# a strong reversal signal — vote BUY.
class BullishEngulfingBuy(BaseStrategy):
    name = "B12_BullishEngulfing"; category = "swing"
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (prev["close"] < prev["open"] and curr["close"] > curr["open"] and
                curr["open"] < prev["close"] and curr["close"] > prev["open"]):
            return self._buy(0.77, "Bullish engulfing pattern")
        return self._no_signal()


# B13 — Bollinger Squeeze Breakout Buy
# When Bollinger Bands narrow (squeeze), volatility is compressed.
# When price then breaks above the upper band, the compressed energy
# releases upward — the start of a strong move — vote BUY.
class BollingerSqueezeBuy(BaseStrategy):
    name = "B13_BollingerSqueezeBuy"; category = "swing"
    def __init__(self, period=20, squeeze_threshold=0.05):
        self.period, self.squeeze_threshold = period, squeeze_threshold
    def evaluate(self, df):
        if len(df) < self.period + 5: return self._no_signal()
        bb = compute_bbands(df["close"], self.period)
        squeezed = (bb.bandwidth.iloc[-5:-1] < self.squeeze_threshold).all()
        if squeezed and df["close"].iloc[-1] > bb.upper.iloc[-1]:
            return self._buy(0.80, "Bollinger squeeze bullish breakout")
        return self._no_signal()


# B14 — Higher Lows Pattern Buy
# Every bar is making a higher high and higher low than the one before.
# This is the textbook definition of an uptrend — confirmed momentum
# across multiple bars — vote BUY.
class HigherLowsBuy(BaseStrategy):
    name = "B14_HigherLowsPattern"; category = "swing"
    def __init__(self, lookback=5):
        self.lookback = lookback
    def evaluate(self, df):
        if len(df) < self.lookback * 2: return self._no_signal()
        lows  = df["low"].iloc[-self.lookback:]
        highs = df["high"].iloc[-self.lookback:]
        if (all(lows.iloc[i] > lows.iloc[i-1] for i in range(1, len(lows))) and
                all(highs.iloc[i] > highs.iloc[i-1] for i in range(1, len(highs)))):
            return self._buy(0.72, f"Higher highs & lows over {self.lookback} bars")
        return self._no_signal()


# B15 — RSI Bullish Divergence Buy
# Price makes a lower low but RSI makes a higher low.
# This means sellers are getting weaker even as price falls —
# hidden strength that typically precedes a reversal — vote BUY.
class RSIBullishDivergenceBuy(BaseStrategy):
    name = "B15_RSIBullishDivergence"; category = "swing"
    def __init__(self, period=14, lookback=20):
        self.period, self.lookback = period, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + self.period: return self._no_signal()
        rsi   = compute_rsi(df["close"], self.period)
        price = df["close"]
        low_idx = price.iloc[-self.lookback:].idxmin()
        if price.iloc[-1] <= price[low_idx] and rsi.iloc[-1] > rsi[low_idx] and rsi.iloc[-1] < 40:
            return self._buy(0.82, "Bullish RSI divergence detected")
        return self._no_signal()


# B16 — Morning Star Buy
# Three candles tell the story: Bar 1 strong selling, Bar 2 indecision,
# Bar 3 strong buying that closes above Bar 1 midpoint.
# This is a complete seller exhaustion pattern — vote BUY.
class MorningStarBuy(BaseStrategy):
    name = "B16_MorningStar"; category = "swing"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal()
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if (c1["close"] < c1["open"] and
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and
                c3["close"] > c3["open"] and
                c3["close"] > (c1["open"] + c1["close"]) / 2):
            return self._buy(0.78, "Morning Star reversal pattern")
        return self._no_signal()


# B17 — Momentum Breakout Buy
# Price breaks to a new 20-bar high AND volume is above average.
# Volume confirmation means institutional buyers are participating —
# the breakout is genuine not a fake-out — vote BUY.
class MomentumBreakoutBuy(BaseStrategy):
    name = "B17_MomentumBreakout"; category = "scalp"
    def __init__(self, vol_mult=1.5, lookback=20):
        self.vol_mult, self.lookback = vol_mult, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + 2: return self._no_signal()
        avg_vol  = df["tick_volume"].iloc[-self.lookback:-1].mean()
        curr_vol = df["tick_volume"].iloc[-1]
        high_20  = df["high"].iloc[-self.lookback:-1].max()
        if df["close"].iloc[-1] > high_20 and curr_vol > self.vol_mult * avg_vol:
            return self._buy(0.83, f"Volume surge ({curr_vol:.0f} vs avg {avg_vol:.0f}) + breakout")
        return self._no_signal()


# B18 — Support Bounce Buy
# Calculates where price has historically found support (10th percentile low).
# When price returns to this zone and starts rising, buyers are stepping
# in at a proven level — market memory — vote BUY.
class SupportBounceBuy(BaseStrategy):
    name = "B18_SupportBounce"; category = "swing"
    def __init__(self, lookback=50, tolerance=0.002):
        self.lookback, self.tolerance = lookback, tolerance
    def evaluate(self, df):
        if len(df) < self.lookback: return self._no_signal()
        support = df["low"].iloc[-self.lookback:-5].quantile(0.1)
        price   = df["close"].iloc[-1]
        if abs(price - support) / support < self.tolerance and \
                df["close"].iloc[-1] > df["close"].iloc[-2]:
            return self._buy(0.70, f"Bouncing off support {support:.5f}")
        return self._no_signal()


# B19 — CCI Oversold Buy
# CCI measures how far price has deviated from its statistical average.
# When CCI drops below -100 (extreme low) then crosses back above it,
# the extreme is ending and price reverts upward — vote BUY.
class CCIOversoldBuy(BaseStrategy):
    name = "B19_CCIOversoldBuy"; category = "swing"
    def __init__(self, period=20, threshold=-100.0):
        self.period, self.threshold = period, threshold
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal()
        cci = compute_cci(df, self.period)
        if cci.iloc[-2] < self.threshold and cci.iloc[-1] >= self.threshold:
            return self._buy(0.71, f"CCI recovered from oversold ({self.threshold})")
        return self._no_signal()


# B20 — Golden Cross Buy
# The most famous long-term bullish signal in trading.
# When the 50 EMA (medium-term) crosses ABOVE the 200 EMA (long-term),
# it signals a major uptrend is starting — vote BUY.
class GoldenCrossBuy(BaseStrategy):
    name = "B20_GoldenCross"; category = "swing"
    def __init__(self, fast=50, slow=200):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data for 200 EMA")
        ef = compute_ema(df["close"], self.fast)
        es = compute_ema(df["close"], self.slow)
        if ef.iloc[-2] < es.iloc[-2] and ef.iloc[-1] >= es.iloc[-1]:
            return self._buy(0.85, "Golden Cross: 50 EMA crossed above 200 EMA")
        return self._no_signal()


# ── Strategy Registry ─────────────────────────────────────────────────────────
# This list registers all 20 buy strategies in one place.
# The strategy engine imports ALL_BUY_STRATEGIES and runs every
# strategy in this list on every price update automatically.
# To add a new strategy, create the class above and add it here.
ALL_BUY_STRATEGIES: list[BaseStrategy] = [
    RSIOversoldBounce(), MACDBullishCrossover(), EMABullishCrossover(),
    BollingerLowerTouchBuy(), PriceAbove200EMABuy(), StochasticOversoldBuy(),
    InsideBarBreakoutBuy(), HammerCandleBuy(), ADXTrendPullbackBuy(),
    VWAPBounceBuy(), TripleEMABuy(), BullishEngulfingBuy(),
    BollingerSqueezeBuy(), HigherLowsBuy(), RSIBullishDivergenceBuy(),
    MorningStarBuy(), MomentumBreakoutBuy(), SupportBounceBuy(),
    CCIOversoldBuy(), GoldenCrossBuy(),
]