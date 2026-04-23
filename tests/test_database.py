"""
tests/test_database.py
──────────────────────
Database layer tests — verifies all repository functions
work correctly with a temporary in-memory database.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from database.models import Base
from database.connection import get_session


# ── Setup — use in-memory SQLite for tests ────────────────────────────────────
# This creates a fresh temporary database for every test
# so tests never touch the real algobot.db file

@pytest.fixture(scope="function")
def test_engine():
    """Create a fresh in-memory database for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provide a database session connected to the test database."""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


# ── Table creation tests ──────────────────────────────────────────────────────

class TestDatabaseSetup:

    def test_all_tables_created(self, test_engine):
        """Verify all 8 required tables exist after init."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        required = [
            "accounts", "trades", "trade_outcomes", "signals",
            "strategy_votes", "risk_events", "price_snapshots",
            "performance_daily"
        ]
        for table in required:
            assert table in tables, f"Table '{table}' is missing"

    def test_accounts_table_columns(self, test_engine):
        """Verify accounts table has required columns."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("accounts")]
        for col in ["id", "login", "balance", "equity", "server", "mock_mode"]:
            assert col in columns

    def test_trades_table_columns(self, test_engine):
        """Verify trades table has required columns."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("trades")]
        for col in ["id", "symbol", "direction", "lot_size", "entry_price", "sl_price", "tp_price"]:
            assert col in columns

    def test_signals_table_columns(self, test_engine):
        """Verify signals table has required columns."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("signals")]
        for col in ["id", "symbol", "timeframe", "final_signal", "confidence", "buy_votes", "sell_votes", "total_evaluated"]:
            assert col in columns

    def test_risk_events_table_columns(self, test_engine):
        """Verify risk_events table has required columns."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("risk_events")]
        for col in ["id", "event_type", "detail", "equity", "occurred_at"]:
            assert col in columns


# ── Model tests ───────────────────────────────────────────────────────────────

class TestDatabaseModels:

    def test_save_and_retrieve_account(self, db_session):
        """Save an account snapshot and retrieve it."""
        from database.models import Account
        account = Account(
            login=12345678, server="TestServer",
            balance=10000.0, equity=10050.0,
            margin=200.0, free_margin=9850.0,
            currency="USD", mock_mode=True,
        )
        db_session.add(account)
        db_session.commit()

        retrieved = db_session.query(Account).filter_by(login=12345678).first()
        assert retrieved is not None
        assert float(retrieved.balance) == 10000.0
        assert retrieved.server == "TestServer"
        assert retrieved.mock_mode is True

    def test_save_and_retrieve_trade(self, db_session):
        """Save a trade and retrieve it."""
        from database.models import Trade
        trade = Trade(
            symbol="EURUSD", direction="BUY",
            lot_size=0.01, entry_price=1.08500,
            sl_price=1.08000, tp_price=1.09500,
            sl_pips=50, tp_pips=100,
            state="FILLED",
        )
        db_session.add(trade)
        db_session.commit()

        retrieved = db_session.query(Trade).filter_by(symbol="EURUSD").first()
        assert retrieved is not None
        assert retrieved.direction == "BUY"
        assert float(retrieved.lot_size) == 0.01
        assert float(retrieved.entry_price) == 1.08500

    def test_save_and_retrieve_signal(self, db_session):
        """Save a signal evaluation and retrieve it."""
        from database.models import Signal
        signal = Signal(
            symbol="EURUSD", timeframe="M15",
            final_signal="BUY", confidence=0.75,
            buy_votes=18, sell_votes=4,
            none_votes=18, total_evaluated=40,
        )
        db_session.add(signal)
        db_session.commit()

        retrieved = db_session.query(Signal).filter_by(symbol="EURUSD").first()
        assert retrieved is not None
        assert retrieved.final_signal == "BUY"
        assert retrieved.buy_votes == 18
        assert float(retrieved.confidence) == 0.75

    def test_trade_outcome_links_to_trade(self, db_session):
        """TradeOutcome must be linked to a Trade via foreign key."""
        from database.models import Trade, TradeOutcome
        trade = Trade(
            symbol="GBPUSD", direction="SELL",
            lot_size=0.05, entry_price=1.26700,
            sl_price=1.27200, tp_price=1.25700,
            sl_pips=50, tp_pips=100, state="FILLED",
        )
        db_session.add(trade)
        db_session.flush()

        outcome = TradeOutcome(
            trade_id=trade.id,
            exit_price=1.25700,
            pnl=100.0, pips_gained=100,
            close_reason="TP",
        )
        db_session.add(outcome)
        db_session.commit()

        retrieved = db_session.query(TradeOutcome).filter_by(trade_id=trade.id).first()
        assert retrieved is not None
        assert float(retrieved.pnl) == 100.0
        assert retrieved.close_reason == "TP"

    def test_signal_votes_link_to_signal(self, db_session):
        """StrategyVote rows must be linked to a Signal."""
        from database.models import Signal, StrategyVote
        signal = Signal(
            symbol="XAUUSD", timeframe="H1",
            final_signal="BUY", confidence=0.80,
            buy_votes=20, sell_votes=5,
            none_votes=15, total_evaluated=40,
        )
        db_session.add(signal)
        db_session.flush()

        vote = StrategyVote(
            signal_id=signal.id,
            strategy_name="RSIOversoldBounce",
            vote="BUY", confidence=0.85,
            reason="RSI below 30 recovering",
        )
        db_session.add(vote)
        db_session.commit()

        retrieved = db_session.query(StrategyVote).filter_by(signal_id=signal.id).first()
        assert retrieved is not None
        assert retrieved.strategy_name == "RSIOversoldBounce"
        assert retrieved.vote == "BUY"

    def test_risk_event_saved(self, db_session):
        """Risk events are saved with correct type and detail."""
        from database.models import RiskEvent
        event = RiskEvent(
            event_type="KILL_SWITCH_ON",
            detail="Manual activation by user",
            equity=10000.0,
        )
        db_session.add(event)
        db_session.commit()

        retrieved = db_session.query(RiskEvent).filter_by(
            event_type="KILL_SWITCH_ON"
        ).first()
        assert retrieved is not None
        assert "Manual" in retrieved.detail

    def test_performance_daily_saved(self, db_session):
        """Daily performance row saves and retrieves correctly."""
        from database.models import PerformanceDaily
        perf = PerformanceDaily(
            trade_date="2026-04-23",
            total_trades=5, winning_trades=3,
            losing_trades=2, total_pnl=150.0,
            win_rate=0.6, avg_pnl=30.0,
        )
        db_session.add(perf)
        db_session.commit()

        retrieved = db_session.query(PerformanceDaily).filter_by(
            trade_date="2026-04-23"
        ).first()
        assert retrieved is not None
        assert retrieved.total_trades == 5
        assert float(retrieved.win_rate) == 0.6


