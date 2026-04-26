"""
indicators/rsi.py
─────────────────
Wilder's Relative Strength Index – pure pandas/numpy, no TA-Lib needed.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI using EMA of gains and losses.
    Returns values in [0, 100]. Returns 50 (neutral) on insufficient data.
    """
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi      = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def is_oversold(series: pd.Series, period: int = 14, threshold: float = 30.0) -> pd.Series:
    return compute_rsi(series, period) < threshold


def is_overbought(series: pd.Series, period: int = 14, threshold: float = 70.0) -> pd.Series:
    return compute_rsi(series, period) > threshold
