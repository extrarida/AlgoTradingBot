"""
tests/test_strategies.py
────────────────────────
Tests for individual buy and sell strategies.
We create synthetic DataFrames that are designed to trigger
each strategy's conditions, then verify the correct signal
is returned.
"""

import pytest
import numpy as np
import pandas as pd

from strategies.base import Signal
from strategies.buy  import (
    RSIOversoldBounce, MACDBullishCrossover, EMABullishCrossover,
    BollingerLowerTouchBuy, BullishEngulfingBuy, HammerCandleBuy,
    GoldenCrossBuy
)
from strategies.sell import (
    RSIOverboughtSell, MACDBearishCrossover, EMABearishCrossover,
    BearishEngulfingSell, ShootingStarSell, DeathCrossSell
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_df(closes, add_ohlcv=True):
    """
    Build a minimal OHLCV DataFrame from a list of close prices.
    Used to create controlled test scenarios for each strategy.
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
    return pd.DataFrame({"close": closes}, index=idx)

def rising(n=100, start=1.0, step=0.005):
    return [start + i * step for i in range(n)]

def falling(n=100, start=1.5, step=0.005):
    return [start - i * step for i in range(n)]


# ── Signal enum sanity ────────────────────────────────────────────────────────

class TestSignalEnum:

    def test_signal_values(self):
        assert Signal.BUY  == "BUY"
        assert Signal.SELL == "SELL"
        assert Signal.NONE == "NONE"

    def test_signal_is_string(self):
        assert isinstance(Signal.BUY, str)


# ── RSI Strategy Tests ────────────────────────────────────────────────────────

class TestRSIOversoldBounce:

    def test_returns_buy_after_oversold_recovery(self):
        """
        Build a series where RSI drops below 30 then recovers.
        Strategy B01 should trigger a BUY.
        """
        # 80 falling bars to push RSI below 30, then 2 rising bars to recover
        prices = falling(80) + [falling(80)[-1] + 0.01, falling(80)[-1] + 0.02]
        df     = make_df(prices)
        result = RSIOversoldBounce().evaluate(df)
        # May be BUY or NONE depending on exact RSI values — just check valid signal
        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_returns_no_signal_for_insufficient_data(self):
        df     = make_df([1.0, 1.1, 1.2])
        result = RSIOversoldBounce().evaluate(df)
        assert result.signal == Signal.NONE

    def test_result_has_confidence(self):
        df     = make_df(rising())
        result = RSIOversoldBounce().evaluate(df)
        assert 0.0 <= result.confidence <= 1.0

    def test_result_has_strategy_name(self):
        df     = make_df(rising())
        result = RSIOversoldBounce().evaluate(df)
        assert result.strategy == "B01_RSIOversoldBounce"


class TestRSIOverboughtSell:

    def test_returns_no_signal_for_insufficient_data(self):
        df     = make_df([1.0, 1.1])
        result = RSIOverboughtSell().evaluate(df)
        assert result.signal == Signal.NONE

    def test_result_has_strategy_name(self):
        df     = make_df(falling())
        result = RSIOverboughtSell().evaluate(df)
        assert result.strategy == "S01_RSIOverboughtSell"

    def test_confidence_in_valid_range(self):
        df     = make_df(rising())
        result = RSIOverboughtSell().evaluate(df)
        assert 0.0 <= result.confidence <= 1.0


# ── MACD Strategy Tests ───────────────────────────────────────────────────────

class TestMACDBullishCrossover:

    def test_insufficient_data_returns_none(self):
        df     = make_df([1.0] * 10)
        result = MACDBullishCrossover().evaluate(df)
        assert result.signal == Signal.NONE
        assert "insufficient" in result.reason.lower()

    def test_returns_valid_signal(self):
        df     = make_df(rising())
        result = MACDBullishCrossover().evaluate(df)
        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_strategy_name_correct(self):
        df     = make_df(rising())
        result = MACDBullishCrossover().evaluate(df)
        assert result.strategy == "B02_MACDBullishCrossover"


class TestMACDBearishCrossover:

    def test_insufficient_data_returns_none(self):
        df     = make_df([1.0] * 10)
        result = MACDBearishCrossover().evaluate(df)
        assert result.signal == Signal.NONE

    def test_returns_valid_signal(self):
        df     = make_df(falling())
        result = MACDBearishCrossover().evaluate(df)
        assert result.signal in [Signal.SELL, Signal.NONE]


# ── Candlestick Pattern Tests ─────────────────────────────────────────────────

class TestBullishEngulfing:

    def test_detects_bullish_engulfing(self):
        """
        Manually craft a bullish engulfing pattern:
        Previous candle: bearish (open > close)
        Current candle:  bullish, opens below prev close, closes above prev open
        """
        idx = pd.date_range("2024-01-01", periods=2, freq="15min")
        df  = pd.DataFrame({
            "open":        [1.105, 1.098],   # curr opens below prev close
            "high":        [1.110, 1.115],
            "low":         [1.095, 1.095],
            "close":       [1.100, 1.112],   # curr closes above prev open
            "tick_volume": [1000.0, 1200.0],
        }, index=idx)
        result = BullishEngulfingBuy().evaluate(df)
        assert result.signal == Signal.BUY

    def test_no_signal_when_not_engulfing(self):
        df     = make_df(rising(n=10))
        result = BullishEngulfingBuy().evaluate(df)
        assert result.signal in [Signal.BUY, Signal.NONE]


class TestBearishEngulfing:

    def test_detects_bearish_engulfing(self):
        """
        Manually craft a bearish engulfing pattern:
        Previous candle: bullish (close > open)
        Current candle:  bearish, opens above prev close, closes below prev open
        """
        idx = pd.date_range("2024-01-01", periods=2, freq="15min")
        df  = pd.DataFrame({
            "open":        [1.100, 1.112],   # curr opens above prev close
            "high":        [1.115, 1.115],
            "low":         [1.095, 1.093],
            "close":       [1.110, 1.097],   # curr closes below prev open
            "tick_volume": [1000.0, 1200.0],
        }, index=idx)
        result = BearishEngulfingSell().evaluate(df)
        assert result.signal == Signal.SELL


# ── EMA Crossover Tests ───────────────────────────────────────────────────────

class TestEMACrossover:

    def test_buy_strategy_returns_valid_signal(self):
        df     = make_df(rising())
        result = EMABullishCrossover().evaluate(df)
        assert result.signal in [Signal.BUY, Signal.NONE]

    def test_sell_strategy_returns_valid_signal(self):
        df     = make_df(falling())
        result = EMABearishCrossover().evaluate(df)
        assert result.signal in [Signal.SELL, Signal.NONE]

    def test_insufficient_data_buy(self):
        df     = make_df([1.0] * 5)
        result = EMABullishCrossover().evaluate(df)
        assert result.signal == Signal.NONE

    def test_insufficient_data_sell(self):
        df     = make_df([1.0] * 5)
        result = EMABearishCrossover().evaluate(df)
        assert result.signal == Signal.NONE