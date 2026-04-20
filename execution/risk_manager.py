"""
execution/risk_manager.py
─────────────────────────
This file is the safety guard for all trades.
Before any trade is placed, it runs through a series of checks.
If any single check fails, the trade is blocked completely.
It also calculates the correct trade size based on your account balance.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import date
from typing import Tuple

from config.settings import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


# ── Default risk values ───────────────────────────────────────────────────────
# This stores all the risk-related numbers in one place.
# Values are read from settings.py which reads from your .env file.
# You can change these in .env without touching this file.
@dataclass
class RiskParams:
    lot_size:           float = settings.DEFAULT_LOT_SIZE       # trade size per order
    stop_loss_pips:     int   = settings.DEFAULT_STOP_LOSS_PIPS # how far SL is placed
    take_profit_pips:   int   = settings.DEFAULT_TAKE_PROFIT_PIPS # how far TP is placed
    max_trades_per_day: int   = settings.MAX_TRADES_PER_DAY     # daily trade limit
    max_drawdown_pct:   float = settings.MAX_DRAWDOWN_PCT       # max allowed loss %
    risk_per_trade_pct: float = settings.RISK_PER_TRADE_PCT     # % of account to risk


# ── Main Risk Manager class ───────────────────────────────────────────────────
# This class runs all risk checks before every trade.
# It also keeps track of how many trades were placed today
# and what the highest account balance was (peak equity).
class RiskManager:

    def __init__(self, params: RiskParams | None = None) -> None:
        # Load risk settings — uses defaults from RiskParams if nothing passed
        self.params = params or RiskParams()
        # Dictionary to count how many trades were placed each day
        self._daily_trades: dict[date, int] = {}
        # Tracks the highest account balance ever seen (used for drawdown check)
        self._peak_equity:  float | None    = None
        # Emergency stop flag — when True, no trades are allowed at all
        self._kill_switch:  bool            = False

    # ── Individual risk checks ────────────────────────────────────────────────
    # Each function checks one specific risk rule.
    # Every function returns two things:
    #   True/False — whether the trade is allowed
    #   A message  — explaining why if it was blocked

    def check_kill_switch(self) -> Tuple[bool, str]:
        # Check if the emergency stop has been activated.
        # If the kill switch is ON, block all trades immediately.
        if self._kill_switch:
            return False, "Kill switch is active – all trading halted"
        return True, "ok"

    def check_daily_limit(self) -> Tuple[bool, str]:
        # Check if the bot has already placed the maximum allowed trades today.
        # If the limit is reached, no more trades for the rest of the day.
        today = date.today()
        count = self._daily_trades.get(today, 0)
        if count >= self.params.max_trades_per_day:
            return False, (f"Daily trade limit reached "
                           f"({count}/{self.params.max_trades_per_day})")
        return True, "ok"

    def check_drawdown(self, current_equity: float) -> Tuple[bool, str]:
        # Check if the account has dropped too much from its highest point.
        # If peak equity is not set yet, set it now (first time running).
        if self._peak_equity is None:
            self._peak_equity = current_equity
            return True, "ok"

        # If account grew, update the peak to the new high
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # Guard against dividing by zero if peak equity somehow becomes 0
        if self._peak_equity == 0:
            self._peak_equity = current_equity
            return True, "ok"

        # Calculate how much % the account has dropped from the peak
        dd_pct = (self._peak_equity - current_equity) / self._peak_equity * 100

        # If the drop exceeds the allowed limit, block all trades
        if dd_pct >= self.params.max_drawdown_pct:
            return False, (f"Max drawdown exceeded: {dd_pct:.2f}% "
                        f"(limit {self.params.max_drawdown_pct}%)")
        return True, "ok"

    def check_lot_size(self, lot: float) -> Tuple[bool, str]:
        # Check that the requested lot size is valid.
        # Must be greater than 0 and must not exceed the maximum allowed.
        if lot <= 0:
            return False, "Lot size must be positive"
        if lot > settings.MAX_LOT_SIZE:
            return False, f"Lot {lot} exceeds maximum {settings.MAX_LOT_SIZE}"
        return True, "ok"

    def check_fat_finger(self, lot: float, equity: float) -> Tuple[bool, str]:
        # Fat finger check — prevents accidentally placing a huge order.
        # Calculates the approximate dollar value of the order.
        # If the order value is too large compared to the account, block it.
        # In demo/mock mode (equity under $15,000), uses a looser limit
        # so test trades are not blocked unnecessarily.
        approx_value = lot * 100_000 * 0.01
        limit_pct = 2.0 if equity <= 15_000 else 0.5
        if approx_value > equity * limit_pct:
            return False, f"Fat-finger check: order value ${approx_value:.0f} > limit"
        return True, "ok"

    # ── Master validation — runs ALL checks in sequence ───────────────────────
    # This is the main function called before every trade.
    # It runs all 5 checks one by one.
    # The first check that fails stops everything — no trade is placed.
    def validate_trade(self, lot: float, equity: float) -> Tuple[bool, str]:
        # List of all checks to run, in order
        checks = [
            (self.check_kill_switch,  []),         # 1. Emergency stop?
            (self.check_daily_limit,  []),         # 2. Too many trades today?
            (self.check_drawdown,     [equity]),   # 3. Account dropped too much?
            (self.check_lot_size,     [lot]),      # 4. Valid lot size?
            (self.check_fat_finger,   [lot, equity]), # 5. Order too large?
        ]
        for fn, args in checks:
            ok, reason = fn(*args)
            if not ok:
                # Log the failure and return immediately — no trade allowed
                logger.warning("Risk check FAILED: %s", reason)
                return False, reason
        # All checks passed — trade is approved
        return True, "ok"

    # ── Position sizing ───────────────────────────────────────────────────────
    # Calculates the correct lot size based on how much of the account
    # you are willing to risk per trade.
    # Formula: Risk Amount = Account Balance × Risk %
    #          Lot Size    = Risk Amount / (Stop Loss pips × pip value)
    def calc_lot_size(
        self,
        account_equity: float,
        stop_loss_pips: int,
        pip_value:      float = 10.0,  # default $10 per pip per standard lot
    ) -> float:
        # Calculate the dollar amount to risk on this trade
        risk_amount = account_equity * (self.params.risk_per_trade_pct / 100)
        # Calculate the dollar value of the stop loss distance
        sl_value    = stop_loss_pips * pip_value
        # Divide risk amount by SL value to get the correct lot size
        lot = risk_amount / sl_value if sl_value > 0 else self.params.lot_size
        # Make sure the lot size stays within allowed min (0.01) and max limits
        lot = round(min(max(lot, 0.01), settings.MAX_LOT_SIZE), 2)
        return lot

    # ── State management functions ────────────────────────────────────────────
    # These functions update and track the internal state of the risk manager.

    def record_trade(self) -> None:
        # Called after every successful trade to add 1 to today's trade count
        today = date.today()
        self._daily_trades[today] = self._daily_trades.get(today, 0) + 1

    def reset_daily(self) -> None:
        # Clears the daily trade count — called at the start of each new day
        self._daily_trades.clear()

    def activate_kill_switch(self) -> None:
        # Turns ON the emergency stop — no trades will be placed after this
        # until deactivate_kill_switch() is called
        self._kill_switch = True
        logger.critical("KILL SWITCH ACTIVATED – all trading halted")

    def deactivate_kill_switch(self) -> None:
        # Turns OFF the emergency stop — resumes normal trading
        self._kill_switch = False
        logger.info("Kill switch deactivated")

    def daily_trade_count(self) -> int:
        # Returns how many trades have been placed today
        return self._daily_trades.get(date.today(), 0)

    def current_drawdown_pct(self, equity: float) -> float:
        # Returns the current drawdown as a percentage.
        # e.g. if peak was $10,000 and current is $9,500, drawdown is 5%
        if self._peak_equity is None or self._peak_equity == 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity * 100)


# ── Single shared instance ────────────────────────────────────────────────────
# One shared RiskManager used by the whole bot.
# The trade executor imports this directly to validate every trade.
risk_manager = RiskManager()