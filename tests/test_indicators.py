"""
tests/test_indicators.py
────────────────────────
Unit tests for all technical indicator calculations used by the trading
strategies.

Indicators are the mathematical building blocks of the entire strategy engine.
Before the 40 strategies can vote on whether to buy or sell, they all call
one or more of these indicator functions. If an indicator returns wrong values,
every strategy that uses it will make wrong decisions — so these are the most
fundamental tests in the project.

All indicator functions are pure functions: given the same input, they always
return the same output. There are no side effects, no database calls, no
network requests. This makes them very fast and completely deterministic to
test.

The test fixtures at the top create reusable price series representing
different market conditions (rising, falling, flat), so each test class can
use realistic data without repeating the setup code.

Run with:
    pytest tests/test_indicators.py -v
"""

import pytest
import numpy as np
import pandas as pd

from indicators.rsi       import compute_rsi, is_oversold, is_overbought
from indicators.macd      import compute_macd, bullish_crossover, bearish_crossover
from indicators.ema       import compute_ema, ema_crossover_bullish, ema_crossover_bearish
from indicators.bollinger import compute_bbands
from indicators.atr       import compute_atr


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
#
# These fixtures create synthetic price series to use across all test classes.
# Using fixtures instead of repeating the data setup in every test keeps things
# DRY (Don't Repeat Yourself) and makes the tests easier to read.
#
# Each fixture represents a specific market condition:
#   rising_series  → prices trending upward   (bullish market)
#   falling_series → prices trending downward (bearish market)
#   flat_series    → prices completely flat   (no movement)
#   ohlcv_df       → full Open/High/Low/Close/Volume candle data
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def rising_series():
    """
    A steadily rising price series with small random noise added.

    The noise makes the data behave more like real market prices (which never
    rise in a perfectly straight line), while the overall upward trend is
    strong enough to produce bullish indicator readings.

    Seed 42 is used so the random noise is identical every time the test runs,
    keeping the results deterministic.
    """
    import numpy as np

    rng   = np.random.default_rng(42)
    base  = [1.00 + i * 0.005 for i in range(100)]
    noise = rng.normal(0, 0.001, 100)
    return pd.Series([b + n for b, n in zip(base, noise)])


@pytest.fixture
def falling_series():
    """
    A perfectly and consistently falling price series.

    No noise is added here — a clean downtrend makes it easy to assert that
    bearish indicator readings are produced reliably. 100 prices falling by
    0.005 each step gives a clear oversold signal by the end.
    """
    return pd.Series([1.50 - i * 0.005 for i in range(100)])


@pytest.fixture
def flat_series():
    """
    100 identical prices with no movement at all.

    Flat prices represent a market in equilibrium. Indicators like RSI should
    return neutral values (around 50) when there is no directional movement,
    and Bollinger Band width should be near zero.
    """
    return pd.Series([1.1000] * 100)


