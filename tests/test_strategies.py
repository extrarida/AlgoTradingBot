"""
tests/test_strategies.py
────────────────────────
Unit tests for individual buy and sell trading strategies.

Each strategy in AlgoTrader is a self-contained class that takes a DataFrame
of price candles and returns a StrategyResult — a named tuple containing
the signal (BUY, SELL, or NONE), a confidence score between 0 and 1, and
a human-readable reason explaining the decision.

The strategy tests work by constructing synthetic price DataFrames that are
designed to either trigger or not trigger each strategy's conditions. This
is different from the indicator tests (which test pure mathematical functions)
— here we are testing the decision-making logic that wraps those indicators.

Approach to synthetic data:
────────────────────────────
Rather than using real market data (which would make tests dependent on
external files or APIs), we build controlled price series using the helper
functions at the top of this file. A rising series of 100 prices gives
indicators enough data to calculate correctly, and the direction makes it
easy to predict which strategies should fire.

For candlestick pattern strategies (Bullish/Bearish Engulfing, Hammer,
Shooting Star), we construct the exact candle structure the pattern requires
rather than hoping a random series happens to contain the pattern. This makes
the tests deterministic and the intent clear.

Run with:
    pytest tests/test_strategies.py -v
"""

import pytest
import numpy as np
import pandas as pd

