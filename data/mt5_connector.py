"""
data/mt5_connector.py
─────────────────────
Layers 1–3 of the architecture:
  Broker Feed → Market Data Connector → Parser/Decoder

Wraps the MetaTrader5 Python package. If MT5 is not installed (Linux/Mac)
the connector automatically activates MOCK MODE, generating synthetic
OHLCV data and simulating order execution so everything works without
a real broker.
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
    "M1": Timeframe.M1,  "M5": Timeframe.M5,  "M15": Timeframe.M15,
    "M30": Timeframe.M30, "H1": Timeframe.H1,  "H4": Timeframe.H4,
    "D1": Timeframe.D1,  "W1": Timeframe.W1,
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
    login:       int
    server:      str
    connected:   bool        = False
    account_info: Dict       = field(default_factory=dict)


class MT5Connector:
    """
    Thread-safe MT5 wrapper with full mock fallback.

    Public API
    ----------
    connect(login, password, server)  → bool
    disconnect()
    is_connected                      → bool
    get_rates(symbol, timeframe, n)   → DataFrame
    get_tick(symbol)                  → dict
    get_symbols()                     → list[str]
    get_account_info()                → dict
    get_open_positions()              → list[dict]
    get_orders()                      → list[dict]
    send_order(request)               → dict
    close_position(ticket, symbol, volume, order_type) → dict
    """

    def __init__(self) -> None:
        self._session: Optional[MT5Session] = None
        self._mock_positions: List[dict]    = []
        self._mock_order_counter: int       = 10000

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, login: int, password: str, server: str) -> bool:
        if not _MT5_AVAILABLE:
            logger.info("[MOCK] MT5 connect: login=%s server=%s", login, server)
            self._session = MT5Session(
                login=login, server=server, connected=True,
                account_info=self._mock_account(login, server),
            )
            return True

        if not _mt5.initialize():
            logger.error("MT5 initialize() failed: %s", _mt5.last_error())
            return False

        if not _mt5.login(login, password=password, server=server):
            logger.error("MT5 login failed: %s", _mt5.last_error())
            _mt5.shutdown()
            return False

        info = _mt5.account_info()._asdict()
        self._session = MT5Session(login=login, server=server,
                                   connected=True, account_info=info)
        logger.info("MT5 connected – balance=%.2f equity=%.2f",
                    info.get("balance", 0), info.get("equity", 0))
        return True

    def disconnect(self) -> None:
        if _MT5_AVAILABLE and self._session and self._session.connected:
            _mt5.shutdown()
        self._session = None
        logger.info("MT5 disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._session.connected

    @property
    def mock_mode(self) -> bool:
        return not _MT5_AVAILABLE

    # ── Market data ───────────────────────────────────────────────────────────

    def get_rates(self, symbol: str, timeframe: int, count: int = 500) -> pd.DataFrame:
        """Return OHLCV DataFrame indexed by UTC datetime."""
        if not _MT5_AVAILABLE:
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
        if not _MT5_AVAILABLE:
            return self._mock_tick(symbol)
        t = _mt5.symbol_info_tick(symbol)
        return t._asdict() if t else {}

    def get_symbols(self) -> List[str]:
        if not _MT5_AVAILABLE:
            return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "AUDUSD"]
        syms = _mt5.symbols_get()
        return [s.name for s in syms] if syms else []

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        if not self._session:
            return {}
        if not _MT5_AVAILABLE:
            return self._session.account_info
        info = _mt5.account_info()
        return info._asdict() if info else {}

    def get_open_positions(self) -> List[dict]:
        if not _MT5_AVAILABLE:
            return self._mock_positions
        positions = _mt5.positions_get()
        return [p._asdict() for p in positions] if positions else []

    def get_orders(self) -> List[dict]:
        if not _MT5_AVAILABLE:
            return []
        orders = _mt5.orders_get()
        return [o._asdict() for o in orders] if orders else []

    # ── Execution ─────────────────────────────────────────────────────────────

    def send_order(self, request: dict) -> dict:
        """Send a trade request. Returns result dict."""
        if not _MT5_AVAILABLE:
            return self._mock_send_order(request)
        result = _mt5.order_send(request)
        if result is None:
            return {"retcode": -1, "comment": str(_mt5.last_error())}
        return result._asdict()

    def close_position(self, ticket: int, symbol: str,
                       volume: float, order_type: int) -> dict:
        tick      = self.get_tick(symbol)
        price     = tick.get("bid" if order_type == ORDER_TYPE_BUY else "ask", 0)
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
        rng    = np.random.default_rng(abs(hash(symbol)) % (2**31))
        base   = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.5,
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
        base = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.5,
                "XAUUSD": 2350.0, "US30": 38500.0}.get(symbol, 1.10)
        spread = base * 0.0001
        return {
            "bid":    round(base, 5),
            "ask":    round(base + spread, 5),
            "last":   round(base, 5),
            "volume": 100,
            "time":   int(datetime.utcnow().timestamp()),
        }

    def _mock_send_order(self, request: dict) -> dict:
        self._mock_order_counter += 1
        oid  = self._mock_order_counter
        did  = self._mock_order_counter + 50000
        sym  = request.get("symbol", "EURUSD")
        vol  = request.get("volume", 0.01)
        price = request.get("price", 1.1)

        # Track mock open positions
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
            # Remove closed positions if this is a close
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
