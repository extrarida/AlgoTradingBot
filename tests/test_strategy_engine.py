"""
tests/test_strategy_engine.py
─────────────────────────────
Unit tests for the StrategyEngine — the component that aggregates votes from
all 40 strategies and decides the final trading signal.

The strategy engine is the most critical component in the application. It sits
between the individual strategies (which each have an opinion) and the trade
executor (which actually places orders). Its job is to collect all votes, count
them, calculate a confidence score, and decide whether the consensus is strong
enough to act on.

Why mock strategies?
─────────────────────
The real strategies depend on indicators, which depend on enough price history
to produce valid readings. Testing the engine with real strategies would mix
two concerns: whether the voting logic is correct, and whether the strategies
themselves return sensible signals.

Instead, we inject mock strategies that always return a fixed vote. This lets
us test the engine's aggregation logic with complete precision — for example,
we can say "given exactly 3 BUY votes and 1 SELL vote, the engine must return
BUY" without any ambiguity about what the strategies returned.

This technique is called dependency injection and is a standard approach for
testing components that depend on other components.

Run with:
    pytest tests/test_strategy_engine.py -v
"""

import pytest
import pandas as pd

from strategies.base      import BaseStrategy, Signal, StrategyResult
from services.strategy_engine import StrategyEngine, AggregatedSignal


# ─────────────────────────────────────────────────────────────────────────────
# Mock strategies
#
# These four classes cover every possible strategy outcome:
#
#   AlwaysBuy   → always returns BUY with high confidence
#   AlwaysSell  → always returns SELL with high confidence
#   AlwaysNone  → always abstains (no signal)
#   AlwaysError → always raises an exception (simulates a buggy strategy)
#
# Using 0.90 confidence for Buy/Sell makes the expected confidence values
# of the aggregated result easy to calculate and verify by hand.
# ─────────────────────────────────────────────────────────────────────────────

class AlwaysBuy(BaseStrategy):
    """Mock strategy that unconditionally votes BUY at 90% confidence."""
    name = "AlwaysBuy"

    def evaluate(self, df):
        return self._buy(0.90, "always buy")


class AlwaysSell(BaseStrategy):
    """Mock strategy that unconditionally votes SELL at 90% confidence."""
    name = "AlwaysSell"

    def evaluate(self, df):
        return self._sell(0.90, "always sell")


class AlwaysNone(BaseStrategy):
    """Mock strategy that always abstains — no opinion on market direction."""
    name = "AlwaysNone"

    def evaluate(self, df):
        return self._no_signal("always none")


class AlwaysError(BaseStrategy):
    """
    Mock strategy that always raises an exception.

    Used to test that the engine handles individual strategy failures
    gracefully — one broken strategy must not prevent the remaining
    strategies from running or the engine from returning a result.
    """
    name = "AlwaysError"

    def evaluate(self, df):
        raise ValueError("Simulated strategy crash")


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """
    A minimal but valid OHLCV DataFrame with 50 candles.

    The engine requires a DataFrame to pass to each strategy's evaluate()
    method. The mock strategies ignore the data entirely, but the engine
    still needs a valid DataFrame to call them with.

    50 candles is enough to prevent any index-out-of-bounds issues inside
    the engine, while being small enough to keep test runs fast.
    """
    n   = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    c   = pd.Series([1.10 + i * 0.001 for i in range(n)])

    return pd.DataFrame({
        "open":        c.shift(1).fillna(c.iloc[0]),
        "high":        c + 0.002,
        "low":         c - 0.002,
        "close":       c,
        "tick_volume": [1000.0] * n,
    }, index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# TestStrategyEngineVoting
#
# These tests verify the core decision logic: given a set of votes, does the
# engine produce the right final signal?
#
# The engine requires a minimum number of votes (min_votes) before acting on
# a signal, and also requires the winning side's confidence to exceed a
# threshold. These tests exercise different combinations of those conditions.
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategyEngineVoting:

    def test_majority_buy_produces_buy_signal(self, sample_df):
        """
        3 BUY votes against 1 SELL vote, with min_votes=3, should produce BUY.

        The buy side has enough votes to meet the minimum threshold, and has
        a clear majority. This is the most common scenario in which the bot
        places a buy order automatically.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [AlwaysSell()],
            min_votes            = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)

        assert result.final_signal == Signal.BUY

    def test_majority_sell_produces_sell_signal(self, sample_df):
        """
        1 BUY vote against 3 SELL votes, with min_votes=3, should produce SELL.

        The sell side has the majority and meets the minimum vote count.
        This is the scenario where the bot would place a sell order.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy()],
            sell_strategies      = [AlwaysSell(), AlwaysSell(), AlwaysSell()],
            min_votes            = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)

        assert result.final_signal == Signal.SELL

    def test_no_majority_produces_none_signal(self, sample_df):
        """
        2 BUY votes and 2 SELL votes with min_votes=3 must produce NONE.

        Neither side has enough votes to meet the minimum threshold, so the
        engine should abstain rather than flip a coin. The bot stays out of
        the market when there is no clear agreement.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [AlwaysSell(), AlwaysSell()],
            min_votes            = 3,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)

        assert result.final_signal == Signal.NONE

    def test_all_none_produces_none_signal(self, sample_df):
        """
        When all strategies abstain, the final signal must be NONE.

        Even with min_votes=1, if no strategy voted BUY or SELL, there is
        nothing to act on. This tests the edge case where the market is
        completely ambiguous and no strategy has a view.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysNone()],
            sell_strategies      = [AlwaysNone()],
            min_votes            = 1,
            confidence_threshold = 0.60,
        )
        result = engine.evaluate(sample_df)

        assert result.final_signal == Signal.NONE


