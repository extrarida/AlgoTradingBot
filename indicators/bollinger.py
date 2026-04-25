"""
indicators/bollinger.py
───────────────────────
This file calculates Bollinger Bands and related helper functions.
Bollinger Bands draw three lines around a price chart:
  - A middle line (the average price)
  - An upper line (average + 2 standard deviations above)
  - A lower line (average - 2 standard deviations below)
When price touches the upper band it has moved unusually far up.
When price touches the lower band it has moved unusually far down.
This file also provides two extra measurements:
  - %B  (percent B)  → where exactly is price within the bands right now
  - Bandwidth        → how wide the bands are (measures volatility / squeeze)
"""

from __future__ import annotations
from typing import NamedTuple
import pandas as pd


# ── BBands result container ───────────────────────────────────────────────────
# This is a named tuple — a simple container that holds all five
# Bollinger Band values together so they can be returned in one object.
# Instead of returning five separate series, we return one BBands object
# and access each value by name e.g. bb.upper, bb.lower, bb.bandwidth.
class BBands(NamedTuple):
    upper:     pd.Series   # upper band = middle + (2 × standard deviation)
    middle:    pd.Series   # middle band = simple moving average of price
    lower:     pd.Series   # lower band = middle - (2 × standard deviation)
    pct_b:     pd.Series   # %B: 0 = at lower band, 0.5 = at middle, 1 = at upper band
    bandwidth: pd.Series   # how wide the bands are relative to the middle line


def compute_bbands(
    series:  pd.Series,
    period:  int   = 20,     # number of candles to look back (default 20)
    std_dev: float = 2.0,    # how many standard deviations wide the bands are
) -> BBands:
    """
    Calculates all five Bollinger Band values for a price series.
    Returns a BBands object containing upper, middle, lower, pct_b, bandwidth.

    Example usage:
      bb = compute_bbands(df["close"], period=20, std_dev=2.0)
      bb.upper   → the upper band values
      bb.lower   → the lower band values
      bb.pct_b   → where price sits within the bands (0 to 1)
    """
    # Middle band = simple moving average of the last 20 closing prices
    # This is the baseline "fair value" line that the other bands are built from
    middle = series.rolling(period).mean()

    # Standard deviation measures how spread out prices are from the average
    # A high std means prices are jumping around a lot (volatile market)
    # A low std means prices are staying close to the average (calm market)
    std = series.rolling(period).std()

    # Upper band = average + (2 × standard deviation)
    # Statistically, price should stay below this line about 95% of the time
    upper = middle + std_dev * std

    # Lower band = average - (2 × standard deviation)
    # Statistically, price should stay above this line about 95% of the time
    lower = middle - std_dev * std

    # Band range = distance between upper and lower band
    # replace(0, nan) prevents division by zero if bands somehow collapse to same value
    band_range = (upper - lower).replace(0, float("nan"))

    # %B = where is the current price sitting within the bands?
    # 0.0 means price is exactly at the lower band
    # 0.5 means price is exactly at the middle band
    # 1.0 means price is exactly at the upper band
    # Values above 1.0 or below 0.0 mean price has broken outside the bands
    pct_b = (series - lower) / band_range

    # Bandwidth = how wide the bands are as a proportion of the middle line
    # High bandwidth = bands are wide = market is volatile
    # Low bandwidth = bands are narrow = market is calm (squeeze condition)
    bandwidth = band_range / middle

    return BBands(upper, middle, lower, pct_b, bandwidth)


def touch_lower_band(
    series: pd.Series,
    period: int   = 20,
    std_dev: float = 2.0
) -> pd.Series:
    """
    Returns True for each candle where price touched or went below the lower band.
    Used by the Bollinger Lower Touch Buy strategy (B04) to detect oversold conditions.
    When price touches the lower band, it has moved statistically too far down
    and is likely to bounce back toward the middle — a potential buy signal.
    """
    # Calculate the bands first
    bb = compute_bbands(series, period, std_dev)

    # Return a boolean series — True where price is at or below the lower band
    return series <= bb.lower


def touch_upper_band(
    series: pd.Series,
    period: int   = 20,
    std_dev: float = 2.0
) -> pd.Series:
    """
    Returns True for each candle where price touched or went above the upper band.
    Used by the Bollinger Upper Touch Sell strategy (S04) to detect overbought conditions.
    When price touches the upper band, it has moved statistically too far up
    and is likely to pull back toward the middle — a potential sell signal.
    """
    # Calculate the bands first
    bb = compute_bbands(series, period, std_dev)

    # Return a boolean series — True where price is at or above the upper band
    return series >= bb.upper


def is_squeeze(
    series: pd.Series,
    period: int     = 20,
    threshold: float = 0.05
) -> pd.Series:
    """
    Returns True for each candle where the bands are unusually narrow (squeezed).
    A squeeze means the market has been very calm and low volatility for a while.
    This is significant because after a long period of calm, markets tend to make
    a sudden strong move in one direction — the squeeze releases like a coiled spring.
    Used by the Bollinger Squeeze strategies (B13 and S19) to detect this condition.
    threshold = 0.05 means bandwidth must be below 5% of the middle line to qualify.
    """
    # Calculate the full bands and check if bandwidth is below the squeeze threshold
    return compute_bbands(series, period).bandwidth < threshold