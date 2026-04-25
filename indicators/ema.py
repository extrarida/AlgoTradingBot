"""
indicators/ema.py
─────────────────
This file contains Exponential Moving Average (EMA) functions.
An EMA is a smoothed average of past prices that gives more weight
to recent prices than older ones — making it react faster to new
price movements compared to a simple average.

For example, a 9-period EMA reacts quickly to recent price changes.
A 200-period EMA moves very slowly and reflects the long-term trend.

Functions in this file:
  - compute_ema            → calculates the EMA line for any period
  - ema_crossover_bullish  → detects when fast EMA crosses above slow EMA (buy signal)
  - ema_crossover_bearish  → detects when fast EMA crosses below slow EMA (sell signal)
  - price_above_ema        → checks if price is above a given EMA (trend filter)
"""

from __future__ import annotations
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculates the Exponential Moving Average for a price series.
    More weight is given to recent prices so the line reacts faster
    to new market movements than a simple moving average would.

    span=period sets how many periods are used in the calculation.
    adjust=False uses the standard recursive EMA formula used in trading platforms.

    Example:
      compute_ema(df["close"], 9)   → fast EMA, reacts quickly to price changes
      compute_ema(df["close"], 200) → slow EMA, reflects the long-term trend
    """
    return series.ewm(span=period, adjust=False).mean()


def ema_crossover_bullish(
    series: pd.Series,
    fast: int = 9,
    slow: int = 21
) -> pd.Series:
    """
    Detects where the fast EMA crosses ABOVE the slow EMA.
    This is a bullish crossover — the short-term trend is turning upward.
    Returns a boolean series — True on the exact candle where the cross happened.

    How the crossover is detected:
      - On the PREVIOUS candle: fast EMA was BELOW slow EMA
      - On the CURRENT candle:  fast EMA is now ABOVE or equal to slow EMA
      - Both conditions together = the crossover just happened on this candle

    Used by strategy B03 (EMA Bullish Crossover) to generate buy signals.
    """
    # Calculate both EMA lines
    ef = compute_ema(series, fast)   # fast EMA e.g. 9-period
    es = compute_ema(series, slow)   # slow EMA e.g. 21-period

    # shift(1) looks at the previous candle's values
    # Condition 1: on the previous candle, fast was below slow (not yet crossed)
    # Condition 2: on the current candle, fast is now at or above slow (just crossed)
    # Both must be True at the same time for a valid crossover signal
    return (ef.shift(1) < es.shift(1)) & (ef >= es)


def ema_crossover_bearish(
    series: pd.Series,
    fast: int = 9,
    slow: int = 21
) -> pd.Series:
    """
    Detects where the fast EMA crosses BELOW the slow EMA.
    This is a bearish crossover — the short-term trend is turning downward.
    Returns a boolean series — True on the exact candle where the cross happened.

    How the crossover is detected:
      - On the PREVIOUS candle: fast EMA was ABOVE slow EMA
      - On the CURRENT candle:  fast EMA is now BELOW or equal to slow EMA
      - Both conditions together = the crossover just happened on this candle

    Used by strategy S03 (EMA Bearish Crossover) to generate sell signals.
    """
    # Calculate both EMA lines
    ef = compute_ema(series, fast)   # fast EMA e.g. 9-period
    es = compute_ema(series, slow)   # slow EMA e.g. 21-period

    # shift(1) looks at the previous candle's values
    # Condition 1: on the previous candle, fast was above slow (not yet crossed)
    # Condition 2: on the current candle, fast is now at or below slow (just crossed)
    # Both must be True at the same time for a valid crossover signal
    return (ef.shift(1) > es.shift(1)) & (ef <= es)


def price_above_ema(series: pd.Series, period: int = 200) -> pd.Series:
    """
    Returns True for each candle where the closing price is above the EMA.
    Used as a trend filter — if price is above the 200 EMA, the long-term
    trend is considered to be upward and only buy signals are considered.

    The 200-period EMA is the most widely watched long-term trend indicator.
    When price is above it, the market is in a long-term uptrend.
    When price is below it, the market is in a long-term downtrend.

    Used by strategy B05 (Price Above 200 EMA) to confirm the uptrend
    before entering a buy trade on a pullback.
    """
    # Simply compare each closing price to its corresponding EMA value
    # Returns True where price is above the EMA, False where it is below
    return series > compute_ema(series, period)