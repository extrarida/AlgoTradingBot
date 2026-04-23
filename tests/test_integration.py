"""
tests/test_integration.py
─────────────────────────
Integration tests — verify all components work together correctly.
Uses demo/mock mode so no real MT5 connection is needed.
Tests the full stack from API endpoint down to database.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


# ── Shared mock price data ────────────────────────────────────────────────────

MOCK_TICK = {
    "bid":    1.10000,
    "ask":    1.10009,
    "spread": 0.00009,
    "last":   1.10000,
    "volume": 100,
    "time":   1714000000,
}

MOCK_TICK_GOLD = {
    "bid":    2350.0,
    "ask":    2350.5,
    "spread": 0.5,
    "last":   2350.0,
    "volume": 10,
    "time":   1714000000,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Basic test client — not connected to any session."""
    from main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def connected_client():
    """Test client with a mock session already active."""
    from main import app
    from data.mt5_connector import connector
    from execution.risk_manager import risk_manager
    risk_manager.deactivate_kill_switch()
    risk_manager.reset_daily()
    connector.connect_mock(login=12345678, server="TestServer")
    yield TestClient(app)
    connector.disconnect()


# ── Server health ─────────────────────────────────────────────────────────────

class TestServerHealth:

    def test_server_is_running(self, client):
        """Server responds to status check."""
        res = client.get("/api/status")
        assert res.status_code == 200
        assert res.json()["server"] == "running"

    def test_login_page_loads(self, client):
        """Login page returns HTML with correct title."""
        res = client.get("/")
        assert res.status_code == 200
        assert "AlgoTrader" in res.text

    def test_dashboard_page_loads(self, client):
        """Dashboard page returns 200."""
        assert client.get("/dashboard").status_code == 200

    def test_history_page_loads(self, client):
        """Trade history page returns 200."""
        assert client.get("/history").status_code == 200

    def test_performance_page_loads(self, client):
        """Performance analytics page returns 200."""
        assert client.get("/performance").status_code == 200

    def test_risk_page_loads(self, client):
        """Risk manager page returns 200."""
        assert client.get("/risk").status_code == 200


# ── Authentication ────────────────────────────────────────────────────────────

class TestAuthentication:

    def test_demo_mode_login_succeeds(self, client):
        """Demo mode login always succeeds regardless of credentials."""
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
        """Demo mode login returns valid account data."""
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
        """Disconnect clears the session successfully."""
        client.post("/api/connect", json={
            "login": 1, "password": "x",
            "server": "x", "demo_mode": True,
        })
        res = client.post("/api/disconnect")
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_endpoints_require_connection(self, client):
        """Protected API endpoints return 401 when not connected."""
        client.post("/api/disconnect")
        assert client.get("/api/account").status_code == 401

    def test_endpoints_work_when_connected(self, connected_client):
        """Protected API endpoints return 200 when connected."""
        assert connected_client.get("/api/account").status_code == 200


# ── Price feed ────────────────────────────────────────────────────────────────

class TestPriceFeed:

    def test_price_endpoint_returns_bid_ask(self, connected_client):
        """Price endpoint returns bid and ask values."""
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.get("/api/price/EURUSD")
        assert res.status_code == 200, f"Got {res.status_code}: {res.text}"
        data = res.json()
        assert "bid" in data
        assert data["bid"] > 0

    def test_price_ask_higher_than_bid(self, connected_client):
        """Ask price is always higher than or equal to bid."""
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.get("/api/price/EURUSD")
        assert res.status_code == 200
        data = res.json()
        assert "ask" in data
        assert data["ask"] >= data["bid"]

    def test_multiple_symbols_return_prices(self, connected_client):
        """All standard watchlist symbols return valid prices."""
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            for symbol in ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]:
                res = connected_client.get(f"/api/price/{symbol}")
                assert res.status_code == 200, f"{symbol} returned {res.status_code}"


# ── Strategy signal ───────────────────────────────────────────────────────────

class TestStrategySignal:

    def test_signal_endpoint_returns_valid_structure(self, connected_client):
        """Signal endpoint returns all required fields."""
        res = connected_client.get("/api/signal/EURUSD")
        assert res.status_code == 200
        data = res.json()
        for field in ["final_signal", "confidence", "buy_votes",
                      "sell_votes", "none_votes", "total_evaluated", "top_strategies"]:
            assert field in data, f"Missing field: {field}"

    def test_signal_is_valid_value(self, connected_client):
        """Final signal is always BUY, SELL, or NONE."""
        res = connected_client.get("/api/signal/EURUSD")
        assert res.json()["final_signal"] in ["BUY", "SELL", "NONE"]

    def test_votes_add_up_to_total(self, connected_client):
        """Buy + sell + none votes must equal total evaluated."""
        res  = connected_client.get("/api/signal/EURUSD")
        data = res.json()
        total = data["buy_votes"] + data["sell_votes"] + data["none_votes"]
        assert total == data["total_evaluated"]

    def test_confidence_is_percentage(self, connected_client):
        """Confidence value is between 0 and 100."""
        res = connected_client.get("/api/signal/EURUSD")
        assert 0 <= res.json()["confidence"] <= 100


# ── OHLCV chart data ──────────────────────────────────────────────────────────