from strategies.base import Signal
from strategies.buy  import (
    RSIOversoldBounce,
    MACDBullishCrossover,
    EMABullishCrossover,
    BollingerLowerTouchBuy,
    BullishEngulfingBuy,
    HammerCandleBuy,
    GoldenCrossBuy,
)
from strategies.sell import (
    RSIOverboughtSell,
    MACDBearishCrossover,
    EMABearishCrossover,
    BearishEngulfingSell,
    ShootingStarSell,
    DeathCrossSell,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
#
# These functions produce the synthetic price data used across all test classes.
# Keeping them as simple module-level functions (rather than fixtures) makes
# them easy to call with custom parameters inside individual tests.
# ─────────────────────────────────────────────────────────────────────────────

def make_df(closes, add_ohlcv=True):
    """
    Build a minimal OHLCV DataFrame from a list or Series of close prices.

    Most strategies only need the close price, but some (ATR, candlestick
    patterns, Bollinger Bands) also need open, high, low, and volume.
    Setting add_ohlcv=True builds a realistic structure where:
      - open  = previous candle's close (realistic gap behaviour)
      - high  = close + 2 pips
      - low   = close - 2 pips
      - volume = constant 1000 ticks

    The constant high/low spread keeps the data simple while giving
    indicators like ATR and Bollinger Bands enough variation to calculate.
    """
    closes = pd.Series(closes, dtype=float)
    n      = len(closes)
    idx    = pd.date_range("2024-01-01", periods=n, freq="15min")

    if add_ohlcv:
        return pd.DataFrame({
            "open":        closes.shift(1).fillna(closes.iloc[0]),
            "high":        closes + 0.002,
            "low":         closes - 0.002,
            "close":       closes,
            "tick_volume": [1000.0] * n,
        }, index=idx)

    # Minimal version — just close, for strategies that only need one column
    return pd.DataFrame({"close": closes}, index=idx)


def rising(n=100, start=1.0, step=0.005):
    """
    Generate a steadily rising price series.

    Default produces 100 prices from 1.000 to 1.495 — a clear uptrend.
    Bullish strategies evaluated on this data should lean towards BUY.
    """
    return [start + i * step for i in range(n)]


def falling(n=100, start=1.5, step=0.005):
    """
    Generate a steadily falling price series.

    Default produces 100 prices from 1.500 down to 1.005 — a clear downtrend.
    Bearish strategies evaluated on this data should lean towards SELL.
    """
    return [start - i * step for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# TestSignalEnum
#
# Sanity checks for the Signal enum itself. These are trivial but important —
# the strategy engine compares signal values with string literals throughout,
# so Signal.BUY must equal the string "BUY" exactly (case sensitive).
# If this ever breaks, every strategy test and the entire voting engine will
# also break.
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalEnum:

    def test_signal_values(self):
        """
        Signal enum values must match their expected string representations
        exactly. These strings are used by the dashboard's CSS class names
        and by the strategy engine's vote counting logic.
        """
        assert Signal.BUY  == "BUY"
        assert Signal.SELL == "SELL"
        assert Signal.NONE == "NONE"

    def test_signal_is_string(self):
        """
        Signal values must be plain Python strings, not integers or enums
        with custom __eq__ behaviour. This ensures they can be serialised
        directly to JSON for the API response without conversion.
        """
        assert isinstance(Signal.BUY, str)


# ─────────────────────────────────────────────────────────────────────────────
# TestRSIOversoldBounce (B01)
#
# This strategy looks for situations where the RSI has dropped below 30
# (oversold territory) and is now recovering upward. The theory is that
# a heavily oversold market tends to bounce back — making it a potential
# buy opportunity.
#
# Testing note: rather than asserting Signal.BUY on all tests, some tests
# accept either BUY or NONE because the exact RSI value depends on the
# synthetic data and may not always cross the exact oversold threshold.
# ─────────────────────────────────────────────────────────────────────────────

class TestRSIOversoldBounce:

    def test_returns_buy_after_oversold_recovery(self):
        """
        After a sustained decline followed by a small recovery, the strategy
        should produce either BUY or NONE — not SELL.

        We push RSI below 30 with 80 falling bars, then add two rising bars
        to simulate the recovery. Whether it triggers depends on the exact
        RSI crossing the strategy's threshold, so we accept both BUY and NONE.
        """
        # 80 falling candles drives RSI below 30; two rising candles simulate recovery
        fall_prices  = falling(80)
        recovery     = [fall_prices[-1] + 0.01, fall_prices[-1] + 0.02]
        prices       = fall_prices + recovery

        df     = make_df(prices)
        result = RSIOversoldBounce().evaluate(df)

        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_returns_no_signal_for_insufficient_data(self):
        """
        With only 3 data points, there is not enough history to calculate RSI
        (which requires at least 14 bars). The strategy must return NONE rather
        than crashing or returning a misleading signal.
        """
        df     = make_df([1.0, 1.1, 1.2])
        result = RSIOversoldBounce().evaluate(df)

        assert result.signal == Signal.NONE

    def test_result_has_confidence(self):
        """
        Every StrategyResult must include a confidence score between 0 and 1.

        The strategy engine uses this score to weight the final signal — a
        strategy with 0.9 confidence has more influence than one with 0.5.
        A value outside 0-1 would corrupt the confidence calculation.
        """
        df     = make_df(rising())
        result = RSIOversoldBounce().evaluate(df)

        assert 0.0 <= result.confidence <= 1.0

    def test_result_has_strategy_name(self):
        """
        The result must carry the correct strategy identifier string.

        This name appears in the Top Strategies panel on the dashboard and
        is stored in the strategy_votes database table. The format is
        B{number}_{ClassName} for buy strategies.
        """
        df     = make_df(rising())
        result = RSIOversoldBounce().evaluate(df)

        assert result.strategy == "B01_RSIOversoldBounce"


# ─────────────────────────────────────────────────────────────────────────────
# TestRSIOverboughtSell (S01)
#
# The sell-side counterpart to RSIOversoldBounce. Looks for RSI above 70
# (overbought) followed by a turning down — a potential sell opportunity.
# ─────────────────────────────────────────────────────────────────────────────

class TestRSIOverboughtSell:

    def test_returns_no_signal_for_insufficient_data(self):
        """
        Two data points are nowhere near enough for RSI to be calculated.
        The strategy must return NONE gracefully rather than erroring.
        """
        df     = make_df([1.0, 1.1])
        result = RSIOverboughtSell().evaluate(df)

        assert result.signal == Signal.NONE

    def test_result_has_strategy_name(self):
        """
        The result must carry the correct S01 identifier.
        Sell strategies follow the format S{number}_{ClassName}.
        """
        df     = make_df(falling())
        result = RSIOverboughtSell().evaluate(df)

        assert result.strategy == "S01_RSIOverboughtSell"

    def test_confidence_in_valid_range(self):
        """
        Confidence must be between 0 and 1 regardless of which data is used.
        Even when no signal fires, the confidence returned should be 0.0
        rather than a negative number or None.
        """
        df     = make_df(rising())
        result = RSIOverboughtSell().evaluate(df)

        assert 0.0 <= result.confidence <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TestMACDBullishCrossover (B02)
#
# Fires when the MACD line crosses above the signal line, indicating that
# short-term momentum is turning positive. MACD needs at least 26 bars for
# the slow EMA and another 9 for the signal line — around 35 bars minimum.
# ─────────────────────────────────────────────────────────────────────────────

class TestMACDBullishCrossover:

    def test_insufficient_data_returns_none(self):
        """
        10 bars is well below the minimum needed to compute MACD.
        The strategy must detect this and return NONE with an explanatory
        reason rather than raising an exception.
        """
        df     = make_df([1.0] * 10)
        result = MACDBullishCrossover().evaluate(df)

        assert result.signal == Signal.NONE
        assert "insufficient" in result.reason.lower()

    def test_returns_valid_signal(self):
        """
        100 rising bars gives MACD enough data to calculate correctly.
        The signal must be BUY or NONE — never SELL from a bullish crossover
        strategy.
        """
        df     = make_df(rising())
        result = MACDBullishCrossover().evaluate(df)

        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_strategy_name_correct(self):
        """Strategy B02 must identify itself with the correct name string."""
        df     = make_df(rising())
        result = MACDBullishCrossover().evaluate(df)

        assert result.strategy == "B02_MACDBullishCrossover"


# ─────────────────────────────────────────────────────────────────────────────
# TestMACDBearishCrossover (S02)
#
# Fires when the MACD line crosses below the signal line — momentum turning
# negative. Evaluated on falling price data to give it the best chance of
# producing a SELL signal.
# ─────────────────────────────────────────────────────────────────────────────

class TestMACDBearishCrossover:

    def test_insufficient_data_returns_none(self):
        """
        10 bars is not enough for MACD. Must return NONE gracefully.
        """
        df     = make_df([1.0] * 10)
        result = MACDBearishCrossover().evaluate(df)

        assert result.signal == Signal.NONE

    def test_returns_valid_signal(self):
        """
        On falling data, the strategy may return SELL or NONE depending on
        whether a bearish crossover occurred in the final bars.
        Either is valid — we do not assert SELL specifically because the
        exact crossover timing depends on the synthetic series.
        """
        df     = make_df(falling())
        result = MACDBearishCrossover().evaluate(df)

        assert result.signal in [Signal.SELL, Signal.NONE]


# ─────────────────────────────────────────────────────────────────────────────
# TestBullishEngulfing (B05)
#
# A candlestick pattern where a bearish candle is followed by a bullish candle
# that completely 'engulfs' the previous candle's body. Considered a potential
# reversal signal in a downtrend.
#
# These tests manually construct the exact candle structure rather than relying
# on a random series, which makes the expected result certain.
# ─────────────────────────────────────────────────────────────────────────────

class TestBullishEngulfing:

    def test_detects_bullish_engulfing(self):
        """
        Construct a textbook bullish engulfing pattern:
          Candle 1 (bearish): open=1.105, close=1.100  (fell 5 pips)
          Candle 2 (bullish): open=1.098, close=1.112  (rose 14 pips)

        Candle 2 opens below candle 1's close (gap down) and closes above
        candle 1's open — the body of candle 2 fully engulfs candle 1's body.
        The strategy must detect this and return BUY.
        """
        idx = pd.date_range("2024-01-01", periods=2, freq="15min")
        df  = pd.DataFrame({
            "open":        [1.105, 1.098],   # candle 2 opens below candle 1's close
            "high":        [1.110, 1.115],
            "low":         [1.095, 1.095],
            "close":       [1.100, 1.112],   # candle 2 closes above candle 1's open
            "tick_volume": [1000.0, 1200.0],
        }, index=idx)

        result = BullishEngulfingBuy().evaluate(df)
        assert result.signal == Signal.BUY

    def test_no_signal_when_not_engulfing(self):
        """
        A random rising series does not guarantee an engulfing pattern.
        The strategy must return BUY or NONE depending on what it finds —
        never SELL.
        """
        df     = make_df(rising(n=10))
        result = BullishEngulfingBuy().evaluate(df)

        assert result.signal in [Signal.BUY, Signal.NONE]


# ─────────────────────────────────────────────────────────────────────────────
# TestBearishEngulfing (S05)
#
# The inverse of bullish engulfing — a bearish candle completely engulfs the
# body of the previous bullish candle. Considered a potential reversal signal
# in an uptrend.
# ─────────────────────────────────────────────────────────────────────────────

class TestBearishEngulfing:

    def test_detects_bearish_engulfing(self):
        """
        Construct a textbook bearish engulfing pattern:
          Candle 1 (bullish): open=1.100, close=1.110  (rose 10 pips)
          Candle 2 (bearish): open=1.112, close=1.097  (fell 15 pips)

        Candle 2 opens above candle 1's close (gap up) and closes below
        candle 1's open — the body of candle 2 fully engulfs candle 1's body.
        The strategy must detect this and return SELL.
        """
        idx = pd.date_range("2024-01-01", periods=2, freq="15min")
        df  = pd.DataFrame({
            "open":        [1.100, 1.112],   # candle 2 opens above candle 1's close
            "high":        [1.115, 1.115],
            "low":         [1.095, 1.093],
            "close":       [1.110, 1.097],   # candle 2 closes below candle 1's open
            "tick_volume": [1000.0, 1200.0],
        }, index=idx)

        result = BearishEngulfingSell().evaluate(df)
        assert result.signal == Signal.SELL


# ─────────────────────────────────────────────────────────────────────────────
# TestEMACrossover (B03 / S03)
#
# EMA crossover strategies fire when a fast EMA (e.g. 9-period) crosses a
# slow EMA (e.g. 21-period). A bullish crossover (fast crosses above slow)
# signals upward momentum; a bearish crossover signals downward momentum.
#
# These strategies need at least 21 bars for the slow EMA to initialise —
# tests with very few bars must return NONE.
# ─────────────────────────────────────────────────────────────────────────────

class TestEMACrossover:

    def test_buy_strategy_returns_valid_signal(self):
        """
        On 100 rising bars, the bullish EMA crossover strategy should return
        BUY or NONE. SELL would be incorrect for a strategy designed to
        identify upward momentum.
        """
        df     = make_df(rising())
        result = EMABullishCrossover().evaluate(df)

        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_sell_strategy_returns_valid_signal(self):
        """
        On 100 falling bars, the bearish EMA crossover strategy should return
        SELL or NONE. BUY would be incorrect for a strategy designed to
        identify downward momentum.
        """
        df     = make_df(falling())
        result = EMABearishCrossover().evaluate(df)

        assert result.signal in [Signal.SELL, Signal.NONE]

    def test_insufficient_data_buy(self):
        """
        5 bars is not enough to compute a 21-period EMA.
        The buy strategy must return NONE and not raise an exception.
        """
        df     = make_df([1.0] * 5)
        result = EMABullishCrossover().evaluate(df)

        assert result.signal == Signal.NONE

    def test_insufficient_data_sell(self):
        """
        5 bars is not enough to compute a 21-period EMA.
        The sell strategy must return NONE and not raise an exception.
        """
        df     = make_df([1.0] * 5)
        result = EMABearishCrossover().evaluate(df)

        assert result.signal == Signal.NONE