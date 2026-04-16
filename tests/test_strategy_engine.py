"""
tests/test_strategy_engine.py
─────────────────────────────
Tests for the StrategyEngine voting and aggregation logic.
We inject mock strategies so we can control exactly how many
votes each side gets.
"""

import pytest
import pandas as pd

from strategies.base    import BaseStrategy, Signal, StrategyResult
from services.strategy_engine import StrategyEngine, AggregatedSignal


# ── Mock strategies for controlled testing ────────────────────────────────────

class AlwaysBuy(BaseStrategy):
    name = "AlwaysBuy"
    def evaluate(self, df): return self._buy(0.90, "always buy")

class AlwaysSell(BaseStrategy):
    name = "AlwaysSell"
    def evaluate(self, df): return self._sell(0.90, "always sell")

class AlwaysNone(BaseStrategy):
    name = "AlwaysNone"
    def evaluate(self, df): return self._no_signal("always none")

class AlwaysError(BaseStrategy):
    name = "AlwaysError"
    def evaluate(self, df): raise ValueError("Simulated strategy crash")


@pytest.fixture
def sample_df():
    """Minimal valid OHLCV DataFrame."""
    n   = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    c   = pd.Series([1.10 + i * 0.001 for i in range(n)])
    return pd.DataFrame({
        "open":  c.shift(1).fillna(c.iloc[0]),
        "high":  c + 0.002, "low": c - 0.002,
        "close": c, "tick_volume": [1000.0] * n,
    }, index=idx)


# ── Core voting tests ─────────────────────────────────────────────────────────

class TestStrategyEngineVoting:

    def test_majority_buy_produces_buy_signal(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [AlwaysSell()],
            min_votes       = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)
        assert result.final_signal == Signal.BUY

    def test_majority_sell_produces_sell_signal(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy()],
            sell_strategies = [AlwaysSell(), AlwaysSell(), AlwaysSell()],
            min_votes       = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)
        assert result.final_signal == Signal.SELL

    def test_no_majority_produces_none_signal(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [AlwaysSell(), AlwaysSell()],
            min_votes       = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)
        assert result.final_signal == Signal.NONE

    def test_all_none_produces_none_signal(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysNone()],
            sell_strategies = [AlwaysNone()],
            min_votes       = 1,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)
        assert result.final_signal == Signal.NONE


# ── Vote counting ─────────────────────────────────────────────────────────────

class TestVoteCounting:

    def test_buy_votes_counted_correctly(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [AlwaysSell()],
            min_votes = 1, confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)
        assert result.buy_votes  == 3
        assert result.sell_votes == 1

    def test_total_evaluated_is_correct(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [AlwaysSell(), AlwaysSell(), AlwaysSell()],
            min_votes = 1, confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)
        assert result.total_evaluated == 5


# ── Error resilience ──────────────────────────────────────────────────────────

class TestEngineErrorHandling:

    def test_crashing_strategy_does_not_break_engine(self, sample_df):
        """Engine must catch individual strategy errors and continue."""
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy(), AlwaysError()],
            sell_strategies = [],
            min_votes = 3, confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)
        # Should still produce BUY from the 3 working strategies
        assert result.final_signal == Signal.BUY

    def test_all_strategies_crash_returns_none(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysError()],
            sell_strategies = [AlwaysError()],
            min_votes = 1, confidence_threshold = 0.0,
        )
        result = engine.evaluate(sample_df)
        assert result.final_signal == Signal.NONE


# ── AggregatedSignal structure ────────────────────────────────────────────────

class TestAggregatedSignalStructure:

    def test_result_has_all_fields(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [],
            min_votes = 3, confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)
        assert hasattr(result, "final_signal")
        assert hasattr(result, "confidence")
        assert hasattr(result, "buy_votes")
        assert hasattr(result, "sell_votes")
        assert hasattr(result, "none_votes")
        assert hasattr(result, "top_strategies")
        assert hasattr(result, "total_evaluated")

    def test_confidence_in_valid_range(self, sample_df):
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies = [],
            min_votes = 3, confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)
        assert 0.0 <= result.confidence <= 1.0