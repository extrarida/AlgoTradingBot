"""
database/repository.py
──────────────────────
All database read/write operations for AlgoTradingBot.

This is the ONLY file that imports SQLAlchemy sessions.
Every other module (main.py, trade_executor.py, etc.)
should call functions from here — never touch the session directly.

Functions are grouped by table:
  - save_account_snapshot()
  - save_trade()
  - save_trade_outcome()
  - save_signal()
  - save_risk_event()
  - save_price_snapshot()
  - upsert_performance_daily()
  - get_trade_history()
  - get_performance_summary()
  - get_recent_signals()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func

from .connection import get_session
from .models import (
    Account, PerformanceDaily, PriceSnapshot,
    RiskEvent, Signal, StrategyVote, Trade, TradeOutcome,
)

logger = logging.getLogger(__name__)


# ── accounts ──────────────────────────────────────────────────────────────────

def save_account_snapshot(
    login:      int,
    server:     str,
    balance:    float,
    equity:     float,
    margin:     float       = 0.0,
    free_margin:float       = 0.0,
    currency:   str         = "USD",
    leverage:   int         = 0,
    mock_mode:  bool        = False,
) -> Account:
    """
    Persist one account snapshot row and return it.
    Called on connect and periodically by the dashboard.
    """
    account = Account(
        login       = login,
        server      = server,
        balance     = balance,
        equity      = equity,
        margin      = margin,
        free_margin = free_margin,
        currency    = currency,
        leverage    = leverage,
        mock_mode   = mock_mode,
        recorded_at = datetime.utcnow(),
    )
    with get_session() as session:
        session.add(account)
        session.flush()          # get the auto-generated id
        session.expunge(account) # detach so it's safe to return
    logger.debug("Saved account snapshot for login=%s", login)
    return account


# ── trades ────────────────────────────────────────────────────────────────────

def save_trade(
    symbol:       str,
    direction:    str,
    lot_size:     float,
    entry_price:  float,
    sl_price:     float,
    tp_price:     float,
    sl_pips:      int         = 0,
    tp_pips:      int         = 0,
    order_id:     Optional[int] = None,
    deal_id:      Optional[int] = None,
    account_id:   Optional[int] = None,
    magic_number: int         = 123456,
    comment:      str         = "algobot",
    state:        str         = "FILLED",
) -> Trade:
    """
    Persist a new trade row and return it.
    Call this immediately after executor.execute() returns success=True.
    """
    trade = Trade(
        account_id   = account_id,
        order_id     = order_id,
        deal_id      = deal_id,
        symbol       = symbol,
        direction    = direction,
        lot_size     = lot_size,
        entry_price  = entry_price,
        sl_price     = sl_price,
        tp_price     = tp_price,
        sl_pips      = sl_pips,
        tp_pips      = tp_pips,
        magic_number = magic_number,
        comment      = comment,
        state        = state,
        opened_at    = datetime.utcnow(),
    )
    with get_session() as session:
        session.add(trade)
        session.flush()
        session.expunge(trade)
    logger.info("Saved trade: %s %s %s lots", direction, symbol, lot_size)
    return trade


# ── trade_outcomes ────────────────────────────────────────────────────────────

def save_trade_outcome(
    trade_id:     int,
    exit_price:   float,
    pnl:          float,
    pips_gained:  float       = 0.0,
    close_reason: str         = "MANUAL",
    duration_sec: int         = 0,
) -> TradeOutcome:
    """
    Persist the closing details of a trade.
    Call when a position is confirmed closed by MT5.
    """
    outcome = TradeOutcome(
        trade_id     = trade_id,
        exit_price   = exit_price,
        pnl          = pnl,
        pips_gained  = pips_gained,
        close_reason = close_reason,
        closed_at    = datetime.utcnow(),
        duration_sec = duration_sec,
    )
    with get_session() as session:
        session.add(outcome)
        session.flush()
        session.expunge(outcome)
    logger.info("Saved trade outcome: trade_id=%s pnl=%.2f", trade_id, pnl)
    return outcome


# ── signals ───────────────────────────────────────────────────────────────────

def save_signal(
    symbol:          str,
    final_signal:    str,
    confidence:      float,
    buy_votes:       int,
    sell_votes:      int,
    none_votes:      int,
    total_evaluated: int,
    timeframe:       str              = "M15",
    trade_id:        Optional[int]    = None,
    top_strategies:  List[Dict[str, Any]] = None,
) -> Signal:
    """
    Persist a StrategyEngine evaluation result.
    Optionally also saves per-strategy vote detail rows.

    top_strategies format (matches main.py response):
        [{"name": "RSIStrategy", "confidence": 0.75, "reason": "RSI oversold"}]
    """
    signal = Signal(
        trade_id        = trade_id,
        symbol          = symbol,
        timeframe       = timeframe,
        final_signal    = final_signal,
        confidence      = confidence,
        buy_votes       = buy_votes,
        sell_votes      = sell_votes,
        none_votes      = none_votes,
        total_evaluated = total_evaluated,
        evaluated_at    = datetime.utcnow(),
    )
    with get_session() as session:
        session.add(signal)
        session.flush()  # get signal.id before adding children

        if top_strategies:
            for s in top_strategies:
                vote = StrategyVote(
                    signal_id     = signal.id,
                    strategy_name = s.get("name", "unknown"),
                    vote          = final_signal,
                    confidence    = s.get("confidence", 0.0),
                    reason        = s.get("reason", ""),
                )
                session.add(vote)

        session.expunge(signal)

    logger.debug("Saved signal: %s %s conf=%.2f", final_signal, symbol, confidence)
    return signal


# ── risk_events ───────────────────────────────────────────────────────────────

def save_risk_event(
    event_type:   str,
    detail:       str         = "",
    symbol:       Optional[str]   = None,
    lot_size:     Optional[float] = None,
    equity:       Optional[float] = None,
    drawdown_pct: Optional[float] = None,
) -> RiskEvent:
    """
    Log a risk-check failure or kill-switch toggle.
    Call inside risk_manager methods.

    event_type examples:
        KILL_SWITCH_ON, KILL_SWITCH_OFF,
        DAILY_LIMIT_HIT, DRAWDOWN_BREACH,
        LOT_REJECTED, FAT_FINGER
    """
    event = RiskEvent(
        event_type   = event_type,
        symbol       = symbol,
        lot_size     = lot_size,
        equity       = equity,
        drawdown_pct = drawdown_pct,
        detail       = detail,
        occurred_at  = datetime.utcnow(),
    )
    with get_session() as session:
        session.add(event)
        session.flush()
        session.expunge(event)
    logger.warning("Risk event logged: %s — %s", event_type, detail)
    return event


# ── price_snapshots ───────────────────────────────────────────────────────────

def save_price_snapshot(
    symbol: str,
    bid:    float,
    ask:    float,
) -> PriceSnapshot:
    """
    Save one bid/ask tick row.
    Called by the /api/price/{symbol} endpoint (optional — can be sampled).
    """
    spread_pips = round((ask - bid) / 0.0001, 2)
    snap = PriceSnapshot(
        symbol      = symbol,
        bid         = bid,
        ask         = ask,
        spread_pips = spread_pips,
        recorded_at = datetime.utcnow(),
    )
    with get_session() as session:
        session.add(snap)
        session.flush()
        session.expunge(snap)
    return snap


# ── performance_daily ─────────────────────────────────────────────────────────

def upsert_performance_daily(trade_date: Optional[str] = None) -> PerformanceDaily:
    """
    Compute and upsert the daily performance row for *trade_date*.
    Defaults to today (UTC).

    Aggregates all trade_outcomes joined to trades for that calendar day.
    """
    if trade_date is None:
        trade_date = date.today().isoformat()

    with get_session() as session:
        # Gather outcomes for the day
        rows = (
            session.query(TradeOutcome, Trade)
            .join(Trade, TradeOutcome.trade_id == Trade.id)
            .filter(func.date(TradeOutcome.closed_at) == trade_date)
            .all()
        )

        total   = len(rows)
        wins    = [r.TradeOutcome for r in rows if r.TradeOutcome.pnl > 0]
        losses  = [r.TradeOutcome for r in rows if r.TradeOutcome.pnl <= 0]
        pnl_all = [float(r.TradeOutcome.pnl) for r in rows]

        gross_profit = sum(p for p in pnl_all if p > 0)
        gross_loss   = sum(p for p in pnl_all if p <= 0)
        total_pnl    = sum(pnl_all)
        win_rate     = len(wins) / total if total else 0.0
        avg_pnl      = total_pnl / total if total else 0.0
        best         = max(pnl_all, default=0.0)
        worst        = min(pnl_all, default=0.0)

        # Upsert
        existing = (
            session.query(PerformanceDaily)
            .filter_by(trade_date=trade_date)
            .first()
        )
        if existing:
            rec = existing
        else:
            rec = PerformanceDaily(trade_date=trade_date)
            session.add(rec)

        rec.total_trades    = total
        rec.winning_trades  = len(wins)
        rec.losing_trades   = len(losses)
        rec.total_pnl       = total_pnl
        rec.gross_profit    = gross_profit
        rec.gross_loss      = gross_loss
        rec.win_rate        = win_rate
        rec.avg_pnl         = avg_pnl
        rec.best_trade_pnl  = best
        rec.worst_trade_pnl = worst
        rec.computed_at     = datetime.utcnow()

        session.flush()
        session.expunge(rec)

    logger.info("Upserted daily performance for %s: pnl=%.2f trades=%d", trade_date, total_pnl, total)
    return rec


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_trade_history(
    symbol:  Optional[str] = None,
    limit:   int = 50,
) -> List[Dict[str, Any]]:
    """
    Return recent trades with their outcomes as a list of dicts.
    Suitable for the /history page JSON response.
    """
    with get_session() as session:
        q = (
            session.query(Trade, TradeOutcome)
            .outerjoin(TradeOutcome, Trade.id == TradeOutcome.trade_id)
            .order_by(desc(Trade.opened_at))
        )
        if symbol:
            q = q.filter(Trade.symbol == symbol)
        rows = q.limit(limit).all()

    result = []
    for trade, outcome in rows:
        result.append({
            "id":           trade.id,
            "order_id":     trade.order_id,
            "symbol":       trade.symbol,
            "direction":    trade.direction,
            "lot_size":     float(trade.lot_size),
            "entry_price":  float(trade.entry_price),
            "sl_price":     float(trade.sl_price or 0),
            "tp_price":     float(trade.tp_price or 0),
            "state":        trade.state,
            "opened_at":    trade.opened_at.isoformat() if trade.opened_at else None,
            # outcome (may be None if trade still open)
            "exit_price":   float(outcome.exit_price)   if outcome else None,
            "pnl":          float(outcome.pnl)          if outcome else None,
            "close_reason": outcome.close_reason        if outcome else None,
            "closed_at":    outcome.closed_at.isoformat() if outcome else None,
        })
    return result


def get_performance_summary(days: int = 30) -> List[Dict[str, Any]]:
    """
    Return the last *days* rows from performance_daily.
    Used by the /performance page.
    """
    with get_session() as session:
        rows = (
            session.query(PerformanceDaily)
            .order_by(desc(PerformanceDaily.trade_date))
            .limit(days)
            .all()
        )
    return [
        {
            "date":          r.trade_date,
            "total_trades":  r.total_trades,
            "winning":       r.winning_trades,
            "losing":        r.losing_trades,
            "total_pnl":     float(r.total_pnl or 0),
            "win_rate":      round((r.win_rate or 0) * 100, 1),
            "avg_pnl":       float(r.avg_pnl or 0),
            "best_trade":    float(r.best_trade_pnl or 0),
            "worst_trade":   float(r.worst_trade_pnl or 0),
        }
        for r in rows
    ]


def get_recent_signals(symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Return recent signal evaluations — useful for the dashboard signal log.
    """
    with get_session() as session:
        q = (
            session.query(Signal)
            .order_by(desc(Signal.evaluated_at))
        )
        if symbol:
            q = q.filter(Signal.symbol == symbol)
        rows = q.limit(limit).all()

    return [
        {
            "id":             r.id,
            "symbol":         r.symbol,
            "timeframe":      r.timeframe,
            "final_signal":   r.final_signal,
            "confidence":     round(r.confidence * 100, 1),
            "buy_votes":      r.buy_votes,
            "sell_votes":     r.sell_votes,
            "none_votes":     r.none_votes,
            "total_evaluated":r.total_evaluated,
            "evaluated_at":   r.evaluated_at.isoformat() if r.evaluated_at else None,
        }
        for r in rows
    ]
