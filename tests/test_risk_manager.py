"""
tests/test_risk_manager.py
──────────────────────────
Unit tests for the RiskManager — the safety layer that stands between the
strategy engine and the broker.

Every trade the bot wants to place, whether triggered manually or automatically
by the scheduler, must pass through a sequence of five checks before an order
is sent. If any check fails, the trade is blocked and a reason is returned.
This file tests each of those checks individually and also tests the master
validate_trade() method that runs them all in sequence.

The five checks (tested in the order they run):
  1. Kill switch        — manual emergency stop, overrides everything else
  2. Daily limit        — caps the number of trades per day
  3. Drawdown           — halts trading if account equity falls too far
  4. Lot size           — rejects orders that are too small, zero, or too large
  5. Position sizing    — calculates a safe lot size based on account equity

Why these checks matter:
────────────────────────
Automated trading systems can lose money very quickly if there are no limits.
A bug in a strategy could fire the same trade thousands of times per minute.
A market gap could cause an account to drop 20% in seconds. The risk manager
exists specifically to prevent catastrophic losses — these tests prove it works.

Each test gets a fresh RiskManager instance via the rm fixture, so no test
inherits state (like an incremented trade count or an active kill switch) from
a previous test.

Run with:
    pytest tests/test_risk_manager.py -v
"""

import pytest
from execution.risk_manager import RiskManager, RiskParams
from config.settings import get_settings

