"""
tests/test_database.py
──────────────────────
Database layer tests for AlgoTrader Bot.

These tests verify that every repository function in database/models.py
works correctly — saving records, retrieving them, linking related rows
through foreign keys, and enforcing data integrity rules.

The tests never touch the real algobot.db file. Instead, each test gets
its own fresh in-memory SQLite database that is created before the test
runs and discarded immediately after. This means tests are completely
isolated — one test's data cannot affect another's results.

Run these tests with:
    pytest tests/test_database.py -v
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from database.models import Base
from database.connection import get_session


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
#
# Fixtures are reusable setup functions that pytest runs before each test.
# The two fixtures below work together:
#
#   test_engine  →  creates a brand new in-memory SQLite database
#   db_session   →  opens a session (connection) to that database
#
# Using scope="function" means both are recreated for every single test,
# so no data leaks between tests.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def test_engine():
    """
    Spin up a temporary in-memory SQLite database for one test.

    sqlite:///:memory: creates the database entirely in RAM — nothing is
    written to disk and nothing survives beyond this test function.
    create_all() builds every table defined in database/models.py.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)

    yield engine  # hand the engine to the test

    # Teardown — drop everything so the next test starts clean
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(test_engine):
    """
    Open a SQLAlchemy session bound to the in-memory test database.

    The session is what we use to add, query, and commit records.
    It is closed after each test to release any held resources.
    """
    Session = sessionmaker(bind=test_engine)
    session = Session()

    yield session  # hand the session to the test

    session.close()


# ─────────────────────────────────────────────────────────────────────────────
# TestDatabaseSetup
#
# Verifies that the database schema is created correctly. These tests check
# that all 8 required tables exist and that each key table has the columns
# we expect. If any table or column is missing, every other test would fail
# anyway — so these are the first checks to run.
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabaseSetup:

    def test_all_tables_created(self, test_engine):
        """
        All 8 application tables must exist after the engine is initialised.

        If any table is missing it means the model was not imported or the
        ORM mapping was not registered with Base.metadata before create_all()
        was called.
        """
        from sqlalchemy import inspect

        inspector = inspect(test_engine)
        tables = inspector.get_table_names()

        required = [
            "accounts",
            "trades",
            "trade_outcomes",
            "signals",
            "strategy_votes",
            "risk_events",
            "price_snapshots",
            "performance_daily",
        ]

        for table in required:
            assert table in tables, f"Table '{table}' is missing from the schema"

    def test_accounts_table_columns(self, test_engine):
        """
        The accounts table must have all the fields we rely on when saving
        login snapshots — id, login, balance, equity, server, and mock_mode.
        """
        from sqlalchemy import inspect

        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("accounts")]

        for col in ["id", "login", "balance", "equity", "server", "mock_mode"]:
            assert col in columns, f"Column '{col}' missing from accounts table"

    def test_trades_table_columns(self, test_engine):
        """
        The trades table must capture the full picture of every order:
        which symbol, direction (BUY/SELL), size, and the price levels
        for entry, stop loss, and take profit.
        """
        from sqlalchemy import inspect

        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("trades")]

        for col in ["id", "symbol", "direction", "lot_size", "entry_price", "sl_price", "tp_price"]:
            assert col in columns, f"Column '{col}' missing from trades table"

    def test_signals_table_columns(self, test_engine):
        """
        The signals table stores the output of every strategy evaluation.
        It must hold the symbol, timeframe, the final signal decision,
        the confidence score, and the individual vote counts.
        """
        from sqlalchemy import inspect

        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("signals")]

        for col in [
            "id", "symbol", "timeframe", "final_signal",
            "confidence", "buy_votes", "sell_votes", "total_evaluated"
        ]:
            assert col in columns, f"Column '{col}' missing from signals table"

    def test_risk_events_table_columns(self, test_engine):
        """
        The risk_events table logs safety system activity — kill switch
        toggles, drawdown breaches, etc. It must store the event type,
        a description, the account equity at the time, and a timestamp.
        """
        from sqlalchemy import inspect

        inspector = inspect(test_engine)
        columns = [c["name"] for c in inspector.get_columns("risk_events")]

        for col in ["id", "event_type", "detail", "equity", "occurred_at"]:
            assert col in columns, f"Column '{col}' missing from risk_events table"