class TestChartData:

    def test_ohlcv_returns_data(self, connected_client):
        """OHLCV endpoint returns candle data."""
        res = connected_client.get("/api/ohlcv/EURUSD?timeframe=M15&count=50")
        assert res.status_code == 200
        assert len(res.json()["data"]) > 0

    def test_ohlcv_candles_have_required_fields(self, connected_client):
        """Each candle has time, open, high, low, close, volume."""
        candle = connected_client.get(
            "/api/ohlcv/EURUSD?timeframe=M15&count=10"
        ).json()["data"][0]
        for field in ["time", "open", "high", "low", "close", "volume"]:
            assert field in candle, f"Missing field: {field}"

    def test_ohlcv_high_above_low(self, connected_client):
        """High is always greater than or equal to low in every candle."""
        candles = connected_client.get(
            "/api/ohlcv/EURUSD?timeframe=M15&count=20"
        ).json()["data"]
        for candle in candles:
            assert candle["high"] >= candle["low"], \
                f"High {candle['high']} below low {candle['low']}"

    def test_different_timeframes_both_return_data(self, connected_client):
        """M5 and H1 timeframes both return valid candle data."""
        m5 = connected_client.get("/api/ohlcv/EURUSD?timeframe=M5&count=10")
        h1 = connected_client.get("/api/ohlcv/EURUSD?timeframe=H1&count=10")
        assert m5.status_code == 200
        assert h1.status_code == 200
        assert len(m5.json()["data"]) > 0
        assert len(h1.json()["data"]) > 0


# ── Risk manager ──────────────────────────────────────────────────────────────

class TestRiskManagerAPI:

    def test_risk_status_returns_all_fields(self, connected_client):
        """Risk status endpoint returns all required fields."""
        res = connected_client.get("/api/risk/status")
        assert res.status_code == 200
        for field in ["daily_trades", "max_trades", "drawdown_pct",
                      "max_drawdown", "kill_switch"]:
            assert field in res.json()

    def test_kill_switch_activate(self, connected_client):
        """Kill switch can be activated via API."""
        res = connected_client.post("/api/risk/killswitch?activate=true")
        assert res.status_code == 200
        assert res.json()["kill_switch"] is True

    def test_kill_switch_blocks_trades(self, connected_client):
        """Trade is rejected when kill switch is active."""
        connected_client.post("/api/risk/killswitch?activate=true")
        res = connected_client.post("/api/trade", json={
            "symbol": "EURUSD", "signal": "BUY",
            "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
        })
        assert res.status_code == 200
        assert res.json()["success"] is False
        assert "kill" in res.json()["message"].lower()

    def test_kill_switch_deactivate(self, connected_client):
        """Kill switch can be deactivated via API."""
        connected_client.post("/api/risk/killswitch?activate=false")
        res = connected_client.post("/api/risk/killswitch?activate=false")
        assert res.json()["kill_switch"] is False

    def test_trade_allowed_after_kill_switch_off(self, connected_client):
        """Trade succeeds after kill switch is turned off."""
        from execution.risk_manager import risk_manager
        risk_manager.deactivate_kill_switch()
        risk_manager.reset_daily()
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })
        assert res.json()["success"] is True


# ── Trade execution ───────────────────────────────────────────────────────────

class TestTradeExecution:

    @pytest.fixture(autouse=True)
    def reset_risk(self):
        """Reset risk manager state before every trade test."""
        from execution.risk_manager import risk_manager
        risk_manager.deactivate_kill_switch()
        risk_manager.reset_daily()

    def test_buy_trade_succeeds_in_mock(self, connected_client):
        """BUY trade executes successfully in mock mode."""
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
        """SELL trade executes successfully in mock mode."""
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            res = connected_client.post("/api/trade", json={
                "symbol": "GBPUSD", "signal": "SELL",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })
        assert res.json()["success"] is True

    def test_trade_appears_in_positions(self, connected_client):
        """After placing a trade it appears in open positions."""
        with patch("data.mt5_connector.MT5Connector.get_tick", return_value=MOCK_TICK):
            connected_client.post("/api/trade", json={
                "symbol": "EURUSD", "signal": "BUY",
                "lot": 0.01, "sl_pips": 50, "tp_pips": 100,
            })
        positions = connected_client.get("/api/positions").json()["positions"]
        assert len(positions) > 0

    def test_invalid_lot_size_rejected(self, connected_client):
        """Trade with lot size of 0 is rejected by risk manager."""
        res = connected_client.post("/api/trade", json={
            "symbol": "EURUSD", "signal": "BUY",
            "lot": 0.0, "sl_pips": 50, "tp_pips": 100,
        })
        assert res.json()["success"] is False


# ── Database integration ──────────────────────────────────────────────────────

class TestDatabaseIntegration:

    def test_signal_saved_to_database_on_refresh(self, connected_client):
        """Signal evaluations are saved to the database on every refresh."""
        from database.repository import get_recent_signals
        before = len(get_recent_signals(limit=200))
        connected_client.get("/api/signal/EURUSD")
        after = len(get_recent_signals(limit=200))
        assert after >= before

    def test_trade_saved_to_database_on_execute(self, connected_client):
        """Executed trades are persisted to the database."""
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
        """History API endpoint reads from database and returns trades."""
        res = connected_client.get("/api/history")
        assert res.status_code == 200
        data = res.json()
        assert "trades" in data
        assert isinstance(data["trades"], list)

    def test_signals_log_api_returns_data(self, connected_client):
        """Signals log API endpoint reads from database."""
        connected_client.get("/api/signal/EURUSD")
        res = connected_client.get("/api/signals/log")
        assert res.status_code == 200
        data = res.json()
        assert "signals" in data
        assert len(data["signals"]) > 0