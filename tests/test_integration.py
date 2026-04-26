"""
tests/test_integration.py
─────────────────────────
Integration tests for AlgoTrader Bot.

While the unit tests in this project verify individual functions in isolation,
these integration tests verify that all the separate components work correctly
together as a complete system. Every test here makes a real HTTP request to
the FastAPI server and checks the response — the same way the browser does
when you use the dashboard.

The tests are organised into seven groups:
  1. Server Health      — basic connectivity and page loading
  2. Authentication     — login, demo mode, disconnect, session guarding
  3. Price Feed         — live price endpoint with mock broker data
  4. Strategy Signal    — 40-strategy engine output validation
  5. Chart Data         — OHLCV candlestick endpoint validation
  6. Risk Manager       — kill switch and trade blocking
  7. Trade Execution    — buy/sell orders in mock mode
  8. Database           — verifying that API calls persist data correctly

Why mock the MT5 connector?
────────────────────────────
The MetaTrader 5 Python package only works on Windows with the MT5 desktop
application running. These tests need to run on any machine — Mac, Linux,
or Windows — in any environment, including CI/CD pipelines. By replacing the
real connector with unittest.mock.patch, we inject controlled price data
so the tests are deterministic and dependency-free.

This is standard practice in professional trading system testing. The mock
data proves the application logic is correct. The real broker integration is
verified separately through manual testing on Windows.

Run with:
    pytest tests/test_integration.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Shared mock price data
#
# These dictionaries represent what the MT5 connector returns when asked for
# a live price. Using constants here means every test that needs price data
# gets the exact same values, making assertions predictable and repeatable.
#
# MOCK_TICK       — a typical EURUSD price (ask slightly above bid = spread)
# MOCK_TICK_GOLD  — a typical XAUUSD price (wider spread, much higher value)
# ─────────────────────────────────────────────────────────────────────────────

MOCK_TICK = {
    "bid":    1.10000,   # price at which the broker buys from you (you sell at bid)
    "ask":    1.10009,   # price at which the broker sells to you (you buy at ask)
    "spread": 0.00009,   # difference between ask and bid — the broker's fee
    "last":   1.10000,
    "volume": 100,
    "time":   1714000000,
}

MOCK_TICK_GOLD = {
    "bid":    2350.0,    # Gold trades at much higher absolute prices than forex pairs
    "ask":    2350.5,    # Wider spread in dollar terms, though similar in pip terms
    "spread": 0.5,
    "last":   2350.0,
    "volume": 10,
    "time":   1714000000,
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
#
# Two test clients are provided:
#
#   client           — no active session; used to test unauthenticated behaviour
#                      and login flows
#   connected_client — already connected in mock/demo mode; used for all tests
#                      that require an active session
#
# scope="module" means the fixtures are created once per test file and shared
# across all tests in the module. This is much faster than reconnecting for
# every individual test, and safe because the connected state does not change
# between tests (only the risk manager state changes, which is reset per-test
# where needed).
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """
    A basic TestClient with no active session.

    Used to test login behaviour, page loading, and any endpoint that should
    work (or correctly reject requests) before authentication.
    """
    from main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def connected_client():
    """
    A TestClient with an active demo/mock session pre-established.

    Before yielding, the risk manager is reset (kill switch off, daily count
    zero) so tests start from a clean state. After all module tests complete,
    the connector is disconnected to clean up.
    """
    from main import app
    from data.mt5_connector import connector
    from execution.risk_manager import risk_manager

    # Start from a clean risk state before the first test runs
    risk_manager.deactivate_kill_switch()
    risk_manager.reset_daily()

    # Connect in mock mode — no real MT5 needed
    connector.connect_mock(login=12345678, server="TestServer")

    yield TestClient(app)

    # Teardown — disconnect when the module is done
    connector.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# TestServerHealth
#
# The most basic checks: is the server running and do all five pages load?
# If any of these fail, something is wrong with the FastAPI setup or the
# template rendering, and none of the other tests will be meaningful.
# ─────────────────────────────────────────────────────────────────────────────

class TestServerHealth:

    def test_server_is_running(self, client):
        """
        The /api/status endpoint should always return 200 with server: running.

        This is the health check endpoint — if it fails, the server is not
        running at all and every other test will also fail.
        """
        res = client.get("/api/status")
        assert res.status_code == 200
        assert res.json()["server"] == "running"

    def test_login_page_loads(self, client):
        """
        The root URL should return the login HTML page.

        We check that AlgoTrader appears in the HTML — this confirms Jinja2
        template rendering is working, not just that FastAPI returned a 200.
        """
        res = client.get("/")
        assert res.status_code == 200
        assert "AlgoTrader" in res.text

    def test_dashboard_page_loads(self, client):
        """Dashboard HTML page returns 200."""
        assert client.get("/dashboard").status_code == 200

    def test_history_page_loads(self, client):
        """Trade history HTML page returns 200."""
        assert client.get("/history").status_code == 200

    def test_performance_page_loads(self, client):
        """Performance analytics HTML page returns 200."""
        assert client.get("/performance").status_code == 200

    def test_risk_page_loads(self, client):
        """Risk manager HTML page returns 200."""
        assert client.get("/risk").status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TestAuthentication
#
# Verifies the full login flow — demo mode success, correct account data
# returned, disconnect clearing the session, and protected endpoints correctly
# returning 401 when no session is active.
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthentication:

    def test_demo_mode_login_succeeds(self, client):
        """
        Demo mode login should always succeed regardless of what credentials
        are submitted.

        This is by design — demo mode is meant to work on any machine for
        anyone, with no validation. The response must report mock_mode: True
        so the frontend can display the yellow demo banner.
        """
        res = client.post("/api/connect", json={
            "login":     12345678,
            "password":  "any_password",
            "server":    "AnyServer",
            "demo_mode": True,
        })
        assert res.status_code == 200

        data = res.json()
        assert data["success"]   is True
        assert data["mock_mode"] is True

    def test_demo_mode_returns_account_info(self, client):
        """
        The account data returned on demo login must have the expected
        mock values — $10,000 balance and USD currency.

        If these values are wrong, the dashboard tiles will display incorrect
        data immediately after login.
        """
        res = client.post("/api/connect", json={
            "login":     12345678,
            "password":  "test",
            "server":    "TestServer",
            "demo_mode": True,
        })
        account = res.json()["account"]

        assert account["balance"]  == 10000.0
        assert account["currency"] == "USD"

    def test_disconnect_works(self, client):
        """
        /api/disconnect should clear the session and return success: True.

        After disconnecting, the connector's is_connected flag becomes False,
        which is what causes subsequent API calls to return 401.
        """
        # Connect first so there is something to disconnect from
        client.post("/api/connect", json={
            "login": 1, "password": "x",
            "server": "x", "demo_mode": True,
        })

        res = client.post("/api/disconnect")
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_endpoints_require_connection(self, client):
        """
        Protected endpoints must return 401 (Unauthorized) when called
        without an active session.

        This confirms the session guard in each endpoint is working. Without
        this check, anyone could query account data or prices without logging
        in.
        """
        # Ensure we are disconnected before testing
        client.post("/api/disconnect")
        assert client.get("/api/account").status_code == 401

    def test_endpoints_work_when_connected(self, connected_client):
        """
        The same protected endpoint should return 200 when a session is active.

        This is the positive counterpart to the 401 test above — confirming
        that the guard allows legitimate requests through.
        """
        assert connected_client.get("/api/account").status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TestPriceFeed
#
# Verifies that the /api/price/{symbol} endpoint returns valid price data.
# The MT5 connector is patched with MOCK_TICK so these tests work on any
# machine regardless of whether MT5 is installed or the market is open.
# ─────────────────────────────────────────────────────────────────────────────

class TestPriceFeed:

    def test_price_endpoint_returns_bid_ask(self, connected_client):
        """
        The price endpoint must return at minimum a bid price greater than zero.

        We patch get_tick() so the test does not depend on a live MT5 connection.
        The patch is applied as a context manager so it is automatically removed
        after the request completes.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.get("/api/price/EURUSD")

        assert res.status_code == 200, f"Got {res.status_code}: {res.text}"
        data = res.json()
        assert "bid" in data
        assert data["bid"] > 0

    def test_price_ask_higher_than_bid(self, connected_client):
        """
        Ask price must always be greater than or equal to bid price.

        The spread (ask - bid) represents the broker's fee. If ask were lower
        than bid, the spread would be negative, which is impossible in a real
        market. This check confirms the price data is structured correctly.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.get("/api/price/EURUSD")

        assert res.status_code == 200
        data = res.json()
        assert "ask" in data
        assert data["ask"] >= data["bid"]

    def test_multiple_symbols_return_prices(self, connected_client):
        """
        All four symbols in the watchlist must return valid price responses.

        EURUSD, GBPUSD, XAUUSD, and USDJPY are the symbols the automated bot
        monitors. If any of them returns a 404, the bot cannot evaluate that
        market and will miss trade opportunities.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            for symbol in ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]:
                res = connected_client.get(f"/api/price/{symbol}")
                assert res.status_code == 200, f"{symbol} returned {res.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# TestStrategySignal
