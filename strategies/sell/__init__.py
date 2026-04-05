"""
strategies/sell/__init__.py
───────────────────────────
All 20 sell strategies including pattern-based exits and risk exits.
"""

from __future__ import annotations
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, Signal
from indicators.rsi       import compute_rsi
from indicators.macd      import compute_macd, bearish_crossover
from indicators.ema       import compute_ema, ema_crossover_bearish
from indicators.bollinger import compute_bbands, touch_upper_band
from indicators.atr       import compute_stochastic, compute_adx, compute_vwap, compute_cci


class RSIOverboughtSell(BaseStrategy):
    """S01 – RSI peaks above overbought then reverts."""
    name = "S01_RSIOverboughtSell"; category = "swing"
    def __init__(self, period=14, overbought=70.0, revert=67.0):
        self.period, self.overbought, self.revert = period, overbought, revert
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal("insufficient data")
        rsi = compute_rsi(df["close"], self.period)
        if rsi.iloc[-2] > self.overbought and rsi.iloc[-1] <= self.revert:
            return self._sell(0.75, f"RSI reverting from {rsi.iloc[-2]:.1f}", rsi=round(rsi.iloc[-1],2))
        return self._no_signal()


class MACDBearishCrossover(BaseStrategy):
    """S02 – MACD line crosses below signal line."""
    name = "S02_MACDBearishCrossover"; category = "swing"
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast, self.slow, self.signal = fast, slow, signal
    def evaluate(self, df):
        if len(df) < self.slow + self.signal: return self._no_signal("insufficient data")
        if bearish_crossover(df["close"], fast=self.fast, slow=self.slow, signal_period=self.signal).iloc[-1]:
            r = compute_macd(df["close"], self.fast, self.slow, self.signal)
            return self._sell(0.80, "MACD crossed below signal", macd=round(r.macd.iloc[-1],6))
        return self._no_signal()


class EMABearishCrossover(BaseStrategy):
    """S03 – Fast EMA crosses below slow EMA."""
    name = "S03_EMABearishCrossover"; category = "swing"
    def __init__(self, fast=9, slow=21):
        self.fast, self.slow = fast, slow
    def evaluate(self, df):
        if len(df) < self.slow + 2: return self._no_signal("insufficient data")
        if ema_crossover_bearish(df["close"], self.fast, self.slow).iloc[-1]:
            return self._sell(0.72, f"EMA{self.fast} crossed below EMA{self.slow}")
        return self._no_signal()


class BollingerUpperTouchSell(BaseStrategy):
    """S04 – Price hits upper Bollinger Band then closes back inside."""
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


class StopLossTriggerSell(BaseStrategy):
    """S05 – Hard stop-loss: price drops X% below entry."""
    name = "S05_StopLossTrigger"; category = "risk"
    def __init__(self, stop_pct=0.02):
        self.stop_pct = stop_pct
        self.entry_price: float | None = None
    def set_entry(self, price: float) -> None:
        self.entry_price = price
    def evaluate(self, df):
        if self.entry_price is None: return self._no_signal("no entry set")
        current = df["close"].iloc[-1]
        drop = (self.entry_price - current) / self.entry_price
        if drop >= self.stop_pct:
            return self._sell(1.0, f"Stop-loss: {drop*100:.2f}% drop from {self.entry_price:.5f}")
        return self._no_signal()


class TrailingStopSell(BaseStrategy):
    """S06 – Trailing stop: price drops X% from peak."""
    name = "S06_TrailingStop"; category = "risk"
    def __init__(self, trail_pct=0.015):
        self.trail_pct = trail_pct
        self._peak: float | None = None
    def evaluate(self, df):
        price = df["close"].iloc[-1]
        if self._peak is None or price > self._peak:
            self._peak = price
        drop = (self._peak - price) / self._peak
        if drop >= self.trail_pct:
            return self._sell(0.95, f"Trailing stop: {drop*100:.2f}% from peak {self._peak:.5f}")
        return self._no_signal()


class StochasticOverboughtSell(BaseStrategy):
    """S07 – Stochastic %K crosses below %D in overbought zone."""
    name = "S07_StochasticOverboughtSell"; category = "scalp"
    def __init__(self, k=14, d=3, threshold=80.0):
        self.k, self.d, self.threshold = k, d, threshold
    def evaluate(self, df):
        if len(df) < self.k + self.d: return self._no_signal()
        k, d = compute_stochastic(df, self.k, self.d)
        if (k.iloc[-2] > d.iloc[-2]) and (k.iloc[-1] < d.iloc[-1]) and (k.iloc[-1] > self.threshold):
            return self._sell(0.73, f"Stoch K={k.iloc[-1]:.1f} crossed below D in overbought")
        return self._no_signal()


