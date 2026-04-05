"""
strategies/buy/__init__.py
──────────────────────────
All 20 buy strategies. Each is a self-contained, independently
testable class. The ALL_BUY_STRATEGIES list at the bottom is the
registry used by the strategy engine.
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
class RSIOversoldBounce(BaseStrategy):
    """B01 – RSI dips below oversold threshold then recovers."""
    name = "B01_RSIOversoldBounce"; category = "swing"
    def __init__(self, period=14, oversold=30.0, recover=33.0):
        self.period, self.oversold, self.recover = period, oversold, recover
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"], self.period)
        if rsi.iloc[-2] < self.oversold and rsi.iloc[-1] >= self.recover:
            return self._buy(0.75, f"RSI recovering from {rsi.iloc[-2]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


class MACDBullishCrossover(BaseStrategy):
    """B02 – MACD line crosses above signal line."""
    name = "B02_MACDBullishCrossover"; category = "swing"
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast, self.slow, self.signal = fast, slow, signal
    def evaluate(self, df):
        if len(df) < self.slow + self.signal: return self._no_signal("insufficient data")
        if bullish_crossover(df["close"], fast=self.fast, slow=self.slow, signal_period=self.signal).iloc[-1]:
            r = compute_macd(df["close"], self.fast, self.slow, self.signal)
            return self._buy(0.80, "MACD crossed above signal", macd=round(r.macd.iloc[-1],6))
        return self._no_signal()


class EMABullishCrossover(BaseStrategy):
    """B03 – Fast EMA crosses above slow EMA."""
    name = "B03_EMABullishCrossover"; category = "swing"
    def __init__(self, fast=9, slow=21):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        if ema_crossover_bullish(df["close"], self.fast, self.slow).iloc[-1]:
            return self._buy(0.72, f"EMA{self.fast} crossed above EMA{self.slow}")
        return self._no_signal()


class BollingerLowerTouchBuy(BaseStrategy):
    """B04 – Price touches lower Bollinger Band then closes back inside."""
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


class PriceAbove200EMABuy(BaseStrategy):
    """B05 – Price is above 200 EMA (uptrend) with RSI pullback."""
    name = "B05_PriceAbove200EMA"; category = "swing"
    def __init__(self, ema_period=200, rsi_threshold=40.0):
        self.ema_period, self.rsi_threshold = ema_period, rsi_threshold
    def evaluate(self, df):
        if len(df) < self.ema_period: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"])
        if price_above_ema(df["close"], self.ema_period).iloc[-1] and rsi.iloc[-1] < self.rsi_threshold:
            return self._buy(0.78, f"Uptrend pullback: RSI={rsi.iloc[-1]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


class StochasticOversoldBuy(BaseStrategy):
    """B06 – Stochastic %K crosses above %D in oversold zone."""
    name = "B06_StochasticOversoldBuy"; category = "scalp"
    def __init__(self, k=14, d=3, threshold=20.0):
        self.k, self.d, self.threshold = k, d, threshold
    def evaluate(self, df):
        if len(df) < self.k + self.d: return self._no_signal("insufficient data")
        k, d = compute_stochastic(df, self.k, self.d)
        if (k.iloc[-2] < d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]) and (k.iloc[-1] < self.threshold):
            return self._buy(0.73, f"Stoch K={k.iloc[-1]:.1f} crossed D in oversold")
        return self._no_signal()


class InsideBarBreakoutBuy(BaseStrategy):
    """B07 – Inside bar pattern with upside breakout."""
    name = "B07_InsideBarBreakoutBuy"; category = "scalp"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal("insufficient data")
        m, ins, cur = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        is_inside   = ins["high"] <= m["high"] and ins["low"] >= m["low"]
        breaks_up   = cur["close"] > m["high"]
        if is_inside and breaks_up:
            return self._buy(0.68, "Inside bar bullish breakout")
        return self._no_signal()


class HammerCandleBuy(BaseStrategy):
    """B08 – Hammer: small body, long lower shadow."""
    name = "B08_HammerCandle"; category = "swing"
    def __init__(self, body_ratio=0.3, shadow_ratio=2.0):
        self.body_ratio, self.shadow_ratio = body_ratio, shadow_ratio
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        r = df.iloc[-1]
        body = abs(r["close"] - r["open"])
        total = r["high"] - r["low"]
        lower = min(r["open"], r["close"]) - r["low"]
        upper = r["high"] - max(r["open"], r["close"])
        if total == 0: return self._no_signal()
        if (body < self.body_ratio * total and
                lower > self.shadow_ratio * body and upper <= body):
            return self._buy(0.65, "Hammer candlestick pattern")
        return self._no_signal()


class ADXTrendPullbackBuy(BaseStrategy):
    """B09 – Strong ADX uptrend with price pulling back to EMA."""
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


class VWAPBounceBuy(BaseStrategy):
    """B10 – Price bounces off VWAP from above (intraday scalp)."""
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


class TripleEMABuy(BaseStrategy):
    """B11 – Triple EMA bullish alignment with pullback to fast EMA."""
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


class BullishEngulfingBuy(BaseStrategy):
    """B12 – Bullish engulfing candlestick pattern."""
    name = "B12_BullishEngulfing"; category = "swing"
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (prev["close"] < prev["open"] and curr["close"] > curr["open"] and
                curr["open"] < prev["close"] and curr["close"] > prev["open"]):
            return self._buy(0.77, "Bullish engulfing pattern")
        return self._no_signal()


class BollingerSqueezeBuy(BaseStrategy):
    """B13 – Bollinger squeeze releases upward."""
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


class HigherLowsBuy(BaseStrategy):
    """B14 – Consecutive higher highs and higher lows (uptrend structure)."""
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


class RSIBullishDivergenceBuy(BaseStrategy):
    """B15 – Price makes lower low but RSI makes higher low."""
    name = "B15_RSIBullishDivergence"; category = "swing"
    def __init__(self, period=14, lookback=20):
        self.period, self.lookback = period, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + self.period: return self._no_signal()
        rsi = compute_rsi(df["close"], self.period)
        price = df["close"]
        low_idx = price.iloc[-self.lookback:].idxmin()
        if price.iloc[-1] <= price[low_idx] and rsi.iloc[-1] > rsi[low_idx] and rsi.iloc[-1] < 40:
            return self._buy(0.82, "Bullish RSI divergence detected")
        return self._no_signal()


class MorningStarBuy(BaseStrategy):
    """B16 – Three-candle morning star reversal pattern."""
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


class MomentumBreakoutBuy(BaseStrategy):
    """B17 – Volume surge + price breaks 20-bar high."""
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


class SupportBounceBuy(BaseStrategy):
    """B18 – Price bouncing off historical support level."""
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


class CCIOversoldBuy(BaseStrategy):
    """B19 – CCI crosses back above -100 from oversold territory."""
    name = "B19_CCIOversoldBuy"; category = "swing"
    def __init__(self, period=20, threshold=-100.0):
        self.period, self.threshold = period, threshold
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal()
        cci = compute_cci(df, self.period)
        if cci.iloc[-2] < self.threshold and cci.iloc[-1] >= self.threshold:
            return self._buy(0.71, f"CCI recovered from oversold ({self.threshold})")
        return self._no_signal()


class GoldenCrossBuy(BaseStrategy):
    """B20 – 50 EMA crosses above 200 EMA (Golden Cross)."""
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


# ── Registry ──────────────────────────────────────────────────────────────────
ALL_BUY_STRATEGIES: list[BaseStrategy] = [
    RSIOversoldBounce(), MACDBullishCrossover(), EMABullishCrossover(),
    BollingerLowerTouchBuy(), PriceAbove200EMABuy(), StochasticOversoldBuy(),
    InsideBarBreakoutBuy(), HammerCandleBuy(), ADXTrendPullbackBuy(),
    VWAPBounceBuy(), TripleEMABuy(), BullishEngulfingBuy(),
    BollingerSqueezeBuy(), HigherLowsBuy(), RSIBullishDivergenceBuy(),
    MorningStarBuy(), MomentumBreakoutBuy(), SupportBounceBuy(),
    CCIOversoldBuy(), GoldenCrossBuy(),
]
