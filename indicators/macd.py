"""
indicators/macd.py
──────────────────
This file calculates the MACD indicator and detects crossover signals.
MACD stands for Moving Average Convergence Divergence.
It tracks the relationship between two moving averages of price
to measure whether buying or selling momentum is increasing or decreasing.

MACD produces three lines:
  - MACD Line    → the difference between a fast and slow moving average
  - Signal Line  → a smoothed version of the MACD line
  - Histogram    → the gap between the MACD line and Signal line

When the MACD line crosses ABOVE the Signal line → bullish momentum building → buy signal
When the MACD line crosses BELOW the Signal line → bearish momentum building → sell signal
"""

from __future__ import annotations
from typing import NamedTuple
import pandas as pd


# ── MACDResult container ──────────────────────────────────────────────────────
# A named tuple that holds all three MACD values together.
# Instead of returning three separate series, we return one MACDResult object.
# Access values by name: result.macd, result.signal, result.histogram
class MACDResult(NamedTuple):
    macd:      pd.Series   # the main MACD line (fast EMA minus slow EMA)
    signal:    pd.Series   # the signal line (smoothed MACD line)
    histogram: pd.Series   # the gap between MACD and signal (positive = bullish)


def compute_macd(
    series:        pd.Series,
    fast:          int = 12,   # fast EMA period — reacts quickly to price changes
    slow:          int = 26,   # slow EMA period — reacts slowly to price changes
    signal_period: int = 9,    # smoothing period for the signal line
) -> MACDResult:
    """
    Calculates the full MACD indicator for a price series.
    Returns a MACDResult object containing the MACD line, signal line,
    and histogram.

    Standard settings are 12, 26, 9 — the most widely used in trading.

    How it works:
      1. Calculate a fast EMA (12-period) — responds quickly to recent prices
      2. Calculate a slow EMA (26-period) — responds slowly, reflects longer trend
      3. MACD Line = fast EMA minus slow EMA
         → Positive means fast average is above slow (bullish momentum)
         → Negative means fast average is below slow (bearish momentum)
      4. Signal Line = 9-period EMA of the MACD line
         → A smoothed version that filters out noise
      5. Histogram = MACD Line minus Signal Line
         → Shows the distance between the two lines
         → Growing bars = momentum increasing, shrinking bars = momentum fading
    """
    # Step 1 — Calculate the fast EMA (reacts quickly to price changes)
    ema_fast = series.ewm(span=fast, adjust=False).mean()

    # Step 2 — Calculate the slow EMA (reacts slowly, shows longer trend)
    ema_slow = series.ewm(span=slow, adjust=False).mean()

    # Step 3 — MACD Line = fast EMA minus slow EMA
    # When positive: short-term momentum is above long-term momentum (bullish)
    # When negative: short-term momentum is below long-term momentum (bearish)
    macd_line = ema_fast - ema_slow

    # Step 4 — Signal Line = smoothed version of the MACD line
    # This line moves slower than the MACD line
    # Crossovers between MACD and Signal are the key trading signals
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

    # Step 5 — Histogram = MACD Line minus Signal Line
    # Positive histogram = MACD is above signal = bullish momentum
    # Negative histogram = MACD is below signal = bearish momentum
    # Growing histogram = momentum is strengthening
    # Shrinking histogram = momentum is weakening
    histogram = macd_line - signal_line

    return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)


def bullish_crossover(series: pd.Series, **kw) -> pd.Series:
    """
    Detects where the MACD line crosses ABOVE the signal line.
    This is a bullish crossover — buying momentum is taking over.
    Returns a boolean series — True on the exact candle where the cross happened.

    How the crossover is detected:
      - On the PREVIOUS candle: MACD was BELOW the signal line
      - On the CURRENT candle:  MACD is now ABOVE or equal to the signal line
      - Both conditions together = the bullish crossover just happened

    Used by strategy B02 (MACD Bullish Crossover) to generate buy signals.
    **kw allows custom fast, slow, signal_period values to be passed in.
    """
    # Calculate the full MACD result
    r = compute_macd(series, **kw)

    # shift(1) looks at the previous candle's values
    # Condition 1: on the previous candle, MACD was below the signal line
    # Condition 2: on the current candle, MACD is now at or above the signal line
    # Both must be True simultaneously for a valid bullish crossover
    return (r.macd.shift(1) < r.signal.shift(1)) & (r.macd >= r.signal)


def bearish_crossover(series: pd.Series, **kw) -> pd.Series:
    """
    Detects where the MACD line crosses BELOW the signal line.
    This is a bearish crossover — selling momentum is taking over.
    Returns a boolean series — True on the exact candle where the cross happened.

    How the crossover is detected:
      - On the PREVIOUS candle: MACD was ABOVE the signal line
      - On the CURRENT candle:  MACD is now BELOW or equal to the signal line
      - Both conditions together = the bearish crossover just happened

    Used by strategy S02 (MACD Bearish Crossover) to generate sell signals.
    **kw allows custom fast, slow, signal_period values to be passed in.
    """
    # Calculate the full MACD result
    r = compute_macd(series, **kw)

    # shift(1) looks at the previous candle's values
    # Condition 1: on the previous candle, MACD was above the signal line
    # Condition 2: on the current candle, MACD is now at or below the signal line
    # Both must be True simultaneously for a valid bearish crossover
    return (r.macd.shift(1) > r.signal.shift(1)) & (r.macd <= r.signal)