"""
indicators/bollinger.py
───────────────────────
Bollinger Bands with %B and bandwidth helpers.
"""

from __future__ import annotations
from typing import NamedTuple
import pandas as pd


class BBands(NamedTuple):
    upper:     pd.Series
    middle:    pd.Series
    lower:     pd.Series
    pct_b:     pd.Series   # position within bands 0-1
    bandwidth: pd.Series   # (upper-lower)/middle


def compute_bbands(
    series:  pd.Series,
    period:  int   = 20,
    std_dev: float = 2.0,
) -> BBands:
    middle    = series.rolling(period).mean()
    std       = series.rolling(period).std()
    upper     = middle + std_dev * std
    lower     = middle - std_dev * std
    band_range = (upper - lower).replace(0, float("nan"))
    pct_b     = (series - lower) / band_range
    bandwidth = band_range / middle
    return BBands(upper, middle, lower, pct_b, bandwidth)


def touch_lower_band(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    bb = compute_bbands(series, period, std_dev)
    return series <= bb.lower


def touch_upper_band(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    bb = compute_bbands(series, period, std_dev)
    return series >= bb.upper


def is_squeeze(series: pd.Series, period: int = 20, threshold: float = 0.05) -> pd.Series:
    return compute_bbands(series, period).bandwidth < threshold