class InsideBarBreakdownSell(BaseStrategy):
    """S08 – Inside bar pattern with downside breakdown."""
    name = "S08_InsideBarBreakdownSell"; category = "scalp"
    def evaluate(self, df):
        if len(df) < 3: return self._no_signal()
        m, ins, cur = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        is_inside  = ins["high"] <= m["high"] and ins["low"] >= m["low"]
        breaks_down = cur["close"] < m["low"]
        if is_inside and breaks_down:
            return self._sell(0.68, "Inside bar bearish breakdown")
        return self._no_signal()


class ShootingStarSell(BaseStrategy):
    """S09 – Shooting star: small body, long upper shadow."""
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


class BearishEngulfingSell(BaseStrategy):
    """S10 – Bearish engulfing candlestick pattern."""
    name = "S10_BearishEngulfing"; category = "swing"
    def evaluate(self, df):
        if len(df) < 2: return self._no_signal()
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (prev["close"] > prev["open"] and curr["close"] < curr["open"] and
                curr["open"] > prev["close"] and curr["close"] < prev["open"]):
            return self._sell(0.77, "Bearish engulfing pattern")
        return self._no_signal()


class DeathCrossSell(BaseStrategy):
    """S11 – 50 EMA crosses below 200 EMA (Death Cross)."""
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


class VWAPRejectionSell(BaseStrategy):
    """S12 – Price fails to break above VWAP."""
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


class RSIBearishDivergenceSell(BaseStrategy):
    """S13 – Price makes higher high but RSI makes lower high."""
    name = "S13_RSIBearishDivergence"; category = "swing"
    def __init__(self, period=14, lookback=20):
        self.period, self.lookback = period, lookback
    def evaluate(self, df):
        if len(df) < self.lookback + self.period: return self._no_signal()
        rsi = compute_rsi(df["close"], self.period)
        price = df["close"]
        high_idx = price.iloc[-self.lookback:].idxmax()
        if price.iloc[-1] >= price[high_idx] and rsi.iloc[-1] < rsi[high_idx] and rsi.iloc[-1] > 60:
            return self._sell(0.82, "Bearish RSI divergence detected")
        return self._no_signal()


class EveningStarSell(BaseStrategy):
    """S14 – Three-candle evening star reversal pattern."""
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


class LowerHighsSell(BaseStrategy):
    """S15 – Consecutive lower highs and lower lows (downtrend structure)."""
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


class CCIOverboughtSell(BaseStrategy):
    """S16 – CCI crosses back below +100 from overbought territory."""
    name = "S16_CCIOverboughtSell"; category = "swing"
    def __init__(self, period=20, threshold=100.0):
        self.period, self.threshold = period, threshold
    def evaluate(self, df):
        if len(df) < self.period + 2: return self._no_signal()
        cci = compute_cci(df, self.period)
        if cci.iloc[-2] > self.threshold and cci.iloc[-1] <= self.threshold:
            return self._sell(0.71, f"CCI fell from overbought ({self.threshold})")
        return self._no_signal()


class MomentumBreakdownSell(BaseStrategy):
    """S17 – Volume surge + price breaks 20-bar low."""
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


class ResistanceRejectionSell(BaseStrategy):
    """S18 – Price rejected from historical resistance level."""
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


class BollingerSqueezeBreakdownSell(BaseStrategy):
    """S19 – Bollinger squeeze releases downward."""
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


class TakeProfitSell(BaseStrategy):
    """S20 – Take-profit target reached."""
    name = "S20_TakeProfitReached"; category = "risk"
    def __init__(self, target_pct=0.03):
        self.target_pct = target_pct
        self.entry_price: float | None = None
    def set_entry(self, price: float) -> None:
        self.entry_price = price
    def evaluate(self, df):
        if self.entry_price is None: return self._no_signal("no entry set")
        current = df["close"].iloc[-1]
        gain = (current - self.entry_price) / self.entry_price
        if gain >= self.target_pct:
            return self._sell(1.0, f"Take-profit: {gain*100:.2f}% gain from {self.entry_price:.5f}")
        return self._no_signal()


# ── Registry ──────────────────────────────────────────────────────────────────
ALL_SELL_STRATEGIES: list[BaseStrategy] = [
    RSIOverboughtSell(), MACDBearishCrossover(), EMABearishCrossover(),
    BollingerUpperTouchSell(), StopLossTriggerSell(), TrailingStopSell(),
    StochasticOverboughtSell(), InsideBarBreakdownSell(), ShootingStarSell(),
    BearishEngulfingSell(), DeathCrossSell(), VWAPRejectionSell(),
    RSIBearishDivergenceSell(), EveningStarSell(), LowerHighsSell(),
    CCIOverboughtSell(), MomentumBreakdownSell(), ResistanceRejectionSell(),
    BollingerSqueezeBreakdownSell(), TakeProfitSell(),
]
