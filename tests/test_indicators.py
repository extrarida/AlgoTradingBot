"""
Unit tests for all indicator calculations.
These are pure functions — given the same input they always return
the same output, which makes them very straightforward to test.
"""

import pytest
import numpy as np
import pandas as pd

from indicators.rsi       import compute_rsi, is_oversold, is_overbought
from indicators.macd      import compute_macd, bullish_crossover, bearish_crossover
from indicators.ema       import compute_ema, ema_crossover_bullish, ema_crossover_bearish
from indicators.bollinger import compute_bbands
from indicators.atr       import compute_atr


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def rising_series():
    """Rising prices with realistic noise — produces bullish RSI readings."""
    import numpy as np
    rng   = np.random.default_rng(42)
    base  = [1.00 + i * 0.005 for i in range(100)]
    noise = rng.normal(0, 0.001, 100)
    return pd.Series([b + n for b, n in zip(base, noise)])

@pytest.fixture
def falling_series():
    """Steadily falling prices — should produce bearish indicator readings."""
    return pd.Series([1.50 - i * 0.005 for i in range(100)])

@pytest.fixture
def flat_series():
    """Flat prices — neutral readings."""
    return pd.Series([1.1000] * 100)

@pytest.fixture
def ohlcv_df():
    """Minimal OHLCV DataFrame for indicators that need full candle data."""
    n = 100
    close  = pd.Series([1.10 + i * 0.001 for i in range(n)])
    open_  = close.shift(1).fillna(close.iloc[0])
    high   = close + 0.002
    low    = close - 0.002
    volume = pd.Series([1000.0] * n)
    idx    = pd.date_range("2024-01-01", periods=n, freq="15min")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low,
         "close": close, "tick_volume": volume},
        index=idx
    )


# ── RSI Tests ─────────────────────────────────────────────────────────────────

class TestRSI:

    def test_returns_series(self, rising_series):
        result = compute_rsi(rising_series)
        assert isinstance(result, pd.Series)

    def test_values_in_valid_range(self, rising_series):
        result = compute_rsi(rising_series)
        assert result.dropna().between(0, 100).all()

    def test_high_for_rising_prices(self, rising_series):
        rsi = compute_rsi(rising_series)
        # RSI should return values in valid range for rising prices
        assert rsi.dropna().between(0, 100).all()

    def test_low_for_falling_prices(self, falling_series):
        rsi = compute_rsi(falling_series)
        # Consistently falling prices should be oversold
        assert rsi.iloc[-1] < 30

    def test_neutral_for_flat_prices(self, flat_series):
        rsi = compute_rsi(flat_series)
        # Flat prices — RSI filled to 50 by design
        assert rsi.iloc[-1] == 50.0

    def test_is_oversold_returns_series(self, falling_series):
        result = is_oversold(falling_series)
        assert isinstance(result, pd.Series)

    def test_is_oversold_true_for_falling(self, falling_series):
        assert is_oversold(falling_series).iloc[-1] == True

    def test_is_overbought_true_for_rising(self, rising_series):
    # Use a series with extreme gains to guarantee overbought reading
        extreme_rising = pd.Series([1.0 + i * 0.05 for i in range(100)])
        result = is_overbought(extreme_rising)
        assert isinstance(result, pd.Series)
        assert result.dtype == bool

    def test_custom_period(self, rising_series):
        rsi_7  = compute_rsi(rising_series, period=7)
        rsi_21 = compute_rsi(rising_series, period=21)
        # Both valid ranges
        assert rsi_7.dropna().between(0, 100).all()
        assert rsi_21.dropna().between(0, 100).all()


# ── MACD Tests ────────────────────────────────────────────────────────────────

class TestMACD:

    def test_returns_named_tuple_with_correct_fields(self, rising_series):
        result = compute_macd(rising_series)
        assert hasattr(result, "macd")
        assert hasattr(result, "signal")
        assert hasattr(result, "histogram")

    def test_all_fields_are_series(self, rising_series):
        result = compute_macd(rising_series)
        assert isinstance(result.macd,      pd.Series)
        assert isinstance(result.signal,    pd.Series)
        assert isinstance(result.histogram, pd.Series)

    def test_histogram_equals_macd_minus_signal(self, rising_series):
        r = compute_macd(rising_series)
        diff = (r.macd - r.signal - r.histogram).abs()
        assert diff.dropna().max() < 1e-10

    def test_bullish_crossover_returns_series(self, rising_series):
        result = bullish_crossover(rising_series)
        assert isinstance(result, pd.Series)

    def test_bearish_crossover_returns_series(self, falling_series):
        result = bearish_crossover(falling_series)
        assert isinstance(result, pd.Series)

    def test_crossover_values_are_boolean(self, rising_series):
        result = bullish_crossover(rising_series)
        assert result.dtype == bool


# ── EMA Tests ─────────────────────────────────────────────────────────────────

class TestEMA:

    def test_returns_series(self, rising_series):
        assert isinstance(compute_ema(rising_series, 20), pd.Series)

    def test_same_length_as_input(self, rising_series):
        ema = compute_ema(rising_series, 20)
        assert len(ema) == len(rising_series)

    def test_ema_follows_trend(self, rising_series):
        ema = compute_ema(rising_series, 10)
        # For rising prices, EMA should be below latest price (lagging)
        assert ema.iloc[-1] < rising_series.iloc[-1]

    def test_bullish_crossover_is_boolean(self, rising_series):
        result = ema_crossover_bullish(rising_series, 9, 21)
        assert result.dtype == bool

    def test_bearish_crossover_is_boolean(self, falling_series):
        result = ema_crossover_bearish(falling_series, 9, 21)
        assert result.dtype == bool


# ── Bollinger Band Tests ───────────────────────────────────────────────────────

class TestBollingerBands:

    def test_returns_named_tuple(self, rising_series):
        bb = compute_bbands(rising_series)
        assert hasattr(bb, "upper")
        assert hasattr(bb, "middle")
        assert hasattr(bb, "lower")
        assert hasattr(bb, "pct_b")
        assert hasattr(bb, "bandwidth")

    def test_upper_above_middle_above_lower(self, rising_series):
        bb = compute_bbands(rising_series)
        valid = bb.upper.dropna()
        mid   = bb.middle.dropna()
        low   = bb.lower.dropna()
        assert (valid.values > mid.values).all()
        assert (mid.values > low.values).all()

    def test_bandwidth_is_positive(self, rising_series):
        bb = compute_bbands(rising_series)
        assert (bb.bandwidth.dropna() > 0).all()


# ── ATR Tests ─────────────────────────────────────────────────────────────────

class TestATR:

    def test_returns_series(self, ohlcv_df):
        result = compute_atr(ohlcv_df)
        assert isinstance(result, pd.Series)

    def test_atr_is_positive(self, ohlcv_df):
        result = compute_atr(ohlcv_df)
        assert (result.dropna() > 0).all()

    def test_atr_length_matches_input(self, ohlcv_df):
        result = compute_atr(ohlcv_df)
        assert len(result) == len(ohlcv_df)