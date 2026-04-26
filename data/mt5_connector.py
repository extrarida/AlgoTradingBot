"""
data/mt5_connector.py
─────────────────────
This file is the MT5 bridge for account, order, and live market access.
The fallback pipeline for market data has been moved to data/data_pipeline.py.
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

try:
    import MetaTrader5 as _mt5  # type: ignore
    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not found. MT5 features are disabled.")


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
    "M1":  Timeframe.M1,
    "M5":  Timeframe.M5,
    "M15": Timeframe.M15,
    "M30": Timeframe.M30,
    "H1":  Timeframe.H1,
    "H4":  Timeframe.H4,
    "D1":  Timeframe.D1,
    "W1":  Timeframe.W1,
}

TRADE_ACTION_DEAL  = 1
ORDER_TYPE_BUY     = 0
ORDER_TYPE_SELL    = 1
ORDER_TIME_GTC     = 0
ORDER_FILLING_IOC  = 2
ORDER_FILLING_FOK  = 1
RETCODE_DONE       = 10009


@dataclass
class MT5Session:
    login:        int
    server:       str
    connected:    bool = False
    account_info: Dict = field(default_factory=dict)


class MT5Connector:
    def __init__(self) -> None:
        self._session: Optional[MT5Session] = None
        self._mock_positions: List[dict] = []
        self._mock_order_counter: int = 10000
        self._force_mock: bool = False

    def connect(self, login: int, password: str, server: str) -> bool:
        if not _MT5_AVAILABLE:
            logger.warning("MT5 connect failed because MetaTrader5 package is unavailable.")
            return False

        if not _mt5.initialize():
            logger.warning("MT5 initialize failed: %s", _mt5.last_error())
            return False

        if not _mt5.login(login, password=password, server=server):
            logger.warning("MT5 login failed for account %s: %s", login, _mt5.last_error())
            _mt5.shutdown()
            return False

        info = _mt5.account_info()
        if not info:
            logger.warning("MT5 account_info() returned no data after login.")
            _mt5.shutdown()
            return False

        self._session = MT5Session(
            login=login,
            server=server,
            connected=True,
            account_info=info._asdict(),
        )
        self._force_mock = False
        logger.info(
            "MT5 connected (REAL) — login=%s balance=%.2f equity=%.2f",
            login, info.balance, info.equity,
        )
        return True

    def connect_mock(self, login: int = 0, server: str = "Demo") -> bool:
        self._force_mock = True
        self._session = MT5Session(
            login=login,
            server=server,
            connected=True,
            account_info=self._mock_account(login, server),
        )
        logger.info("[MOCK] Demo mode explicitly selected by user.")
        return True

    def disconnect(self) -> None:
        if not self.mock_mode and self._session and self._session.connected and _MT5_AVAILABLE:
            _mt5.shutdown()
        self._session = None
        self._force_mock = False
        logger.info("MT5 disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._session.connected

    @property
    def mock_mode(self) -> bool:
        return self._force_mock

    def get_rates(self, symbol: str, timeframe: int, count: int = 500) -> pd.DataFrame:
        if self.mock_mode:
            return self._mock_rates(symbol, count)

        if not self.is_connected or not _MT5_AVAILABLE:
            return pd.DataFrame()

        if not _mt5.symbol_select(symbol, True):
            logger.warning("Symbol %s not available in MT5, trying anyway...", symbol)

        rates = _mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning(
                "No rates returned for %s (timeframe=%s): %s",
                symbol, timeframe, _mt5.last_error(),
            )
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        expected = ["open", "high", "low", "close", "tick_volume"]
        if any(col not in df.columns for col in expected):
            missing = [col for col in expected if col not in df.columns]
            logger.error("MT5 missing columns %s for %s", missing, symbol)
            return pd.DataFrame()
        return df[expected]

    def get_tick(self, symbol: str) -> dict:
        if self.mock_mode:
            tick = self._mock_tick(symbol)
            tick["source"] = "mock"
            return tick

        if not self.is_connected or not _MT5_AVAILABLE:
            return {}

        if _mt5.terminal_info() is None:
            logger.warning("MT5 connection lost — terminal_info() returned None.")
            return {}

        _mt5.symbol_select(symbol, True)
        t = _mt5.symbol_info_tick(symbol)
        if t is None:
            return {}

        info = t._asdict()
        spread = round(info.get("ask", 0) - info.get("bid", 0), 5)
        info["spread"] = spread
        info["source"] = "mt5"
        return info

    def get_symbols(self) -> List[str]:
        if self.mock_mode:
            return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "AUDUSD"]

        if not self.is_connected or not _MT5_AVAILABLE:
            return []

        syms = _mt5.symbols_get()
        return [s.name for s in syms] if syms else []

    def get_account_info(self) -> dict:
        if not self._session:
            return {}
        if self.mock_mode:
            return self._session.account_info

        info = _mt5.account_info()
        return info._asdict() if info else {}

    def get_open_positions(self) -> List[dict]:
        if self.mock_mode:
            return self._mock_positions

        positions = _mt5.positions_get()
        return [p._asdict() for p in positions] if positions else []

    def get_orders(self) -> List[dict]:
        if self.mock_mode:
            return []

        orders = _mt5.orders_get()
        return [o._asdict() for o in orders] if orders else []

    def send_order(self, request: dict) -> dict:
        if self.mock_mode:
            return self._mock_send_order(request)

        result = _mt5.order_send(request)
        if result is None:
            return {"retcode": -1, "comment": str(_mt5.last_error())}
        return result._asdict()

    def close_position(self, ticket: int, symbol: str,
                       volume: float, order_type: int) -> dict:
        tick = self.get_tick(symbol)
        price = tick.get("bid" if order_type == ORDER_TYPE_BUY else "ask", 0)
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

    @staticmethod
    def _mock_account(login: int = 0, server: str = "MockBroker") -> dict:
        return {
            "login":        login,
            "name":         "Demo Account",
            "server":       server,
            "currency":     "USD",
            "balance":      10000.0,
            "equity":       10050.0,
            "margin":       200.0,
            "free_margin":  9850.0,
            "margin_level": 5025.0,
            "profit":       50.0,
        }

    @staticmethod
    def _mock_rates(symbol: str, count: int) -> pd.DataFrame:
        rng = np.random.default_rng(abs(hash(symbol)) % (2**31 - 1))
        base = {
            "EURUSD": 1.10,
            "GBPUSD": 1.27,
            "USDJPY": 149.50,
            "XAUUSD": 2350.00,
            "US30": 38500.00,
            "USDCAD": 1.35,
            "AUDUSD": 0.67,
        }.get(symbol, 1.00)
        volatility = max(base * 0.0004, 0.0001)
        closes = base + np.cumsum(rng.normal(0.0, volatility, count))
        closes = np.maximum(closes, base * 0.5)
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        highs = np.maximum(opens, closes) + rng.uniform(volatility * 0.1, volatility * 1.5, count)
        lows = np.minimum(opens, closes) - rng.uniform(volatility * 0.1, volatility * 1.5, count)
        volumes = rng.integers(500, 8000, count).astype(float)
        interval_minutes = 15
        index = pd.date_range(end=datetime.utcnow(), periods=count, freq=f"{interval_minutes}min", tz="UTC")
        return pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "tick_volume": volumes,
            },
            index=index,
        )

    @staticmethod
    def _mock_tick(symbol: str) -> dict:
        base = {
            "EURUSD": 1.10,
            "GBPUSD": 1.27,
            "USDJPY": 149.50,
            "XAUUSD": 2350.00,
            "US30": 38500.00,
            "USDCAD": 1.35,
            "AUDUSD": 0.67,
        }.get(symbol, 1.00)
        movement = random.uniform(-0.0003, 0.0003) * base
        bid = round(base + movement, 5)
        spread = round(max(base * 0.0001, 0.00001), 5)
        ask = round(bid + spread, 5)
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": bid,
            "spread": spread,
            "volume": 100,
            "time": int(datetime.utcnow().timestamp()),
        }

    def _mock_send_order(self, request: dict) -> dict:
        self._mock_order_counter += 1
        order_id = self._mock_order_counter
        deal_id = self._mock_order_counter + 50000
        sym = request.get("symbol", "EURUSD")
        vol = request.get("volume", 0.01)
        price = request.get("price", 1.10)
        if request.get("action") == TRADE_ACTION_DEAL:
            if "position" in request:
                self._mock_positions = [
                    p for p in self._mock_positions
                    if p["ticket"] != request["position"]
                ]
            else:
                self._mock_positions.append({
                    "ticket": order_id,
                    "symbol": sym,
                    "type": request.get("type", 0),
                    "volume": vol,
                    "price_open": price,
                    "price_current": price,
                    "sl": request.get("sl", 0),
                    "tp": request.get("tp", 0),
                    "profit": 0.0,
                    "comment": request.get("comment", ""),
                })
        return {
            "retcode": RETCODE_DONE,
            "order": order_id,
            "deal": deal_id,
            "volume": vol,
            "price": price,
            "comment": "mock_executed",
        }


connector = MT5Connector()