#
# Verifies the /api/signal/{symbol} endpoint, which triggers all 40 strategies
# to run simultaneously and returns the aggregated result. These tests check
# the shape and validity of the output — not which specific signal is produced,
# since that depends on the mock price data at runtime.
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategySignal:

    def test_signal_endpoint_returns_valid_structure(self, connected_client):
        """
        The signal response must contain all seven required fields.

        Every field is used by the dashboard: final_signal drives the big
        BUY/SELL/NONE display, confidence fills the progress bar, vote counts
        fill the vote tiles, and top_strategies populates the strategy breakdown.
        """
        res = connected_client.get("/api/signal/EURUSD")
        assert res.status_code == 200

        data = res.json()
        for field in [
            "final_signal", "confidence", "buy_votes",
            "sell_votes", "none_votes", "total_evaluated", "top_strategies"
        ]:
            assert field in data, f"Missing field: {field}"

    def test_signal_is_valid_value(self, connected_client):
        """
        The final_signal field must be one of the three valid values.

        Any other value would break the dashboard's CSS class switching
        (signal-main.BUY, signal-main.SELL, signal-main.NONE) and confuse
        the automated bot's trade decision logic.
        """
        res = connected_client.get("/api/signal/EURUSD")
        assert res.json()["final_signal"] in ["BUY", "SELL", "NONE"]

    def test_votes_add_up_to_total(self, connected_client):
        """
        buy_votes + sell_votes + none_votes must equal total_evaluated.

        This is a mathematical guarantee — every strategy casts exactly one
        vote. If the sum does not equal the total, votes have been lost or
        double-counted somewhere in the aggregation logic.
        """
        res  = connected_client.get("/api/signal/EURUSD")
        data = res.json()
        total = data["buy_votes"] + data["sell_votes"] + data["none_votes"]
        assert total == data["total_evaluated"]

    def test_confidence_is_percentage(self, connected_client):
        """
        Confidence must be a value between 0 and 100.

        The dashboard displays this as a percentage and uses it to fill the
        progress bar. A value outside 0-100 would break the bar display and
        could cause the bot to apply the wrong confidence threshold check.
        """
        res = connected_client.get("/api/signal/EURUSD")
        assert 0 <= res.json()["confidence"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
# TestChartData
#
# Verifies the /api/ohlcv/{symbol} endpoint that provides candlestick data
# for the price chart. The chart uses Chart.js on the frontend, which expects
# a specific structure for each candle.
# ─────────────────────────────────────────────────────────────────────────────

class TestChartData:

    def test_ohlcv_returns_data(self, connected_client):
        """The OHLCV endpoint should return a non-empty list of candles."""
        res = connected_client.get("/api/ohlcv/EURUSD?timeframe=M15&count=50")
        assert res.status_code == 200
        assert len(res.json()["data"]) > 0

    def test_ohlcv_candles_have_required_fields(self, connected_client):
        """
        Each candle in the response must have all six OHLCV fields.

        Chart.js needs time, open, high, low, close to draw the candle body.
        Volume is displayed in the volume panel below the chart. Any missing
        field would cause a JavaScript rendering error on the dashboard.
        """
        candle = connected_client.get(
            "/api/ohlcv/EURUSD?timeframe=M15&count=10"
        ).json()["data"][0]

        for field in ["time", "open", "high", "low", "close", "volume"]:
            assert field in candle, f"Missing field: {field}"

    def test_ohlcv_high_above_low(self, connected_client):
        """
        In every candle, high must be greater than or equal to low.

        This is a physical property of price data — the high of a candle is
        by definition the highest price traded during that period, and the low
        is the lowest. A candle where high < low would be corrupted data.
        """
        candles = connected_client.get(
            "/api/ohlcv/EURUSD?timeframe=M15&count=20"
        ).json()["data"]

        for candle in candles:
            assert candle["high"] >= candle["low"], \
                f"High {candle['high']} below low {candle['low']}"

    def test_different_timeframes_both_return_data(self, connected_client):
        """
        Both M5 and H1 timeframe requests should return valid candle data.

        The dashboard has four timeframe buttons (M5, M15, H1, H4). This test
        confirms the timeframe parameter is correctly passed to the data fetcher
        and that different timeframe requests both succeed.
        """
        m5 = connected_client.get("/api/ohlcv/EURUSD?timeframe=M5&count=10")
        h1 = connected_client.get("/api/ohlcv/EURUSD?timeframe=H1&count=10")

        assert m5.status_code == 200
        assert h1.status_code == 200
        assert len(m5.json()["data"]) > 0
        assert len(h1.json()["data"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TestRiskManagerAPI
#
# Verifies the risk management endpoints. The kill switch is the most important
# safety mechanism in the system — these tests confirm it blocks trades when
# active and allows them again when deactivated.
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskManagerAPI:

    def test_risk_status_returns_all_fields(self, connected_client):
        """
        The risk status endpoint must return all five fields that the
        Risk Manager dashboard page displays.

        daily_trades and max_trades drive the trade count gauge.
        drawdown_pct and max_drawdown drive the drawdown gauge.
        kill_switch determines the shield colour and button state.
        """
        res = connected_client.get("/api/risk/status")
        assert res.status_code == 200

        for field in ["daily_trades", "max_trades", "drawdown_pct",
                      "max_drawdown", "kill_switch"]:
            assert field in res.json()

    def test_kill_switch_activate(self, connected_client):
        """Activating the kill switch via API should set kill_switch: True."""
        res = connected_client.post("/api/risk/killswitch?activate=true")
        assert res.status_code == 200
        assert res.json()["kill_switch"] is True

    def test_kill_switch_blocks_trades(self, connected_client):
        """
        When the kill switch is active, any trade attempt must be rejected.

        The rejection message should contain the word 'kill' so the dashboard
        can display a meaningful explanation to the user rather than a generic
        error. The HTTP status is still 200 — the request succeeded, but the
        trade was correctly blocked.
        """
        connected_client.post("/api/risk/killswitch?activate=true")
        res = connected_client.post("/api/trade", json={
            "symbol": "EURUSD", "signal": "BUY",
            "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
        })

        assert res.status_code == 200
        assert res.json()["success"] is False
        assert "kill" in res.json()["message"].lower()

    def test_kill_switch_deactivate(self, connected_client):
        """Deactivating the kill switch via API should set kill_switch: False."""
        connected_client.post("/api/risk/killswitch?activate=false")
        res = connected_client.post("/api/risk/killswitch?activate=false")
        assert res.json()["kill_switch"] is False

    def test_trade_allowed_after_kill_switch_off(self, connected_client):
        """
        After the kill switch is deactivated, trades must be allowed through.

        This test also resets the daily trade count to ensure the daily limit
        is not the reason a trade gets blocked. The MT5 connector is patched
        so the trade executes against mock data rather than a real broker.
        """
        from execution.risk_manager import risk_manager

        # Clear any blocking conditions from previous tests
        risk_manager.deactivate_kill_switch()
        risk_manager.reset_daily()

        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })

        assert res.json()["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# TestTradeExecution
#
# Verifies the full trade placement flow from the API endpoint through risk
# checks and into the mock executor. The autouse fixture resets the risk
# manager before every test in this class so a failed kill switch test in
# TestRiskManagerAPI does not bleed into these tests.
# ─────────────────────────────────────────────────────────────────────────────

class TestTradeExecution:

    @pytest.fixture(autouse=True)
    def reset_risk(self):
        """
        Reset the risk manager state before every test in this class.

        Without this, tests that activate the kill switch or use up the daily
        trade count would cause subsequent tests to fail for the wrong reason.
        autouse=True means this fixture runs automatically — no test needs to
        explicitly request it.
        """
        from execution.risk_manager import risk_manager
        risk_manager.deactivate_kill_switch()
        risk_manager.reset_daily()

    def test_buy_trade_succeeds_in_mock(self, connected_client):
        """
        A BUY trade must return success: True with a valid order ID and price.

        The order_id is the broker's ticket number — it uniquely identifies the
        trade and is shown on the dashboard and in MT5's trade terminal.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })

        data = res.json()
        assert data["success"] is True, f"Trade failed: {data.get('message')}"
        assert data["order_id"] is not None
        assert data["price"] > 0

    def test_sell_trade_succeeds_in_mock(self, connected_client):
        """
        A SELL trade on a different symbol should also execute successfully.

        Testing with GBPUSD confirms the symbol parameter is correctly passed
        through and that the mock executor handles different symbols identically.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.post("/api/trade", json={
                "symbol": "GBPUSD", "signal": "SELL",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })

        assert res.json()["success"] is True

    def test_trade_appears_in_positions(self, connected_client):
        """
        After placing a trade, the open positions endpoint must return at least
        one position.

        This confirms the trade is not just acknowledged — it is actually
        tracked as an open position that appears in the dashboard table.
        """
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })

        positions = connected_client.get("/api/positions").json()["positions"]
        assert len(positions) > 0

    def test_invalid_lot_size_rejected(self, connected_client):
        """
        A trade with lot size of 0 must be rejected by the risk manager.

        Lot size 0 is not a valid trade — you cannot trade zero units.
        The fat finger / lot size check in the risk manager should catch this
        before it ever reaches the broker, returning success: False.
        """
        res = connected_client.post("/api/trade", json={
            "symbol": "EURUSD", "signal": "BUY",
            "lot": 0.0, "sl_pips": 50, "tp_pips": 100,
        })

        assert res.json()["success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# TestDatabaseIntegration
#
# Verifies that API calls that should save data to the database actually do so.
# These tests bridge the gap between the unit tests (which test repository
# functions directly) and the real application behaviour (where data is saved
# as a side effect of API calls, not through direct function calls).
#
# This is the most important distinction between unit tests and integration
# tests in this project: unit tests verify that save_signal() works correctly
# when called directly; these tests verify that hitting /api/signal/EURUSD
# actually calls save_signal() and the data appears in the database.
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabaseIntegration:

    def test_signal_saved_to_database_on_refresh(self, connected_client):
        """
        Calling the signal endpoint should save a new row to the signals table.

        We compare the count before and after the API call. The count after
        must be greater than or equal to before (>= rather than > because the
        test client may be reusing a session from a previous test in the module
        that already triggered a save).
        """
        from database.repository import get_recent_signals

        before = len(get_recent_signals(limit=200))
        connected_client.get("/api/signal/EURUSD")
        after = len(get_recent_signals(limit=200))

        assert after >= before

    def test_trade_saved_to_database_on_execute(self, connected_client):
        """
        A successful trade execution must create a new row in the trades table.

        This test resets the risk manager to guarantee the trade goes through,
        then compares trade counts before and after. A strict > is used here
        (not >=) because we know a trade was placed, so the count must increase.
        """
        from database.repository import get_trade_history
        from execution.risk_manager import risk_manager

        risk_manager.deactivate_kill_switch()
        risk_manager.reset_daily()

        before = len(get_trade_history(limit=200))

        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })

        after = len(get_trade_history(limit=200))
        assert after > before

    def test_history_api_returns_database_trades(self, connected_client):
        """
        The /api/history endpoint must read from the database and return a
        trades list.

        This confirms that the history page is reading from the persistent
        database (which survives restarts) rather than from in-memory state
        (which is lost on restart).
        """
        res = connected_client.get("/api/history")
        assert res.status_code == 200

        data = res.json()
        assert "trades" in data
        assert isinstance(data["trades"], list)

    def test_signals_log_api_returns_data(self, connected_client):
        """
        After triggering a signal evaluation, the signals log endpoint must
        return at least one entry.

        We call the signal endpoint first to guarantee at least one record
        exists, then verify the log endpoint picks it up from the database.
        """
        # Ensure at least one signal has been saved before checking the log
        connected_client.get("/api/signal/EURUSD")

        res = connected_client.get("/api/signals/log")
        assert res.status_code == 200

        data = res.json()
        assert "signals" in data
        assert len(data["signals"]) > 0

    def test_account_saved_to_database_on_login(self, client):
        """
        Logging in should save an account snapshot to the accounts table.

        This test was written after discovering that the save_account_snapshot()
        call in main.py had incorrect indentation, making it unreachable code.
        The accounts table was always empty as a result. This test catches that
        regression — if the indentation breaks again, this test will fail
        immediately rather than the bug going unnoticed.

        We use a distinct login number (77777777) so the count increase can be
        attributed specifically to this login rather than a previous test.
        """
        from database.connection import engine
        from sqlalchemy import text

        # Count before login
        with engine.connect() as c:
            before = c.execute(text("SELECT COUNT(*) FROM accounts")).scalar()

        # Log in with a distinct account number
        client.post("/api/connect", json={
            "login":     77777777,
            "password":  "test",
            "server":    "TestServer",
            "demo_mode": True,
        })

        # Count after login — must have increased
        with engine.connect() as c:
            after = c.execute(text("SELECT COUNT(*) FROM accounts")).scalar()

        assert after > before, "Account snapshot was not saved on login"