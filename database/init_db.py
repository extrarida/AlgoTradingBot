"""
database/init_db.py
────────────────────
Creates all database tables from the ORM models.
Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.

Run from the project root:
    python -m database.init_db

Optional flags:
    --seed      Insert sample data (useful for UI development)
    --drop      Drop and recreate all tables (WARNING: deletes all data)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_tables(drop_first: bool = False) -> None:
    """Create (or recreate) all tables."""
    from .connection import engine
    from .models import Base

    if drop_first:
        logger.warning("Dropping all tables...")
        Base.metadata.drop_all(engine)
        logger.warning("All tables dropped.")

    logger.info("Creating tables...")
    Base.metadata.create_all(engine)
    logger.info("Tables created successfully.")


def seed_sample_data() -> None:
    """
    Insert a small amount of realistic-looking sample data.
    Useful for testing the UI without a live MT5 connection.
    """
    from .connection import get_session
    from .models import (
        Account, PerformanceDaily, RiskEvent, Signal,
        StrategyVote, Trade, TradeOutcome,
    )

    logger.info("Seeding sample data...")

    with get_session() as session:
        # -- Account snapshot
        acc = Account(
            login=12345678, server="Demo-Server", balance=10000.00,
            equity=10250.00, margin=150.00, free_margin=10100.00,
            currency="USD", leverage=100, mock_mode=True,
        )
        session.add(acc)
        session.flush()

        # -- Two sample trades
        trade1 = Trade(
            account_id=acc.id, order_id=100001, deal_id=200001,
            symbol="EURUSD", direction="BUY", lot_size=0.10,
            entry_price=1.08500, sl_price=1.08000, tp_price=1.09500,
            sl_pips=50, tp_pips=100, state="FILLED",
            opened_at=datetime.utcnow() - timedelta(hours=3),
        )
        trade2 = Trade(
            account_id=acc.id, order_id=100002, deal_id=200002,
            symbol="GBPUSD", direction="SELL", lot_size=0.05,
            entry_price=1.26700, sl_price=1.27200, tp_price=1.25700,
            sl_pips=50, tp_pips=100, state="FILLED",
            opened_at=datetime.utcnow() - timedelta(hours=1),
        )
        session.add_all([trade1, trade2])
        session.flush()

        # -- Outcome for trade1 (closed, won)
        outcome1 = TradeOutcome(
            trade_id=trade1.id, exit_price=1.09500,
            pnl=100.00, pips_gained=100,
            close_reason="TP", duration_sec=10800,
            closed_at=datetime.utcnow() - timedelta(minutes=30),
        )
        session.add(outcome1)

        # -- Signal that triggered trade1
        sig = Signal(
            trade_id=trade1.id, symbol="EURUSD", timeframe="M15",
            final_signal="BUY", confidence=0.72,
            buy_votes=18, sell_votes=4, none_votes=18, total_evaluated=40,
        )
        session.add(sig)
        session.flush()

        # -- Top strategy votes for that signal
        votes = [
            StrategyVote(signal_id=sig.id, strategy_name="RSIBuyStrategy",
                         vote="BUY", confidence=0.85, reason="RSI < 30, oversold"),
            StrategyVote(signal_id=sig.id, strategy_name="MACDBuyStrategy",
                         vote="BUY", confidence=0.78, reason="MACD bullish crossover"),
            StrategyVote(signal_id=sig.id, strategy_name="BollingerBuyStrategy",
                         vote="BUY", confidence=0.70, reason="Price below lower band"),
        ]
        session.add_all(votes)

        # -- Risk event (kill switch test)
        risk_evt = RiskEvent(
            event_type="KILL_SWITCH_ON",
            detail="Manual activation by user",
            equity=10250.00,
        )
        session.add(risk_evt)

        # -- Daily performance row
        perf = PerformanceDaily(
            trade_date=datetime.utcnow().date().isoformat(),
            total_trades=2, winning_trades=1, losing_trades=0,
            total_pnl=100.00, gross_profit=100.00, gross_loss=0.00,
            win_rate=1.0, avg_pnl=100.00,
            best_trade_pnl=100.00, worst_trade_pnl=0.00,
        )
        session.add(perf)

    logger.info("Sample data inserted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AlgoTradingBot — DB initialiser")
    parser.add_argument("--seed", action="store_true", help="Insert sample data after creating tables")
    parser.add_argument("--drop", action="store_true", help="Drop all tables first (DELETES ALL DATA)")
    args = parser.parse_args()

    if args.drop:
        confirm = input("⚠  This will DELETE all data. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    create_tables(drop_first=args.drop)

    if args.seed:
        seed_sample_data()

    logger.info("Done. Run 'python -m database.init_db --help' for options.")


if __name__ == "__main__":
    main()
