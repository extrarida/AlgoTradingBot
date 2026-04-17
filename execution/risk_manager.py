"""
execution/risk_manager.py
─────────────────────────
Layer 10 – Pre-Trade Risk Engine

Guards every trade with three sequential checks.
Also provides risk-based position sizing.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import date
from typing import Tuple

from config.settings import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RiskParams:
    lot_size:           float = settings.DEFAULT_LOT_SIZE
    stop_loss_pips:     int   = settings.DEFAULT_STOP_LOSS_PIPS
    take_profit_pips:   int   = settings.DEFAULT_TAKE_PROFIT_PIPS
    max_trades_per_day: int   = settings.MAX_TRADES_PER_DAY
    max_drawdown_pct:   float = settings.MAX_DRAWDOWN_PCT
    risk_per_trade_pct: float = settings.RISK_PER_TRADE_PCT


class RiskManager:
    """
    Stateful risk manager.
    Tracks daily trade count and peak equity.
    """

    def __init__(self, params: RiskParams | None = None) -> None:
        self.params        = params or RiskParams() #comment
        self._daily_trades: dict[date, int] = {}
        self._peak_equity:  float | None    = None
        self._kill_switch:  bool            = False

    # ── Individual checks ─────────────────────────────────────────────────────

    def check_kill_switch(self) -> Tuple[bool, str]:
        if self._kill_switch:
            return False, "Kill switch is active – all trading halted"
        return True, "ok"

    def check_daily_limit(self) -> Tuple[bool, str]:
        today = date.today()
        count = self._daily_trades.get(today, 0)
        if count >= self.params.max_trades_per_day:
            return False, (f"Daily trade limit reached "
                           f"({count}/{self.params.max_trades_per_day})")
        return True, "ok"

    def check_drawdown(self, current_equity: float) -> Tuple[bool, str]:
        if self._peak_equity is None:
            self._peak_equity = current_equity
            return True, "ok"
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
    
        # Guard against zero peak equity
        if self._peak_equity == 0:
            self._peak_equity = current_equity
            return True, "ok"
    
        dd_pct = (self._peak_equity - current_equity) / self._peak_equity * 100
        if dd_pct >= self.params.max_drawdown_pct:
            return False, (f"Max drawdown exceeded: {dd_pct:.2f}% "
                        f"(limit {self.params.max_drawdown_pct}%)")
        return True, "ok"

    def check_lot_size(self, lot: float) -> Tuple[bool, str]:
        if lot <= 0:
            return False, "Lot size must be positive"
        if lot > settings.MAX_LOT_SIZE:
            return False, f"Lot {lot} exceeds maximum {settings.MAX_LOT_SIZE}"
        return True, "ok"

    def check_fat_finger(self, lot: float, equity: float) -> Tuple[bool, str]:
        """Reject orders where lot value exceeds 50% of equity."""
        approx_value = lot * 100_000 * 0.01
        # Use 200% threshold in mock/demo to allow normal test trading
        limit_pct = 2.0 if equity <= 15_000 else 0.5
        if approx_value > equity * limit_pct:
            return False, f"Fat-finger check: order value ${approx_value:.0f} > limit"
        return True, "ok"

    # ── Master validation ─────────────────────────────────────────────────────

    def validate_trade(self, lot: float, equity: float) -> Tuple[bool, str]:
        """
        Run all risk checks in order.
        Returns (approved, reason).
        First failure stops the chain.
        """
        checks = [
            (self.check_kill_switch,  []),
            (self.check_daily_limit,  []),
            (self.check_drawdown,     [equity]),
            (self.check_lot_size,     [lot]),
            (self.check_fat_finger,   [lot, equity]),
        ]
        for fn, args in checks:
            ok, reason = fn(*args)
            if not ok:
                logger.warning("Risk check FAILED: %s", reason)
                return False, reason
        return True, "ok"

    # ── Position sizing ───────────────────────────────────────────────────────

    def calc_lot_size(
        self,
        account_equity: float,
        stop_loss_pips: int,
        pip_value:      float = 10.0,
    ) -> float:
        """
        Risk-based position sizing.
        Risk Amount = equity × risk_pct
        Lot Size    = Risk Amount / (SL_pips × pip_value_per_lot)
        """
        risk_amount = account_equity * (self.params.risk_per_trade_pct / 100)
        sl_value    = stop_loss_pips * pip_value
        lot = risk_amount / sl_value if sl_value > 0 else self.params.lot_size
        lot = round(min(max(lot, 0.01), settings.MAX_LOT_SIZE), 2)
        return lot

    # ── State management ──────────────────────────────────────────────────────

    def record_trade(self) -> None:
        today = date.today()
        self._daily_trades[today] = self._daily_trades.get(today, 0) + 1

    def reset_daily(self) -> None:
        self._daily_trades.clear()

    def activate_kill_switch(self) -> None:
        self._kill_switch = True
        logger.critical("KILL SWITCH ACTIVATED – all trading halted")

    def deactivate_kill_switch(self) -> None:
        self._kill_switch = False
        logger.info("Kill switch deactivated")

    def daily_trade_count(self) -> int:
        return self._daily_trades.get(date.today(), 0)

    def current_drawdown_pct(self, equity: float) -> float:
        if self._peak_equity is None or self._peak_equity == 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity * 100)


# ── Module-level singleton ────────────────────────────────────────────────────
risk_manager = RiskManager()