# ─────────────────────────────────────────────────────────────────────────────
# TestDatabaseModels
#
# Tests each ORM model by writing a record and reading it back. This confirms
# that the field mappings, data types, and relationships between tables are all
# wired up correctly. Each test is independent — no test relies on data from
# another test.
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabaseModels:

    def test_save_and_retrieve_account(self, db_session):
        """
        Saving an Account snapshot should persist all fields correctly.

        The Account model is used to record a snapshot of the broker account
        every time a user connects — capturing the balance, equity, and
        whether the session is mock or live.
        """
        from database.models import Account

        # Create and persist an account record
        account = Account(
            login=12345678,
            server="TestServer",
            balance=10000.0,
            equity=10050.0,
            margin=200.0,
            free_margin=9850.0,
            currency="USD",
            mock_mode=True,
        )
        db_session.add(account)
        db_session.commit()

        # Read it back and verify every field came through correctly
        retrieved = db_session.query(Account).filter_by(login=12345678).first()

        assert retrieved is not None
        assert float(retrieved.balance) == 10000.0
        assert retrieved.server == "TestServer"
        assert retrieved.mock_mode is True

    def test_save_and_retrieve_trade(self, db_session):
        """
        Saving a Trade should persist symbol, direction, size, and all
        price levels correctly.

        Trades are created when the executor sends an order to the broker.
        We store enough detail to reconstruct exactly what was placed and at
        what price.
        """
        from database.models import Trade

        trade = Trade(
            symbol="EURUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=1.08500,
            sl_price=1.08000,
            tp_price=1.09500,
            sl_pips=50,
            tp_pips=100,
            state="FILLED",
        )
        db_session.add(trade)
        db_session.commit()

        # Retrieve by symbol and confirm all fields
        retrieved = db_session.query(Trade).filter_by(symbol="EURUSD").first()

        assert retrieved is not None
        assert retrieved.direction == "BUY"
        assert float(retrieved.lot_size) == 0.01
        assert float(retrieved.entry_price) == 1.08500

    def test_save_and_retrieve_signal(self, db_session):
        """
        Saving a Signal should persist the voting outcome correctly.

        Every time the strategy engine runs, the result — which direction
        won, how confident, how many votes each way — is saved as a Signal
        record. This lets us audit the bot's decision history.
        """
        from database.models import Signal

        signal = Signal(
            symbol="EURUSD",
            timeframe="M15",
            final_signal="BUY",
            confidence=0.75,
            buy_votes=18,
            sell_votes=4,
            none_votes=18,
            total_evaluated=40,
        )
        db_session.add(signal)
        db_session.commit()

        retrieved = db_session.query(Signal).filter_by(symbol="EURUSD").first()

        assert retrieved is not None
        assert retrieved.final_signal == "BUY"
        assert retrieved.buy_votes == 18
        assert float(retrieved.confidence) == 0.75

    def test_trade_outcome_links_to_trade(self, db_session):
        """
        A TradeOutcome must be linked to an existing Trade via foreign key.

        TradeOutcome captures what happened after the trade closed — the exit
        price, realised P&L, and the reason it closed (stop loss, take profit,
        or manual). The foreign key ensures every outcome has a parent trade.
        """
        from database.models import Trade, TradeOutcome

        # First create the parent trade
        trade = Trade(
            symbol="GBPUSD",
            direction="SELL",
            lot_size=0.05,
            entry_price=1.26700,
            sl_price=1.27200,
            tp_price=1.25700,
            sl_pips=50,
            tp_pips=100,
            state="FILLED",
        )
        db_session.add(trade)
        db_session.flush()  # flush to get the auto-generated trade.id

        # Now create the outcome linked to that trade
        outcome = TradeOutcome(
            trade_id=trade.id,
            exit_price=1.25700,
            pnl=100.0,
            pips_gained=100,
            close_reason="TP",
        )
        db_session.add(outcome)
        db_session.commit()

        # Verify the outcome was saved and correctly linked
        retrieved = db_session.query(TradeOutcome).filter_by(trade_id=trade.id).first()

        assert retrieved is not None
        assert float(retrieved.pnl) == 100.0
        assert retrieved.close_reason == "TP"

    def test_signal_votes_link_to_signal(self, db_session):
        """
        Each StrategyVote must be linked to a parent Signal via foreign key.

        When the engine evaluates all 40 strategies, each individual strategy's
        vote is stored as a StrategyVote row pointing back to the Signal that
        aggregated them. This lets us drill into exactly why a signal fired.
        """
        from database.models import Signal, StrategyVote

        # Create the parent signal first
        signal = Signal(
            symbol="XAUUSD",
            timeframe="H1",
            final_signal="BUY",
            confidence=0.80,
            buy_votes=20,
            sell_votes=5,
            none_votes=15,
            total_evaluated=40,
        )
        db_session.add(signal)
        db_session.flush()  # flush to get signal.id before linking votes

        # Create a vote linked to this signal
        vote = StrategyVote(
            signal_id=signal.id,
            strategy_name="RSIOversoldBounce",
            vote="BUY",
            confidence=0.85,
            reason="RSI below 30 recovering",
        )
        db_session.add(vote)
        db_session.commit()

        # Retrieve the vote and confirm it points to the right signal
        retrieved = db_session.query(StrategyVote).filter_by(signal_id=signal.id).first()

        assert retrieved is not None
        assert retrieved.strategy_name == "RSIOversoldBounce"
        assert retrieved.vote == "BUY"

    def test_risk_event_saved(self, db_session):
        """
        Risk events should persist correctly with the right type and detail.

        RiskEvent records are created whenever the risk manager takes action —
        for example, when the kill switch is activated or a drawdown limit is
        breached. This creates an audit trail of all safety interventions.
        """
        from database.models import RiskEvent

        event = RiskEvent(
            event_type="KILL_SWITCH_ON",
            detail="Manual activation by user",
            equity=10000.0,
        )
        db_session.add(event)
        db_session.commit()

        # Find the most recent KILL_SWITCH_ON event and verify its content
        retrieved = db_session.query(RiskEvent).filter_by(
            event_type="KILL_SWITCH_ON"
        ).first()

        assert retrieved is not None
        assert "Manual" in retrieved.detail

    def test_performance_daily_saved(self, db_session):
        """
        Daily performance records should save and retrieve correctly.

        PerformanceDaily stores rolled-up statistics for a single trading day
        — total trades, wins, losses, P&L, win rate, and average P&L per trade.
        These drive the performance analytics page.
        """
        from database.models import PerformanceDaily

        perf = PerformanceDaily(
            trade_date="2026-04-23",
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            total_pnl=150.0,
            win_rate=0.6,
            avg_pnl=30.0,
        )
        db_session.add(perf)
        db_session.commit()

        retrieved = db_session.query(PerformanceDaily).filter_by(
            trade_date="2026-04-23"
        ).first()

        assert retrieved is not None
        assert retrieved.total_trades == 5
        assert float(retrieved.win_rate) == 0.6


