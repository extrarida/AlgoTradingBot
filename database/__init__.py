"""
database/
─────────
AlgoTradingBot database layer.

Public API
----------
    from database.connection  import get_session, check_connection
    from database.models      import Trade, Signal, Account, ...
    from database.repository  import (
        save_trade, save_signal, save_account_snapshot,
        save_risk_event, save_price_snapshot,
        get_trade_history, get_performance_summary,
    )
    from database.init_db     import create_tables
"""

from .connection import check_connection, get_session
from .models import (
    Account, PerformanceDaily, PriceSnapshot,
    RiskEvent, Signal, StrategyVote, Trade, TradeOutcome,
)
from .repository import (
    get_performance_summary,
    get_recent_signals,
    get_trade_history,
    save_account_snapshot,
    save_price_snapshot,
    save_risk_event,
    save_signal,
    save_trade,
    save_trade_outcome,
    upsert_performance_daily,
)

__all__ = [
    # connection
    "get_session", "check_connection",
    # models
    "Account", "Trade", "TradeOutcome", "Signal", "StrategyVote",
    "RiskEvent", "PriceSnapshot", "PerformanceDaily",
    # repository
    "save_account_snapshot", "save_trade", "save_trade_outcome",
    "save_signal", "save_risk_event", "save_price_snapshot",
    "upsert_performance_daily",
    "get_trade_history", "get_performance_summary", "get_recent_signals",
]
