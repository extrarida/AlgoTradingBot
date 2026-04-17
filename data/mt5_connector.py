"""
data/mt5_connector.py
─────────────────────
Layers 1–3 of the architecture:
  Broker Feed → Market Data Connector → Parser/Decoder

Wraps the MetaTrader5 Python package. If MT5 is not installed (Linux/Mac)
the connector automatically activates MOCK MODE, generating synthetic
OHLCV data and simulating order execution so everything works without
a real broker.

If MT5 is installed (Windows) but not running, the connector also
automatically falls back to MOCK MODE via the _force_mock flag.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Try real MT5 package ──────────────────────────────────────────────────────
try:
    import MetaTrader5 as _mt5
    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None           # type: ignore
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not found – running in MOCK mode.")


# ── MT5 Timeframe constants (mirrored for mock compatibility) ─────────────────
class Timeframe:
    M1  = 1
    M5  = 5
    M15 = 15
    M30 = 30
    H1  = 16385
    H4  = 16388
    D1  = 16408
    W1  = 32769

TIMEFRAME_MAP: Dict[str, int] = {
    "M1":  Timeframe.M1,  "M5":  Timeframe.M5,  "M15": Timeframe.M15,
    "M30": Timeframe.M30, "H1":  Timeframe.H1,  "H4":  Timeframe.H4,
    "D1":  Timeframe.D1,  "W1":  Timeframe.W1,
}

# ── MT5 order constants ───────────────────────────────────────────────────────
TRADE_ACTION_DEAL  = 1
ORDER_TYPE_BUY     = 0
ORDER_TYPE_SELL    = 1
ORDER_TIME_GTC     = 0
ORDER_FILLING_IOC  = 2
RETCODE_DONE       = 10009


@dataclass
class MT5Session:
    login:        int
    server:       str
    connected:    bool = False
    account_info: Dict = field(default_factory=dict)


class MT5Connector:
    """
    Thread-safe MT5 wrapper with full mock fallback.

    mock_mode is True when:
      - MetaTrader5 package is not installed (Mac/Linux)
      - MetaTrader5 package is installed but MT5 app is not running (Windows)

    Public API
    ----------
    connect(login, password, server)               → bool
    disconnect()
    is_connected                                   → bool
    mock_mode                                      → bool
    get_rates(symbol, timeframe, n)                → DataFrame
    get_tick(symbol)                               → dict
    get_symbols()                                  → list[str]
    get_account_info()                             → dict
    get_open_positions()                           → list[dict]
    get_orders()                                   → list[dict]
    send_order(request)                            → dict
    close_position(ticket, symbol, volume, type)   → dict
    """

    def __init__(self) -> None:
        self._session:              Optional[MT5Session] = None
        self._mock_positions:       List[dict]           = []
        self._mock_order_counter:   int                  = 10000
        self._force_mock:           bool                 = False

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, login: int, password: str, server: str) -> bool:
        """
        Connect to MT5 broker.

        Falls back to mock mode automatically if:
          - The MetaTrader5 package is not installed
          - The MT5 application is not running on this machine
        """
        # Case 1: Package not installed (Mac/Linux)
        if not _MT5_AVAILABLE:
            logger.info("[MOCK] MT5 package not found. Using mock mode.")
            self._session = MT5Session(
                login=login, server=server, connected=True,
                account_info=self._mock_account(login, server),
            )
            return True

        # Case 2: Package installed but MT5 app not running (Windows without MT5 open)
        if not _mt5.initialize():
            logger.warning(
                "MT5 initialize() failed: %s — falling back to MOCK mode.",
                _mt5.last_error()
            )
            self._force_mock = True
            self._session = MT5Session(
                login=login, server=server, connected=True,
                account_info=self._mock_account(login, server),
            )
            return True

        # Case 3: MT5 is running — attempt real login
        if not _mt5.login(login, password=password, server=server):
            logger.error("MT5 login failed: %s", _mt5.last_error())
            _mt5.shutdown()
            return False

        info = _mt5.account_info()._asdict()
        self._session = MT5Session(
            login=login, server=server,
            connected=True, account_info=info
        )
        logger.info("MT5 connected – balance=%.2f equity=%.2f",
                    info.get("balance", 0), info.get("equity", 0))
        return True

    def disconnect(self) -> None:
        """Disconnect from MT5 and reset all state."""
        if not self.mock_mode and self._session and self._session.connected:
            _mt5.shutdown()
        self._session    = None
        self._force_mock = False
        logger.info("MT5 disconnected.")

    @property
    def is_connected(self) -> bool:
        """True if a session is active (real or mock)."""
        return self._session is not None and self._session.connected

    @property
    def mock_mode(self) -> bool:
        """
        True if running in mock mode for any reason.
        - Package not installed → always mock
        - Package installed but MT5 not running → _force_mock = True
        """
        return not _MT5_AVAILABLE or self._force_mock

    # ── Market data ───────────────────────────────────────────────────────────

    def get_rates(self, symbol: str, timeframe: int, count: int = 500) -> pd.DataFrame:
        """Return OHLCV DataFrame indexed by UTC datetime."""
        if self.mock_mode:
            return self._mock_rates(symbol, count)

        rates = _mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            logger.warning("No rates for %s: %s", symbol, _mt5.last_error())
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        return df

    def get_tick(self, symbol: str) -> dict:
        """Return latest bid/ask tick."""
        if self.mock_mode:
            return self._mock_tick(symbol)

        t = _mt5.symbol_info_tick(symbol)
        return t._asdict() if t else {}

    def get_symbols(self) -> List[str]:
        """Return list of available trading symbols."""
        if self.mock_mode:
            return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "AUDUSD"]

        syms = _mt5.symbols_get()
        return [s.name for s in syms] if syms else []

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        """Return account balance, equity, margin and other details."""
        if not self._session:
            return {}
        if self.mock_mode:
            return self._session.account_info

        info = _mt5.account_info()
        return info._asdict() if info else {}

    def get_open_positions(self) -> List[dict]:
        """Return all currently open positions."""
        if self.mock_mode:
            return self._mock_positions

        positions = _mt5.positions_get()
        return [p._asdict() for p in positions] if positions else []

    def get_orders(self) -> List[dict]:
        """Return all pending orders."""
        if self.mock_mode:
            return []

        orders = _mt5.orders_get()
        return [o._asdict() for o in orders] if orders else []

    # ── Execution ─────────────────────────────────────────────────────────────

    def send_order(self, request: dict) -> dict:
        """Send a trade request. Returns result dict."""
        if self.mock_mode:
            return self._mock_send_order(request)

        result = _mt5.order_send(request)
        if result is None:
            return {"retcode": -1, "comment": str(_mt5.last_error())}
        return result._asdict()

    def close_position(self, ticket: int, symbol: str,
                       volume: float, order_type: int) -> dict:
        """Close an open position by ticket number."""
        tick       = self.get_tick(symbol)
        price      = tick.get("bid" if order_type == ORDER_TYPE_BUY else "ask", 0)
        close_type = ORDER_TYPE_SELL if order_type == ORDER_TYPE_BUY else ORDER_TYPE_BUY
        return self.send_order({
            "action":       TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    20,
            "magic":        999999,
            "comment":      "algobot_close",
            "type_time":    ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        })

    # ── Mock helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _mock_account(login: int = 0, server: str = "MockBroker") -> dict:
        """Generate a realistic fake account for mock mode."""
        return {
            "login":        login,
            "name":         "Demo Account",
            "server":       server,
            "currency":     "USD",
            "balance":      10_000.0,
            "equity":       10_050.0,
            "margin":       200.0,
            "free_margin":  9_850.0,
            "margin_level": 5025.0,
            "profit":       50.0,
        }

    @staticmethod
    def _mock_rates(symbol: str, count: int) -> pd.DataFrame:
        """Generate synthetic OHLCV data using a seeded random walk."""
        rng = np.random.default_rng(abs(hash(symbol + str(datetime.utcnow().hour))) % (2**31))
        base  = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.5,
                 "XAUUSD": 2350.0, "US30": 38500.0}.get(symbol, 1.10)
        noise  = base * 0.0005
        closes = base + np.cumsum(rng.normal(0, noise, count))
        closes = np.maximum(closes, base * 0.5)
        highs  = closes + rng.uniform(noise * 0.5, noise * 2, count)
        lows   = closes - rng.uniform(noise * 0.5, noise * 2, count)
        opens  = np.roll(closes, 1)
        opens[0] = closes[0]
        vols   = rng.integers(500, 8000, count).astype(float)
        idx    = pd.date_range(end=datetime.utcnow(), periods=count, freq="15min")
        return pd.DataFrame(
            {"open": opens, "high": highs, "low": lows,
             "close": closes, "tick_volume": vols},
            index=idx,
        )

    @staticmethod
    def _mock_tick(symbol: str) -> dict:
        import random
        base   = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.5,
                  "XAUUSD": 2350.0, "US30": 38500.0}.get(symbol, 1.10)
        # Small random movement so price changes on every call
        movement = random.uniform(-0.0003, 0.0003) * base
        bid      = round(base + movement, 5)
        spread   = round(base * 0.0001, 5)
        return {
            "bid":    bid,
            "ask":    round(bid + spread, 5),
            "spread": spread,
            "last":   bid,
            "volume": 100,
            "time":   int(datetime.utcnow().timestamp()),
        }

    def _mock_send_order(self, request: dict) -> dict:
        """Simulate order execution and track mock positions."""
        self._mock_order_counter += 1
        oid   = self._mock_order_counter
        did   = self._mock_order_counter + 50000
        sym   = request.get("symbol", "EURUSD")
        vol   = request.get("volume", 0.01)
        price = request.get("price", 1.1)

        if request.get("action") == TRADE_ACTION_DEAL:
            pos = {
                "ticket":        oid,
                "symbol":        sym,
                "type":          request.get("type", 0),
                "volume":        vol,
                "price_open":    price,
                "price_current": price,
                "sl":            request.get("sl", 0),
                "tp":            request.get("tp", 0),
                "profit":        0.0,
                "comment":       request.get("comment", ""),
            }
            # If closing an existing position, remove it
            if "position" in request:
                self._mock_positions = [
                    p for p in self._mock_positions
                    if p["ticket"] != request["position"]
                ]
            else:
                self._mock_positions.append(pos)

        return {
            "retcode": RETCODE_DONE,
            "order":   oid,
            "deal":    did,
            "volume":  vol,
            "price":   price,
            "comment": "mock_executed",
        }


# ── Module-level singleton ────────────────────────────────────────────────────
connector = MT5Connector()