"""
indicators/atr.py
─────────────────
This file contains five technical indicator functions used by the trading strategies.
All of them take price data as input and return a calculated series of values.
None of them require any external TA-Lib library — everything is built using
standard pandas and numpy operations.

Indicators in this file:
  - ATR  (Average True Range)      → measures market volatility
  - Stochastic                     → measures momentum / overbought / oversold
  - ADX  (Average Directional Index) → measures how strong the trend is
  - VWAP (Volume Weighted Avg Price) → measures fair value price for the day
  - CCI  (Commodity Channel Index)   → measures how far price is from its average
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ATR — Average True Range.
    Measures how much the market is moving on average over a given period.
    A high ATR means the market is volatile (big price swings).
    A low ATR means the market is calm (small price movements).
    Used by strategies to understand current market conditions.
    df must have high, low, close columns.
    """
    # Extract high, low, and the previous close price
    h = df["high"]
    l = df["low"]
    c = df["close"].shift(1)   # shift(1) means "the close from the previous candle"

    # True Range is the largest of these three measurements:
    #   1. Current high minus current low (normal candle size)
    #   2. Current high minus previous close (gap up scenario)
    #   3. Current low minus previous close (gap down scenario)
    # Taking the maximum captures the full price range including overnight gaps
    tr = pd.concat(
        [h - l,           # candle body size
         (h - c).abs(),   # distance from prev close to current high
         (l - c).abs()],  # distance from prev close to current low
        axis=1
    ).max(axis=1)

    # Smooth the True Range values using an exponential moving average
    # alpha = 1/period gives the standard Wilder smoothing used in ATR
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator — returns two lines: %K (fast) and %D (slow).
    Compares the current closing price to the range of prices over the past
    k_period candles. Scale is 0 to 100.
      - Above 80 means overbought (price near the top of its recent range)
      - Below 20 means oversold (price near the bottom of its recent range)
    Strategies use the crossover of K and D lines as entry signals.
    """
    # Lowest low over the past k_period candles
    ll = df["low"].rolling(k_period).min()

    # Highest high over the past k_period candles
    hh = df["high"].rolling(k_period).max()

    # %K = how far is current close from the recent low, as a percentage of the range
    # replace(0, np.nan) prevents division by zero when high equals low
    k = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)

    # %D = a smoothed version of %K using a rolling average
    # This is slower and less jumpy than %K
    d = k.rolling(d_period).mean()

    return k, d


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX — Average Directional Index.
    Measures how strong the current trend is, on a scale of 0 to 100.
    It does NOT tell you the direction — only the strength.
      - Above 25 means a strong trend is in place
      - Below 20 means the market is ranging with no clear direction
    Strategies like ADX Trend Pullback use this to confirm a trend is worth trading.
    """
    h = df["high"]
    l = df["low"]
    c = df["close"]

    # Plus Directional Movement (+DM): how much the high moved up from the previous candle
    plus_dm  = (h.diff()).clip(lower=0)

    # Minus Directional Movement (-DM): how much the low moved down from the previous candle
    minus_dm = (-l.diff()).clip(lower=0)

    # If the upward move is smaller than the downward move, the +DM is set to zero
    # If the downward move is smaller than the upward move, the -DM is set to zero
    # This ensures only the dominant direction is counted
    plus_dm[plus_dm   < minus_dm] = 0
    minus_dm[minus_dm < plus_dm]  = 0

    # Smooth both directional movements using ATR as a normaliser
    # This makes the values comparable regardless of the price level of the symbol
    atr      = compute_atr(df, period)
    plus_di  = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr

    # DX = how different the two directional movements are, as a percentage
    # A large difference means a strong trend — either up or down
    dx = (100 * (plus_di - minus_di).abs() /
          (plus_di + minus_di).replace(0, np.nan))

    # Smooth DX one more time to get the final ADX line
    return dx.ewm(alpha=1/period, adjust=False).mean()


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    VWAP — Volume Weighted Average Price.
    This is the average price weighted by how much volume traded at each level.
    It resets at the start of every new trading day.
    Institutional traders (banks, funds) use VWAP as a benchmark —
    they try to buy below VWAP and sell above it.
    When price dips to VWAP from above, it often acts as a support level.
    df must have high, low, close, tick_volume columns with a DatetimeIndex.
    """
    # Typical Price = average of high, low, and close for each candle
    # This is the standard way to represent the "middle" price of a candle
    tp = (df["high"] + df["low"] + df["close"]) / 3

    # Volume traded during each candle
    vol = df["tick_volume"]

    # Extract just the date portion of the datetime index
    # This is used to group candles by day so VWAP resets each session
    dates = df.index.date

    # Cumulative sum of (typical price × volume) — resets each day
    cum_tpv = (tp * vol).groupby(dates).cumsum()

    # Cumulative sum of volume — resets each day
    cum_vol = vol.groupby(dates).cumsum()

    # VWAP = running total of price×volume divided by running total of volume
    # replace(0, nan) prevents division by zero at the very start of each day
    return cum_tpv / cum_vol.replace(0, float("nan"))


def compute_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    CCI — Commodity Channel Index.
    Measures how far the current price has moved from its average over the period.
    Scale has no fixed bounds but common thresholds are:
      - Above +100 means price is unusually high (overbought)
      - Below -100 means price is unusually low (oversold)
    Strategies use CCI crossing back through these levels as reversal signals.
    """
    # Typical Price = average of high, low, and close for each candle
    tp = (df["high"] + df["low"] + df["close"]) / 3

    # Simple moving average of the typical price over the period
    sma = tp.rolling(period).mean()

    # Mean Absolute Deviation — average distance of each value from the mean
    # This measures how spread out the typical prices are around the average
    mad = tp.rolling(period).apply(
        lambda x: abs(x - x.mean()).mean(),
        raw=True
    )

    # CCI formula: deviation from average divided by a scaled MAD
    # 0.015 is a constant that scales the result so that ~70-80% of values
    # fall between -100 and +100 under normal market conditions
    # replace(0, nan) prevents division by zero when prices are perfectly flat
    return (tp - sma) / (0.015 * mad.replace(0, float("nan")))