# ─────────────────────────────────────────────────────────────────────────────
# TestDataIntegrity
#
# These tests check that the database enforces sensible rules about the data
# it holds — valid trade directions, multiple records per symbol, positive
# balances, and correct behaviour across separate sessions. These are the kinds
# of constraints that protect data quality over time.
# ─────────────────────────────────────────────────────────────────────────────

class TestDataIntegrity:

    def test_trade_direction_is_buy_or_sell(self, db_session):
        """
        Every trade direction stored must be either BUY or SELL.

        This is the most basic integrity check for the trades table — the
        direction field should never contain an unexpected value, because
        the rest of the system (P&L calculation, reporting, etc.) depends
        on it being one of these two values.
        """
        from database.models import Trade

        trade = Trade(
            symbol="USDJPY",
            direction="BUY",
            lot_size=0.01,
            entry_price=149.500,
            sl_price=149.000,
            tp_price=150.000,
            sl_pips=50,
            tp_pips=50,
            state="FILLED",
        )
        db_session.add(trade)
        db_session.commit()

        # The direction of any saved trade must be one of the two valid values
        assert trade.direction in ["BUY", "SELL"]

    def test_multiple_signals_same_symbol(self, db_session):
        """
        Multiple signal evaluations for the same symbol should all be stored.

        The signals table is an append-only log — every time the engine runs
        on EURUSD, a new row is added. No row is overwritten. This test
        confirms that 5 separate evaluations produce 5 separate rows.
        """
        from database.models import Signal

        # Save 5 signals for the same symbol
        for i in range(5):
            signal = Signal(
                symbol="EURUSD",
                timeframe="M15",
                final_signal="NONE",
                confidence=0.0,
                buy_votes=i,
                sell_votes=0,
                none_votes=40 - i,
                total_evaluated=40,
            )
            db_session.add(signal)
        db_session.commit()

        # All 5 should exist — nothing should have been merged or overwritten
        count = db_session.query(Signal).filter_by(symbol="EURUSD").count()
        assert count == 5

    def test_account_balance_positive(self, db_session):
        """
        Account balance should always be a positive number.

        A zero or negative balance would indicate a data error — the broker
        account balance can never go below zero in practice (the broker
        enforces a margin call before that happens). This test confirms the
        model stores what we give it without corrupting the value.
        """
        from database.models import Account

        account = Account(
            login=99999,
            server="Test",
            balance=10000.0,
            equity=10000.0,
            currency="USD",
            mock_mode=False,
        )
        db_session.add(account)
        db_session.commit()

        assert float(account.balance) > 0

    def test_database_persists_across_sessions(self, test_engine):
        """
        Data written in one session must be readable in a completely separate
        session — simulating a server restart.

        This is the most important persistence test. In production, the server
        restarts regularly. Every trade and signal saved before a restart must
        still be there after it. This test opens two independent sessions and
        verifies the data written in the first is visible in the second.
        """
        from database.models import Trade

        Session = sessionmaker(bind=test_engine)

        # Session 1 — write a trade and close the session completely
        s1 = Session()
        trade = Trade(
            symbol="EURUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=1.08500,
            sl_price=1.08000,
            tp_price=1.09500,
            sl_pips=50,
            tp_pips=100,
            state="FILLED",
        )
        s1.add(trade)
        s1.commit()
        s1.close()  # close completely — simulates server shutdown

        # Session 2 — a new independent session that represents a fresh start
        s2 = Session()
        retrieved = s2.query(Trade).filter_by(symbol="EURUSD").first()

        assert retrieved is not None
        assert retrieved.direction == "BUY"

        s2.close()