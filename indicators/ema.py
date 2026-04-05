"""
indicators/ema.py
─────────────────
Exponential Moving Average helpers.
"""

from __future__ import annotations
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def ema_crossover_bullish(series: pd.Series, fast: int = 9, slow: int = 21) -> pd.Series:
    """True where fast EMA crosses above slow EMA."""
    ef, es = compute_ema(series, fast), compute_ema(series, slow)
    return (ef.shift(1) < es.shift(1)) & (ef >= es)


def ema_crossover_bearish(series: pd.Series, fast: int = 9, slow: int = 21) -> pd.Series:
    """True where fast EMA crosses below slow EMA."""
    ef, es = compute_ema(series, fast), compute_ema(series, slow)
    return (ef.shift(1) > es.shift(1)) & (ef <= es)


def price_above_ema(series: pd.Series, period: int = 200) -> pd.Series:
    return series > compute_ema(series, period)