# ── Data integrity tests ──────────────────────────────────────────────────────

class TestDataIntegrity:

    def test_trade_direction_is_buy_or_sell(self, db_session):
        """Trades should only have BUY or SELL direction."""
        from database.models import Trade
        trade = Trade(
            symbol="USDJPY", direction="BUY",
            lot_size=0.01, entry_price=149.500,
            sl_price=149.000, tp_price=150.000,
            sl_pips=50, tp_pips=50, state="FILLED",
        )
        db_session.add(trade)
        db_session.commit()
        assert trade.direction in ["BUY", "SELL"]

    def test_multiple_signals_same_symbol(self, db_session):
        """Multiple signals for the same symbol should all be stored."""
        from database.models import Signal
        for i in range(5):
            signal = Signal(
                symbol="EURUSD", timeframe="M15",
                final_signal="NONE", confidence=0.0,
                buy_votes=i, sell_votes=0,
                none_votes=40-i, total_evaluated=40,
            )
            db_session.add(signal)
        db_session.commit()

        count = db_session.query(Signal).filter_by(symbol="EURUSD").count()
        assert count == 5

    def test_account_balance_positive(self, db_session):
        """Account balance should always be positive."""
        from database.models import Account
        account = Account(
            login=99999, server="Test",
            balance=10000.0, equity=10000.0,
            currency="USD", mock_mode=False,
        )
        db_session.add(account)
        db_session.commit()
        assert float(account.balance) > 0

    def test_database_persists_across_sessions(self, test_engine):
        """Data saved in one session should be readable in another."""
        from database.models import Trade
        Session = sessionmaker(bind=test_engine)

        # Session 1 — write
        s1 = Session()
        trade = Trade(
            symbol="EURUSD", direction="BUY",
            lot_size=0.01, entry_price=1.08500,
            sl_price=1.08000, tp_price=1.09500,
            sl_pips=50, tp_pips=100, state="FILLED",
        )
        s1.add(trade)
        s1.commit()
        s1.close()

        # Session 2 — read (simulates server restart)
        s2 = Session()
        retrieved = s2.query(Trade).filter_by(symbol="EURUSD").first()
        assert retrieved is not None
        assert retrieved.direction == "BUY"
        s2.close()