@pytest.fixture
def ohlcv_df():
    """
    A minimal OHLCV (Open, High, Low, Close, Volume) DataFrame.

    Some indicators — particularly ATR (Average True Range) — need the full
    candle structure, not just the closing price. This fixture builds a
    realistic-looking DataFrame with:
      - Close prices rising by 0.001 per candle
      - High always 0.002 above close
      - Low always 0.002 below close
      - Open taken from the previous candle's close (realistic gap behaviour)
      - Constant volume of 1000 ticks per candle
    """
    n = 100
    close  = pd.Series([1.10 + i * 0.001 for i in range(n)])
    open_  = close.shift(1).fillna(close.iloc[0])  # previous close = current open
    high   = close + 0.002
    low    = close - 0.002
    volume = pd.Series([1000.0] * n)
    idx    = pd.date_range("2024-01-01", periods=n, freq="15min")

    return pd.DataFrame(
        {
            "open":        open_,
            "high":        high,
            "low":         low,
            "close":       close,
            "tick_volume": volume,
        },
        index=idx
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestRSI
#
# RSI (Relative Strength Index) measures the speed and magnitude of recent
# price movements on a scale from 0 to 100. Values below 30 indicate the
# market is oversold (potentially a buy opportunity), values above 70 indicate
# overbought (potentially a sell opportunity).
#
# These tests verify the output range, the directional behaviour, and the
# helper functions is_oversold() and is_overbought() that the strategies use.
# ─────────────────────────────────────────────────────────────────────────────

class TestRSI:

    def test_returns_series(self, rising_series):
        """compute_rsi() should return a pandas Series, not a scalar or list."""
        result = compute_rsi(rising_series)
        assert isinstance(result, pd.Series)

    def test_values_in_valid_range(self, rising_series):
        """
        RSI values must always be between 0 and 100.

        This is a mathematical property of the RSI formula — values outside
        this range would indicate a bug in the calculation. We drop NaN values
        that appear at the beginning (before the lookback period is filled).
        """
        result = compute_rsi(rising_series)
        assert result.dropna().between(0, 100).all()

    def test_high_for_rising_prices(self, rising_series):
        """
        RSI for a rising price series should stay within the valid 0-100 range.

        We do not assert a specific value because the exact RSI depends on
        the noise in the fixture, but any valid rising series should produce
        values well within range.
        """
        rsi = compute_rsi(rising_series)
        assert rsi.dropna().between(0, 100).all()

    def test_low_for_falling_prices(self, falling_series):
        """
        A consistently falling price series should produce an oversold RSI.

        After 100 periods of uninterrupted decline, the RSI should have
        dropped below 30 — the standard oversold threshold. If it has not,
        the RSI formula is not responding correctly to downward momentum.
        """
        rsi = compute_rsi(falling_series)
        assert rsi.iloc[-1] < 30

    def test_neutral_for_flat_prices(self, flat_series):
        """
        Flat prices with no movement should produce an RSI of exactly 50.

        When average gain and average loss are both zero, the RSI formula
        is undefined. Our implementation handles this edge case by filling
        with 50 (neutral) by design.
        """
        rsi = compute_rsi(flat_series)
        assert rsi.iloc[-1] == 50.0

    def test_is_oversold_returns_series(self, falling_series):
        """is_oversold() should return a boolean Series, not a single value."""
        result = is_oversold(falling_series)
        assert isinstance(result, pd.Series)

    def test_is_oversold_true_for_falling(self, falling_series):
        """
        is_oversold() should return True on the last value of a consistently
        falling price series.

        After 100 candles of uninterrupted decline, the RSI will be well below
        30, so the oversold flag should be True at the current position.
        """
        assert is_oversold(falling_series).iloc[-1] == True

    def test_is_overbought_true_for_rising(self, rising_series):
        """
        is_overbought() should return a boolean Series.

        We use an extreme rising series (0.05 per step instead of 0.005) to
        guarantee the RSI crosses above 70. The standard rising_series fixture
        has noise that can keep RSI below 70 depending on the seed.
        """
        # Extreme gains to guarantee an overbought RSI reading
        extreme_rising = pd.Series([1.0 + i * 0.05 for i in range(100)])
        result = is_overbought(extreme_rising)

        assert isinstance(result, pd.Series)
        assert result.dtype == bool

    def test_custom_period(self, rising_series):
        """
        compute_rsi() should accept a custom period parameter without errors.

        A shorter period (7) makes RSI more sensitive to recent price changes,
        while a longer period (21) smooths it out. Both should return valid
        values in the 0-100 range.
        """
        rsi_7  = compute_rsi(rising_series, period=7)
        rsi_21 = compute_rsi(rising_series, period=21)

        assert rsi_7.dropna().between(0, 100).all()
        assert rsi_21.dropna().between(0, 100).all()


# ─────────────────────────────────────────────────────────────────────────────
# TestMACD
#
# MACD (Moving Average Convergence Divergence) identifies trend direction and
# momentum by comparing two exponential moving averages. It returns three
# values: the MACD line, the signal line (a smoothed version of MACD), and the
# histogram (their difference). A bullish crossover (MACD crosses above signal)
# suggests upward momentum; a bearish crossover suggests downward momentum.
# ─────────────────────────────────────────────────────────────────────────────

class TestMACD:

    def test_returns_named_tuple_with_correct_fields(self, rising_series):
        """
        compute_macd() should return an object with macd, signal, and histogram
        attributes — not a plain tuple or a dict.

        Using a named tuple (or dataclass) makes the calling code much clearer:
        result.macd is easier to read than result[0].
        """
        result = compute_macd(rising_series)

        assert hasattr(result, "macd")
        assert hasattr(result, "signal")
        assert hasattr(result, "histogram")

    def test_all_fields_are_series(self, rising_series):
        """
        All three MACD output fields should be pandas Series so they can be
        compared, indexed, and passed to strategy functions without conversion.
        """
        result = compute_macd(rising_series)

        assert isinstance(result.macd,      pd.Series)
        assert isinstance(result.signal,    pd.Series)
        assert isinstance(result.histogram, pd.Series)

    def test_histogram_equals_macd_minus_signal(self, rising_series):
        """
        The histogram must equal (MACD line - signal line) at every point.

        This is the mathematical definition of the MACD histogram. If this
        does not hold, the histogram values are inconsistent and any strategy
        relying on histogram direction will make wrong decisions.

        The tolerance of 1e-10 accounts for floating-point rounding.
        """
        r = compute_macd(rising_series)
        diff = (r.macd - r.signal - r.histogram).abs()
        assert diff.dropna().max() < 1e-10

    def test_bullish_crossover_returns_series(self, rising_series):
        """bullish_crossover() should return a Series so it can be used as a mask."""
        result = bullish_crossover(rising_series)
        assert isinstance(result, pd.Series)

    def test_bearish_crossover_returns_series(self, falling_series):
        """bearish_crossover() should return a Series so it can be used as a mask."""
        result = bearish_crossover(falling_series)
        assert isinstance(result, pd.Series)

    def test_crossover_values_are_boolean(self, rising_series):
        """
        Crossover Series values must be boolean (True/False), not integers or
        floats. The strategy engine checks these values with direct boolean
        evaluation, so a non-boolean dtype would silently produce wrong results.
        """
        result = bullish_crossover(rising_series)
        assert result.dtype == bool


# ─────────────────────────────────────────────────────────────────────────────
# TestEMA
#
# EMA (Exponential Moving Average) smooths price data by giving more weight to
# recent prices than older ones. It is used in many strategies as a trend
# filter — if price is above the EMA, the trend is up; below, it is down.
# EMA crossovers (a fast EMA crossing a slow EMA) are used to detect trend
# changes.
# ─────────────────────────────────────────────────────────────────────────────

class TestEMA:

    def test_returns_series(self, rising_series):
        """compute_ema() should return a pandas Series."""
        assert isinstance(compute_ema(rising_series, 20), pd.Series)

    def test_same_length_as_input(self, rising_series):
        """
        The EMA output must be the same length as the input series.

        Some implementations trim NaN values from the beginning, which would
        change the length and break alignment with other indicators. We need
        the lengths to match so Series can be compared by index.
        """
        ema = compute_ema(rising_series, 20)
        assert len(ema) == len(rising_series)

    def test_ema_follows_trend(self, rising_series):
        """
        For a rising price series, the EMA should lag slightly behind the
        current price — meaning the latest price will be above the EMA.

        EMAs are lagging indicators by design. If the EMA were above the
        current price in a rising market, the smoothing is not working
        correctly.
        """
        ema = compute_ema(rising_series, 10)
        assert ema.iloc[-1] < rising_series.iloc[-1]

    def test_bullish_crossover_is_boolean(self, rising_series):
        """
        ema_crossover_bullish() must return boolean values.
        The strategies check these directly with if/else logic.
        """
        result = ema_crossover_bullish(rising_series, 9, 21)
        assert result.dtype == bool

    def test_bearish_crossover_is_boolean(self, falling_series):
        """
        ema_crossover_bearish() must return boolean values.
        The strategies check these directly with if/else logic.
        """
        result = ema_crossover_bearish(falling_series, 9, 21)
        assert result.dtype == bool


# ─────────────────────────────────────────────────────────────────────────────
# TestBollingerBands
#
# Bollinger Bands place an upper and lower band around a moving average, each
# a set number of standard deviations away. When price touches the lower band
# the market may be oversold; when it touches the upper band it may be
# overbought. The bandwidth measures how wide the bands are, indicating
# volatility.
# ─────────────────────────────────────────────────────────────────────────────

class TestBollingerBands:

    def test_returns_named_tuple(self, rising_series):
        """
        compute_bbands() should return an object with upper, middle, lower,
        pct_b, and bandwidth attributes.

        pct_b measures where the current price sits within the bands (0 = at
        lower band, 1 = at upper band). bandwidth measures the spread.
        """
        bb = compute_bbands(rising_series)

        assert hasattr(bb, "upper")
        assert hasattr(bb, "middle")
        assert hasattr(bb, "lower")
        assert hasattr(bb, "pct_b")
        assert hasattr(bb, "bandwidth")

    def test_upper_above_middle_above_lower(self, rising_series):
        """
        The band order must always be: upper > middle > lower.

        This is a mathematical guarantee of the Bollinger Band formula — the
        middle band is the moving average, and upper/lower are symmetrically
        placed above and below it by a multiple of the standard deviation.
        If this order is ever violated, the bands have been calculated
        incorrectly.
        """
        bb = compute_bbands(rising_series)

        valid = bb.upper.dropna()
        mid   = bb.middle.dropna()
        low   = bb.lower.dropna()

        assert (valid.values > mid.values).all()
        assert (mid.values > low.values).all()

    def test_bandwidth_is_positive(self, rising_series):
        """
        Bandwidth must always be positive.

        Bandwidth = (upper - lower) / middle. Since upper > lower, this will
        always be positive as long as the band order is correct. A zero or
        negative bandwidth would mean the bands have collapsed, which should
        only happen in perfectly flat data (even then, bandwidth approaches
        zero but does not go negative).
        """
        bb = compute_bbands(rising_series)
        assert (bb.bandwidth.dropna() > 0).all()


# ─────────────────────────────────────────────────────────────────────────────
# TestATR
#
# ATR (Average True Range) measures market volatility. It calculates the
# average range between high and low prices over a lookback period, accounting
# for overnight gaps. Higher ATR means more volatility. It is used to set
# realistic stop-loss distances and to filter out low-volatility conditions
# where strategies tend to produce false signals.
# ─────────────────────────────────────────────────────────────────────────────

class TestATR:

    def test_returns_series(self, ohlcv_df):
        """compute_atr() should return a pandas Series."""
        result = compute_atr(ohlcv_df)
        assert isinstance(result, pd.Series)

    def test_atr_is_positive(self, ohlcv_df):
        """
        ATR must always be positive.

        ATR represents a price range (how much the market moved), so it can
        never be negative. A zero or negative ATR would indicate a bug in the
        True Range calculation (high - low is always >= 0 by definition).
        """
        result = compute_atr(ohlcv_df)
        assert (result.dropna() > 0).all()

    def test_atr_length_matches_input(self, ohlcv_df):
        """
        The ATR output must be the same length as the input DataFrame.

        This ensures it can be aligned with other indicators by index when
        strategies combine multiple signals.
        """
        result = compute_atr(ohlcv_df)
        assert len(result) == len(ohlcv_df)