"""
indicators/rsi.py
─────────────────
This file calculates the RSI (Relative Strength Index) indicator.
RSI measures whether a market has risen or fallen too far too fast.
It produces a single number between 0 and 100 for every candle:

  - Above 70 = overbought  (price has risen too fast, likely to pull back)
  - Below 30 = oversold    (price has fallen too fast, likely to bounce)
  - Around 50 = neutral    (no extreme condition, market is balanced)

RSI is one of the most widely used indicators in trading and is the
foundation of several strategies in this bot including B01, B05, B15,
S01, and S13.

Built using pure pandas and numpy — no external TA-Lib library needed.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculates Wilder's RSI for a price series.
    Returns a series of values between 0 and 100.
    Returns 50 (neutral) on candles where there is not enough data yet.
    Default period is 14 — the most widely used RSI setting in trading.

    How it works step by step:
      1. Calculate how much price changed from one candle to the next
      2. Separate the changes into gains (price went up) and losses (price went down)
      3. Calculate the average gain and average loss over the period
      4. RS = average gain divided by average loss
      5. RSI = 100 minus (100 divided by 1 plus RS)

    When there are many more gains than losses, RS is large and RSI approaches 100.
    When there are many more losses than gains, RS is small and RSI approaches 0.
    """
    # Step 1 — Calculate price change from one candle to the next
    # Positive value = price went up, negative value = price went down
    delta = series.diff()

    # Step 2a — Extract only the upward moves (gains)
    # clip(lower=0) sets all negative values to zero, keeping only gains
    gain = delta.clip(lower=0)

    # Step 2b — Extract only the downward moves (losses)
    # clip(upper=0) keeps only negative values, then negate to make them positive
    loss = -delta.clip(upper=0)

    # Step 3 — Calculate the average gain and average loss using Wilder smoothing
    # Wilder's smoothing uses alpha = 1/period (e.g. 1/14 = 0.0714)
    # min_periods=period means the first RSI value is only calculated after
    # enough candles have passed — earlier candles return NaN which becomes 50
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    # Step 4 — RS = average gain divided by average loss
    # replace(0, np.nan) prevents division by zero when there are no losses at all
    # (which would happen in a perfectly rising market)
    rs = avg_gain / avg_loss.replace(0, np.nan)

    # Step 5 — Convert RS into the RSI scale of 0 to 100
    # Formula: RSI = 100 - (100 / (1 + RS))
    # When RS is very high (many gains, few losses) → RSI approaches 100
    # When RS is very low (few gains, many losses) → RSI approaches 0
    rsi = 100 - (100 / (1 + rs))

    # Fill any NaN values with 50 (neutral) — these occur in the warmup period
    # before enough candles have accumulated for a valid RSI calculation
    return rsi.fillna(50)


def is_oversold(
    series: pd.Series,
    period: int     = 14,
    threshold: float = 30.0
) -> pd.Series:
    """
    Returns True for each candle where RSI is below the oversold threshold.
    Default threshold is 30 — the standard oversold level used in trading.
    When RSI is below 30, price has fallen too fast and a bounce is likely.
    Used as a condition check in several buy strategies including B01 and B05.
    """
    # Calculate RSI and check where it is below the threshold
    return compute_rsi(series, period) < threshold


def is_overbought(
    series: pd.Series,
    period: int     = 14,
    threshold: float = 70.0
) -> pd.Series:
    """
    Returns True for each candle where RSI is above the overbought threshold.
    Default threshold is 70 — the standard overbought level used in trading.
    When RSI is above 70, price has risen too fast and a pullback is likely.
    Used as a condition check in several sell strategies including S01 and S13.
    """
    # Calculate RSI and check where it is above the threshold
    return compute_rsi(series, period) > threshold