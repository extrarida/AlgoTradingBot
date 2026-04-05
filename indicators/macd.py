"""
indicators/macd.py
──────────────────
Moving Average Convergence Divergence.
"""

from __future__ import annotations
from typing import NamedTuple
import pandas as pd


class MACDResult(NamedTuple):
    macd:      pd.Series
    signal:    pd.Series
    histogram: pd.Series


def compute_macd(
    series:        pd.Series,
    fast:          int = 12,
    slow:          int = 26,
    signal_period: int = 9,
) -> MACDResult:
    ema_fast   = series.ewm(span=fast,   adjust=False).mean()
    ema_slow   = series.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram  = macd_line - signal_line
    return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)


def bullish_crossover(series: pd.Series, **kw) -> pd.Series:
    """True at bars where MACD crosses above signal."""
    r = compute_macd(series, **kw)
    return (r.macd.shift(1) < r.signal.shift(1)) & (r.macd >= r.signal)


def bearish_crossover(series: pd.Series, **kw) -> pd.Series:
    """True at bars where MACD crosses below signal."""
    r = compute_macd(series, **kw)
    return (r.macd.shift(1) > r.signal.shift(1)) & (r.macd <= r.signal)
