"""
indicators/atr.py
─────────────────
ATR, Stochastic Oscillator, ADX, and daily VWAP.
All computed from raw OHLCV DataFrames – no TA-Lib required.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range. df must have high, low, close columns."""
    h, l, c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """Stochastic %K and %D."""
    ll = df["low"].rolling(k_period).min()
    hh = df["high"].rolling(k_period).max()
    k  = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    d  = k.rolling(d_period).mean()
    return k, d


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (trend strength; >25 = strong trend)."""
    h, l, c = df["high"], df["low"], df["close"]
    plus_dm  = (h.diff()).clip(lower=0)
    minus_dm = (-l.diff()).clip(lower=0)
    plus_dm[plus_dm  < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    atr      = compute_atr(df, period)
    plus_di  = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    dx       = (100 * (plus_di - minus_di).abs() /
                (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=1/period, adjust=False).mean()


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Daily VWAP that resets every session.
    df must have high, low, close, tick_volume columns with DatetimeIndex.
    """
    tp      = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["tick_volume"]
    dates   = df.index.date
    cum_tpv = (tp * vol).groupby(dates).cumsum()
    cum_vol = vol.groupby(dates).cumsum()
    return cum_tpv / cum_vol.replace(0, float("nan"))


def compute_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0, float("nan")))
