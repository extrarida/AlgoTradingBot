"""
database/models.py
──────────────────
SQLAlchemy ORM models for AlgoTradingBot.

Tables
------
  accounts          – MT5 account snapshots (balance, equity, margin)
  trades            – Every executed trade (entry details)
  trade_outcomes    – Close/result data linked to a trade
  signals           – Strategy engine output per evaluation
  risk_events       – Kill switch, drawdown breaches, daily limit hits
  price_snapshots   – Periodic bid/ask tick records
  strategy_votes    – Per-strategy vote detail inside each signal evaluation
  performance_daily – Rolled-up daily PnL & stats
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── 1. accounts ───────────────────────────────────────────────────────────────

class Account(Base):
    """
    Snapshot of the MT5 account at a point in time.
    Captured on connect and periodically during a session.
    """
    __tablename__ = "accounts"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    login      = Column(BigInteger, nullable=False, index=True)
    server     = Column(String(120), nullable=False)
    balance    = Column(Numeric(18, 2), nullable=False)
    equity     = Column(Numeric(18, 2), nullable=False)
    margin     = Column(Numeric(18, 2), nullable=True)
    free_margin= Column(Numeric(18, 2), nullable=True)
    currency   = Column(String(10), nullable=True, default="USD")
    leverage   = Column(Integer, nullable=True)
    mock_mode  = Column(Boolean, nullable=False, default=False)
    recorded_at= Column(DateTime, nullable=False, default=datetime.utcnow)

    trades = relationship("Trade", back_populates="account")

    def __repr__(self) -> str:
        return f"<Account login={self.login} equity={self.equity} at={self.recorded_at}>"


# ── 2. trades ─────────────────────────────────────────────────────────────────

class Trade(Base):
    """
    One row per executed trade (FILLED orders only).
    The trade lifecycle ends in trade_outcomes.
    """
    __tablename__ = "trades"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    account_id   = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    order_id     = Column(BigInteger, nullable=True, index=True)   # MT5 order ticket
    deal_id      = Column(BigInteger, nullable=True)               # MT5 deal ticket
    symbol       = Column(String(20),  nullable=False, index=True)
    direction    = Column(String(10),  nullable=False)             # BUY | SELL
    lot_size     = Column(Numeric(10, 2), nullable=False)
    entry_price  = Column(Numeric(18, 5), nullable=False)
    sl_price     = Column(Numeric(18, 5), nullable=True)
    tp_price     = Column(Numeric(18, 5), nullable=True)
    sl_pips      = Column(Integer, nullable=True)
    tp_pips      = Column(Integer, nullable=True)
    magic_number = Column(Integer, nullable=True, default=123456)
    comment      = Column(String(120), nullable=True)
    state        = Column(String(30),  nullable=False, default="FILLED")
    opened_at    = Column(DateTime, nullable=False, default=datetime.utcnow)

    account  = relationship("Account",      back_populates="trades")
    outcome  = relationship("TradeOutcome", back_populates="trade", uselist=False)
    signal   = relationship("Signal",       back_populates="trade", uselist=False)

    __table_args__ = (
        Index("ix_trades_symbol_opened", "symbol", "opened_at"),
    )

    def __repr__(self) -> str:
        return f"<Trade {self.direction} {self.symbol} {self.lot_size}L @ {self.entry_price}>"


# ── 3. trade_outcomes ─────────────────────────────────────────────────────────

class TradeOutcome(Base):
    """
    Closing data for a trade — filled when MT5 confirms position closed.
    Linked 1-to-1 with trades.
    """
    __tablename__ = "trade_outcomes"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    trade_id     = Column(Integer, ForeignKey("trades.id"), nullable=False, unique=True)
    exit_price   = Column(Numeric(18, 5), nullable=False)
    pnl          = Column(Numeric(18, 2), nullable=False)   # realised P&L in account currency
    pips_gained  = Column(Numeric(10, 2), nullable=True)
    close_reason = Column(String(30),  nullable=True)       # SL | TP | MANUAL | EXPIRED
    closed_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    duration_sec = Column(Integer,  nullable=True)          # seconds trade was open

    trade = relationship("Trade", back_populates="outcome")

    def __repr__(self) -> str:
        return f"<TradeOutcome trade_id={self.trade_id} pnl={self.pnl}>"


# ── 4. signals ────────────────────────────────────────────────────────────────

class Signal(Base):
    """
    One row per call to StrategyEngine.evaluate().
    Stores the aggregated signal and vote breakdown.
    """
    __tablename__ = "signals"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    trade_id         = Column(Integer, ForeignKey("trades.id"), nullable=True)
    symbol           = Column(String(20),  nullable=False, index=True)
    timeframe        = Column(String(10),  nullable=False, default="M15")
    final_signal     = Column(String(10),  nullable=False)   # BUY | SELL | NONE
    confidence       = Column(Float,       nullable=False)
    buy_votes        = Column(Integer,     nullable=False, default=0)
    sell_votes       = Column(Integer,     nullable=False, default=0)
    none_votes       = Column(Integer,     nullable=False, default=0)
    total_evaluated  = Column(Integer,     nullable=False, default=0)
    evaluated_at     = Column(DateTime,    nullable=False, default=datetime.utcnow)

    trade         = relationship("Trade",         back_populates="signal")
    strategy_votes= relationship("StrategyVote",  back_populates="signal")

    __table_args__ = (
        Index("ix_signals_symbol_evaluated", "symbol", "evaluated_at"),
    )

    def __repr__(self) -> str:
        return (f"<Signal {self.final_signal} {self.symbol} "
                f"conf={self.confidence:.2f} at={self.evaluated_at}>")


# ── 5. strategy_votes ─────────────────────────────────────────────────────────

class StrategyVote(Base):
    """
    Per-strategy detail row inside a signal evaluation.
    Lets you audit which strategies drove the aggregated result.
    """
    __tablename__ = "strategy_votes"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    signal_id    = Column(Integer, ForeignKey("signals.id"), nullable=False, index=True)
    strategy_name= Column(String(80), nullable=False)
    vote         = Column(String(10), nullable=False)   # BUY | SELL | NONE
    confidence   = Column(Float,      nullable=False)
    reason       = Column(Text,       nullable=True)

    signal = relationship("Signal", back_populates="strategy_votes")

    def __repr__(self) -> str:
        return f"<StrategyVote {self.strategy_name} -> {self.vote} conf={self.confidence:.2f}>"


# ── 6. risk_events ────────────────────────────────────────────────────────────

class RiskEvent(Base):
    """
    Audit log for every risk-check failure and kill-switch toggle.
    """
    __tablename__ = "risk_events"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    event_type   = Column(String(40),  nullable=False, index=True)
    # e.g. KILL_SWITCH_ON | KILL_SWITCH_OFF | DAILY_LIMIT | DRAWDOWN | LOT_REJECTED
    symbol       = Column(String(20),  nullable=True)
    lot_size     = Column(Numeric(10, 2), nullable=True)
    equity       = Column(Numeric(18, 2), nullable=True)
    drawdown_pct = Column(Float,       nullable=True)
    detail       = Column(Text,        nullable=True)   # human-readable reason
    occurred_at  = Column(DateTime,    nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<RiskEvent {self.event_type} at={self.occurred_at}>"


# ── 7. price_snapshots ────────────────────────────────────────────────────────

class PriceSnapshot(Base):
    """
    Periodic tick records — bid/ask captured by the dashboard poller.
    Useful for replay and auditing execution quality.
    """
    __tablename__ = "price_snapshots"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(20), nullable=False, index=True)
    bid         = Column(Numeric(18, 5), nullable=False)
    ask         = Column(Numeric(18, 5), nullable=False)
    spread_pips = Column(Numeric(8, 2), nullable=True)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_price_symbol_time", "symbol", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<PriceSnapshot {self.symbol} bid={self.bid} at={self.recorded_at}>"


# ── 8. performance_daily ──────────────────────────────────────────────────────

class PerformanceDaily(Base):
    """
    Daily rolled-up performance stats.
    Computed and upserted at end-of-day (or on demand).
    """
    __tablename__ = "performance_daily"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    trade_date      = Column(String(10), nullable=False, unique=True, index=True)
    # stored as YYYY-MM-DD string for easy filtering
    total_trades    = Column(Integer,     nullable=False, default=0)
    winning_trades  = Column(Integer,     nullable=False, default=0)
    losing_trades   = Column(Integer,     nullable=False, default=0)
    total_pnl       = Column(Numeric(18, 2), nullable=False, default=0)
    gross_profit    = Column(Numeric(18, 2), nullable=True)
    gross_loss      = Column(Numeric(18, 2), nullable=True)
    win_rate        = Column(Float,       nullable=True)
    avg_pnl         = Column(Numeric(18, 2), nullable=True)
    max_drawdown_pct= Column(Float,       nullable=True)
    best_trade_pnl  = Column(Numeric(18, 2), nullable=True)
    worst_trade_pnl = Column(Numeric(18, 2), nullable=True)
    computed_at     = Column(DateTime,    nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PerformanceDaily {self.trade_date} pnl={self.total_pnl} trades={self.total_trades}>"
