"""
tests/test_risk_manager.py
──────────────────────────
Tests for every risk check in the RiskManager.
These are critical — they protect against bad trades.
"""

import pytest
from execution.risk_manager import RiskManager, RiskParams
from config.settings import get_settings

settings = get_settings()


@pytest.fixture
def rm():
    """Fresh RiskManager for every test — no shared state."""
    return RiskManager(RiskParams(
        lot_size           = 0.01,
        stop_loss_pips     = 50,
        take_profit_pips   = 100,
        max_trades_per_day = 5,
        max_drawdown_pct   = 10.0,
        risk_per_trade_pct = 1.0,
    ))


# ── Kill Switch ───────────────────────────────────────────────────────────────

class TestKillSwitch:

    def test_inactive_by_default(self, rm):
        ok, _ = rm.check_kill_switch()
        assert ok is True

    def test_blocks_after_activation(self, rm):
        rm.activate_kill_switch()
        ok, reason = rm.check_kill_switch()
        assert ok is False
        assert "kill switch" in reason.lower()

    def test_allows_after_deactivation(self, rm):
        rm.activate_kill_switch()
        rm.deactivate_kill_switch()
        ok, _ = rm.check_kill_switch()
        assert ok is True


# ── Daily Trade Limit ─────────────────────────────────────────────────────────

class TestDailyLimit:

    def test_allows_trades_under_limit(self, rm):
        for _ in range(4):
            rm.record_trade()
        ok, _ = rm.check_daily_limit()
        assert ok is True

    def test_blocks_when_limit_reached(self, rm):
        for _ in range(5):
            rm.record_trade()
        ok, reason = rm.check_daily_limit()
        assert ok is False
        assert "limit" in reason.lower()

    def test_trade_count_starts_at_zero(self, rm):
        assert rm.daily_trade_count() == 0

    def test_record_trade_increments_count(self, rm):
        rm.record_trade()
        rm.record_trade()
        assert rm.daily_trade_count() == 2

    def test_reset_daily_clears_count(self, rm):
        rm.record_trade()
        rm.record_trade()
        rm.reset_daily()
        assert rm.daily_trade_count() == 0


# ── Drawdown ──────────────────────────────────────────────────────────────────

class TestDrawdown:

    def test_first_call_sets_peak(self, rm):
        ok, _ = rm.check_drawdown(10000.0)
        assert ok is True

    def test_allows_within_drawdown_limit(self, rm):
        rm.check_drawdown(10000.0)   # set peak
        ok, _ = rm.check_drawdown(9500.0)  # 5% drawdown, limit is 10%
        assert ok is True

    def test_blocks_when_drawdown_exceeded(self, rm):
        rm.check_drawdown(10000.0)
        ok, reason = rm.check_drawdown(8900.0)  # 11% drawdown
        assert ok is False
        assert "drawdown" in reason.lower()

    def test_peak_updates_on_new_high(self, rm):
        rm.check_drawdown(10000.0)
        rm.check_drawdown(11000.0)  # new peak
        ok, _ = rm.check_drawdown(10100.0)  # ~8% from new peak, under 10%
        assert ok is True

    def test_current_drawdown_pct_zero_at_peak(self, rm):
        rm.check_drawdown(10000.0)
        assert rm.current_drawdown_pct(10000.0) == 0.0

    def test_current_drawdown_pct_correct(self, rm):
        rm.check_drawdown(10000.0)
        pct = rm.current_drawdown_pct(9000.0)
        assert abs(pct - 10.0) < 0.01


# ── Lot Size ──────────────────────────────────────────────────────────────────

class TestLotSize:

    def test_valid_lot_passes(self, rm):
        ok, _ = rm.check_lot_size(0.1)
        assert ok is True

    def test_zero_lot_fails(self, rm):
        ok, _ = rm.check_lot_size(0.0)
        assert ok is False

    def test_negative_lot_fails(self, rm):
        ok, _ = rm.check_lot_size(-0.1)
        assert ok is False

    def test_lot_above_max_fails(self, rm):
        ok, reason = rm.check_lot_size(settings.MAX_LOT_SIZE + 1.0)
        assert ok is False
        assert "maximum" in reason.lower() or "exceeds" in reason.lower()


# ── Validate Trade (master check) ────────────────────────────────────────────

class TestValidateTrade:

    def test_valid_trade_passes_all_checks(self, rm):
        ok, reason = rm.validate_trade(lot=0.01, equity=10000.0)
        assert ok is True
        assert reason == "ok"

    def test_fails_when_kill_switch_active(self, rm):
        rm.activate_kill_switch()
        ok, _ = rm.validate_trade(lot=0.01, equity=10000.0)
        assert ok is False

    def test_fails_when_daily_limit_reached(self, rm):
        for _ in range(5):
            rm.record_trade()
        ok, _ = rm.validate_trade(lot=0.01, equity=10000.0)
        assert ok is False

    def test_fails_with_zero_lot(self, rm):
        ok, _ = rm.validate_trade(lot=0.0, equity=10000.0)
        assert ok is False


# ── Position Sizing ───────────────────────────────────────────────────────────

class TestPositionSizing:

    def test_returns_positive_lot(self, rm):
        lot = rm.calc_lot_size(10000.0, 50)
        assert lot > 0

    def test_respects_max_lot(self, rm):
        lot = rm.calc_lot_size(10000.0, 1)
        assert lot <= settings.MAX_LOT_SIZE

    def test_respects_min_lot(self, rm):
        lot = rm.calc_lot_size(100.0, 200)
        assert lot >= 0.01

    def test_larger_equity_gives_larger_lot(self, rm):
        lot_small = rm.calc_lot_size(1000.0,  50)
        lot_large = rm.calc_lot_size(100000.0, 50)
        assert lot_large >= lot_small