# Load the app-wide settings so tests use the same limits as production
settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Fixture
#
# Every test gets its own clean RiskManager with known parameter values.
# Using a fixture (rather than creating the RiskManager inside each test)
# means we only define the configuration once — if the parameters change,
# we update one place.
#
# The parameters here are intentionally simple round numbers so the expected
# results of drawdown and lot size calculations are easy to verify by hand.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def rm():
    """
    A fresh RiskManager instance for every test.

    Parameters chosen for predictable test behaviour:
      - max_trades_per_day = 5  (easy to hit exactly in a loop)
      - max_drawdown_pct   = 10.0  (10% makes percentage maths simple)
      - risk_per_trade_pct = 1.0  (1% per trade is the standard safe default)
    """
    return RiskManager(RiskParams(
        lot_size           = 0.01,
        stop_loss_pips     = 50,
        take_profit_pips   = 100,
        max_trades_per_day = 5,
        max_drawdown_pct   = 10.0,
        risk_per_trade_pct = 1.0,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# TestKillSwitch
#
# The kill switch is the highest-priority safety mechanism. When active, it
# blocks every trade regardless of what any other check says. It can be
# triggered manually from the Risk Manager page on the dashboard, or
# automatically if the drawdown limit is breached.
#
# These tests verify three states: inactive by default, blocking when on,
# and allowing again after it is turned off.
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitch:

    def test_inactive_by_default(self, rm):
        """
        A new RiskManager must start with the kill switch off.

        If it defaulted to on, no trades could ever be placed — the bot would
        appear broken every time it was restarted.
        """
        ok, _ = rm.check_kill_switch()
        assert ok is True

    def test_blocks_after_activation(self, rm):
        """
        After activate_kill_switch() is called, check_kill_switch() must
        return False and a reason that mentions the kill switch.

        The reason string is displayed on the dashboard in the trade result
        section, so it needs to be human-readable and contain 'kill switch'
        so the user understands why their trade was rejected.
        """
        rm.activate_kill_switch()
        ok, reason = rm.check_kill_switch()

        assert ok is False
        assert "kill switch" in reason.lower()

    def test_allows_after_deactivation(self, rm):
        """
        After deactivate_kill_switch() is called, trading must be permitted
        again.

        This confirms the kill switch can be toggled — turning it on once does
        not permanently disable trading. The Resume button on the dashboard
        depends on this behaviour.
        """
        rm.activate_kill_switch()
        rm.deactivate_kill_switch()
        ok, _ = rm.check_kill_switch()

        assert ok is True


# ─────────────────────────────────────────────────────────────────────────────
# TestDailyLimit
#
# The daily trade limit prevents the bot from placing an unlimited number of
# orders in a single day. In live trading, excessive order frequency can
# trigger broker restrictions and also indicates a strategy might be firing
# incorrectly. Limiting to 5 trades per day provides a safety ceiling.
#
# These tests verify the counter starts at zero, increments correctly,
# blocks at exactly the limit, and resets properly.
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyLimit:

    def test_allows_trades_under_limit(self, rm):
        """
        4 trades recorded against a limit of 5 should still allow the next
        trade through.

        This confirms the check is strictly greater-than, not greater-than-
        or-equal — you should be able to reach exactly the limit before
        being blocked.
        """
        for _ in range(4):
            rm.record_trade()

        ok, _ = rm.check_daily_limit()
        assert ok is True

    def test_blocks_when_limit_reached(self, rm):
        """
        Once exactly 5 trades have been recorded, the next check must fail.

        The reason string must contain 'limit' so the dashboard can display
        a meaningful message explaining why the trade was rejected.
        """
        for _ in range(5):
            rm.record_trade()

        ok, reason = rm.check_daily_limit()
        assert ok is False
        assert "limit" in reason.lower()

    def test_trade_count_starts_at_zero(self, rm):
        """
        A fresh RiskManager must report zero trades.

        If the counter did not start at zero, tests would get inconsistent
        results depending on how many times the fixture has been used —
        which would not happen with the function-scoped fixture but is
        worth verifying explicitly.
        """
        assert rm.daily_trade_count() == 0

    def test_record_trade_increments_count(self, rm):
        """
        Each call to record_trade() should increase the count by exactly one.

        After two calls, the count should be exactly 2 — not 1 (under-counting)
        or 3 (over-counting), both of which would cause the limit logic to
        fire at the wrong time.
        """
        rm.record_trade()
        rm.record_trade()

        assert rm.daily_trade_count() == 2

    def test_reset_daily_clears_count(self, rm):
        """
        reset_daily() must bring the count back to zero regardless of how
        many trades have been recorded.

        This method is called at midnight (or at the start of each test via
        the integration test fixture) to ensure each day starts fresh.
        """
        rm.record_trade()
        rm.record_trade()
        rm.reset_daily()

        assert rm.daily_trade_count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestDrawdown
#
# Drawdown protection halts trading if the account equity falls too far below
# its peak value. For example, with a 10% limit and a peak of $10,000, trading
# stops if equity drops below $9,000.
#
# The peak is tracked internally — the first equity value sets the initial
# peak, and the peak updates upward whenever equity reaches a new high.
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawdown:

    def test_first_call_sets_peak(self, rm):
        """
        The first call to check_drawdown() should always pass, regardless of
        the equity value, because the first equity value becomes the peak.

        There is no prior peak to compare against, so drawdown is 0% and the
        check must return True.
        """
        ok, _ = rm.check_drawdown(10000.0)
        assert ok is True

    def test_allows_within_drawdown_limit(self, rm):
        """
        A 5% drop from the peak should pass when the limit is 10%.

        Peak is set at $10,000. $9,500 represents a 5% drawdown — well within
        the 10% limit. The trade should be allowed.
        """
        rm.check_drawdown(10000.0)           # sets peak at $10,000
        ok, _ = rm.check_drawdown(9500.0)    # 5% below peak — should pass

        assert ok is True

    def test_blocks_when_drawdown_exceeded(self, rm):
        """
        An 11% drop from peak must be blocked when the limit is 10%.

        Peak is $10,000. $8,900 is $1,100 below peak — 11% drawdown — which
        exceeds the 10% limit. Trading must be halted and the reason must
        mention drawdown so the dashboard can explain why.
        """
        rm.check_drawdown(10000.0)
        ok, reason = rm.check_drawdown(8900.0)  # 11% below peak — must block

        assert ok is False
        assert "drawdown" in reason.lower()

    def test_peak_updates_on_new_high(self, rm):
        """
        When equity reaches a new all-time high, the peak must update so that
        subsequent drawdown calculations use the new peak.

        Starting at $10,000, rising to $11,000 sets a new peak. Dropping to
        $10,100 from $11,000 is about 8.2% drawdown — within the 10% limit.
        If the peak had not updated from $10,000, the same $10,100 would look
        like a profit rather than a drawdown.
        """
        rm.check_drawdown(10000.0)   # initial peak: $10,000
        rm.check_drawdown(11000.0)   # new peak: $11,000
        ok, _ = rm.check_drawdown(10100.0)  # ~8.2% from new peak — within limit

        assert ok is True

    def test_current_drawdown_pct_zero_at_peak(self, rm):
        """
        current_drawdown_pct() must return exactly 0.0 when equity equals
        the peak.

        This drives the drawdown gauge on the Risk Manager page. A non-zero
        value at peak would make the gauge appear to show a loss when there
        is none.
        """
        rm.check_drawdown(10000.0)
        assert rm.current_drawdown_pct(10000.0) == 0.0

    def test_current_drawdown_pct_correct(self, rm):
        """
        current_drawdown_pct() must return the correct percentage for a known
        equity drop.

        Peak: $10,000. Current equity: $9,000. Drawdown = 10%.
        Tolerance of 0.01 accounts for floating-point rounding in the division.
        """
        rm.check_drawdown(10000.0)         # set peak
        pct = rm.current_drawdown_pct(9000.0)

        assert abs(pct - 10.0) < 0.01     # should be very close to exactly 10%


# ─────────────────────────────────────────────────────────────────────────────
# TestLotSize
#
# Lot size validation ensures no order is sent with an obviously invalid
# size — zero, negative, or above the configured maximum. This is the
# 'fat finger' protection layer: it catches accidental inputs that would
# result in an unusually large trade.
# ─────────────────────────────────────────────────────────────────────────────

class TestLotSize:

    def test_valid_lot_passes(self, rm):
        """
        A standard lot size of 0.1 (a mini lot) must pass the check.

        0.1 is a common lot size for retail traders — safely above the minimum
        and well below any reasonable maximum.
        """
        ok, _ = rm.check_lot_size(0.1)
        assert ok is True

    def test_zero_lot_fails(self, rm):
        """
        A lot size of 0 must be rejected.

        You cannot place an order for zero units — it is not a meaningful trade.
        Brokers will reject it, but we catch it earlier in the risk manager so
        the user gets a clear rejection reason rather than a confusing broker
        error.
        """
        ok, _ = rm.check_lot_size(0.0)
        assert ok is False

    def test_negative_lot_fails(self, rm):
        """
        A negative lot size must be rejected.

        A negative lot has no meaning in MT5 — the sign of the trade (buy vs
        sell) is determined by the order type, not the lot size. A negative
        value would indicate a data entry error.
        """
        ok, _ = rm.check_lot_size(-0.1)
        assert ok is False

    def test_lot_above_max_fails(self, rm):
        """
        A lot size above the configured maximum must be rejected.

        The reason string must mention 'maximum' or 'exceeds' to explain
        clearly why the order was blocked. This is the fat finger check —
        accidentally typing '10' instead of '0.1' would be caught here.
        """
        ok, reason = rm.check_lot_size(settings.MAX_LOT_SIZE + 1.0)

        assert ok is False
        assert "maximum" in reason.lower() or "exceeds" in reason.lower()


# ─────────────────────────────────────────────────────────────────────────────
# TestValidateTrade
#
# validate_trade() is the master method that runs all checks in sequence and
# returns as soon as one fails. These tests verify that it integrates the
# individual checks correctly — a clean trade passes everything, and each
# individual failure condition is correctly surfaced.
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateTrade:

    def test_valid_trade_passes_all_checks(self, rm):
        """
        A trade with sensible parameters and a fresh risk manager must pass
        all five checks and return reason 'ok'.

        This is the happy path — the most common case in normal operation.
        If this test fails, something is wrong with the default state of the
        risk manager or one of the checks has a bug that blocks valid trades.
        """
        ok, reason = rm.validate_trade(lot=0.01, equity=10000.0)

        assert ok is True
        assert reason == "ok"

    def test_fails_when_kill_switch_active(self, rm):
        """
        validate_trade() must return False when the kill switch is on,
        regardless of how valid the other parameters are.

        The kill switch is checked first — it is the highest-priority block
        and should short-circuit the remaining checks immediately.
        """
        rm.activate_kill_switch()
        ok, _ = rm.validate_trade(lot=0.01, equity=10000.0)

        assert ok is False

    def test_fails_when_daily_limit_reached(self, rm):
        """
        validate_trade() must return False once the daily trade limit is
        exhausted, even if the kill switch is off and the lot size is valid.

        This confirms the daily limit check runs even when the kill switch
        is not triggered.
        """
        for _ in range(5):
            rm.record_trade()

        ok, _ = rm.validate_trade(lot=0.01, equity=10000.0)
        assert ok is False

    def test_fails_with_zero_lot(self, rm):
        """
        validate_trade() must return False for a lot size of 0.

        Even though the kill switch is off and the daily limit has not been
        reached, an invalid lot size must still be caught by validate_trade().
        This confirms the lot size check runs as part of the validation chain.
        """
        ok, _ = rm.validate_trade(lot=0.0, equity=10000.0)
        assert ok is False


# ─────────────────────────────────────────────────────────────────────────────
# TestPositionSizing
#
# calc_lot_size() computes a safe trade size based on how much of the account
# equity to risk per trade. For example, with 1% risk, a $10,000 account,
# and a 50-pip stop loss, it calculates the lot size where a 50-pip adverse
# move costs exactly $100 (1% of $10,000).
#
# These tests verify the output stays within the configured bounds and scales
# proportionally with account size.
# ─────────────────────────────────────────────────────────────────────────────

class TestPositionSizing:

    def test_returns_positive_lot(self, rm):
        """
        calc_lot_size() must always return a positive number.

        A zero or negative lot would not be a valid trade and would be caught
        by check_lot_size() anyway, but the sizing function itself should never
        produce such a value under normal inputs.
        """
        lot = rm.calc_lot_size(10000.0, 50)
        assert lot > 0

    def test_respects_max_lot(self, rm):
        """
        The calculated lot must never exceed the configured maximum.

        Even for very large account sizes, the sizing function must cap the
        output at MAX_LOT_SIZE to prevent the fat finger check from
        immediately blocking the sized trade.
        """
        lot = rm.calc_lot_size(10000.0, 1)
        assert lot <= settings.MAX_LOT_SIZE

    def test_respects_min_lot(self, rm):
        """
        The calculated lot must never fall below 0.01 (one micro lot).

        For very small accounts or wide stop losses, the maths might produce
        a tiny fraction of a lot. Brokers enforce a minimum lot size of 0.01,
        so the function must round up to this floor rather than returning an
        unacceptable value.
        """
        lot = rm.calc_lot_size(100.0, 200)
        assert lot >= 0.01

    def test_larger_equity_gives_larger_lot(self, rm):
        """
        A larger account should produce a larger (or equal) lot size for the
        same stop loss distance.

        This verifies that position sizing scales correctly with account size.
        A $100,000 account risking 1% can afford to trade larger positions than
        a $1,000 account risking the same percentage.
        """
        lot_small = rm.calc_lot_size(1000.0,   50)   # small account
        lot_large = rm.calc_lot_size(100000.0, 50)   # large account

        assert lot_large >= lot_small