# ─────────────────────────────────────────────────────────────────────────────
# TestVoteCounting
#
# Verifies that the engine counts and reports votes accurately. The vote counts
# are displayed on the dashboard's signal panel and stored in the database's
# signals table — incorrect counts would mislead the user about why a signal
# fired.
# ─────────────────────────────────────────────────────────────────────────────

class TestVoteCounting:

    def test_buy_votes_counted_correctly(self, sample_df):
        """
        With 3 AlwaysBuy strategies and 1 AlwaysSell strategy, the result
        must report buy_votes=3 and sell_votes=1 exactly.

        These vote counts appear on the dashboard (e.g. '3 Buy / 1 Sell /
        0 Hold') and in the database. If the counts are wrong, the user
        cannot understand why a particular signal was produced.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [AlwaysSell()],
            min_votes            = 1,
            confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)

        assert result.buy_votes  == 3
        assert result.sell_votes == 1

    def test_total_evaluated_is_correct(self, sample_df):
        """
        total_evaluated must equal the total number of strategies that ran,
        regardless of how they voted.

        With 2 buy strategies and 3 sell strategies, total_evaluated must be
        5. This is used in the dashboard to show 'X out of 40 strategies
        evaluated'. An incorrect total would give a misleading picture of
        how many strategies participated.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [AlwaysSell(), AlwaysSell(), AlwaysSell()],
            min_votes            = 1,
            confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)

        assert result.total_evaluated == 5


# ─────────────────────────────────────────────────────────────────────────────
# TestEngineErrorHandling
#
# Verifies that the engine is resilient to individual strategy failures.
# In a real 40-strategy system, it is possible that one strategy has a bug
# or receives unexpected data that causes it to throw an exception. The engine
# must catch these errors, log them, and continue with the remaining strategies
# rather than crashing the entire evaluation.
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineErrorHandling:

    def test_crashing_strategy_does_not_break_engine(self, sample_df):
        """
        One crashing strategy among three working ones must not prevent the
        engine from returning a valid result.

        The engine should catch the exception from AlwaysError, skip it,
        and still aggregate the three BUY votes from the working strategies.
        The final signal should be BUY as if the broken strategy was never there.

        This is critical for production reliability — a bug introduced into
        one strategy file must not take down the entire bot.
        """
        engine = StrategyEngine(
            buy_strategies  = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy(), AlwaysError()],
            sell_strategies = [],
            min_votes            = 3,
            confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)

        # The three working AlwaysBuy strategies should still produce BUY
        assert result.final_signal == Signal.BUY

    def test_all_strategies_crash_returns_none(self, sample_df):
        """
        If every strategy crashes, the engine must return NONE rather than
        raising an exception or returning an undefined result.

        This is the worst-case scenario — every strategy file has a bug.
        The engine must degrade gracefully, returning no signal rather than
        crashing the server and taking down the entire application.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysError()],
            sell_strategies      = [AlwaysError()],
            min_votes            = 1,
            confidence_threshold = 0.0,
        )
        result = engine.evaluate(sample_df)

        assert result.final_signal == Signal.NONE


# ─────────────────────────────────────────────────────────────────────────────
# TestAggregatedSignalStructure
#
# Verifies that the AggregatedSignal object returned by the engine has all
# the fields that the rest of the application depends on. The API endpoint
# reads these fields directly to build its JSON response, and the database
# repository function writes them to the signals table.
#
# A missing field here would cause a KeyError or AttributeError downstream —
# either in the API serialisation or in the database write — which would
# appear as a 500 error on the dashboard.
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregatedSignalStructure:

    def test_result_has_all_fields(self, sample_df):
        """
        The AggregatedSignal must contain all seven fields that the API
        endpoint and database layer expect.

        Each field has a specific consumer:
          final_signal    → displayed as BUY/SELL/NONE on the dashboard
          confidence      → fills the confidence progress bar
          buy_votes       → shown in the vote count tiles
          sell_votes      → shown in the vote count tiles
          none_votes      → shown in the vote count tiles (as 'Hold')
          top_strategies  → listed in the Top Strategies panel
          total_evaluated → shown as 'X of 40 strategies'
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [],
            min_votes            = 3,
            confidence_threshold = 0.5,
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
        """
        The confidence score must always be between 0.0 and 1.0.

        The API multiplies this by 100 before sending it to the frontend
        (so 0.75 becomes 75%). A value outside 0-1 would produce a percentage
        above 100% or below 0%, which would break the progress bar display
        and confuse the confidence threshold check in the automated bot.
        """
        engine = StrategyEngine(
            buy_strategies       = [AlwaysBuy(), AlwaysBuy(), AlwaysBuy()],
            sell_strategies      = [],
            min_votes            = 3,
            confidence_threshold = 0.5,
        )
        result = engine.evaluate(sample_df)

        assert 0.0 <= result.confidence <= 1.0