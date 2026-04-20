"""
data/mt5_connector.py
─────────────────────
This file is the BRIDGE between your bot and the MT5 trading platform.
It handles 3 things:
  1. Connecting to MT5 and logging in with your broker credentials
  2. Fetching live prices and chart data from the broker
  3. Sending buy/sell orders to the broker

If MT5 is not installed or not running, it automatically uses fake
(mock) prices so the bot can still run for testing purposes.
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

# ── Alpha Vantage Web API (backup price source) ───────────────────────────────
# This is an external web API that fetches forex prices from the internet.
# It is used as a backup when MT5 is not running.
# To activate it, add ALPHA_VANTAGE_API_KEY=your_key to your .env file.
# Get a free key at: https://www.alphavantage.co/support/#api-key
import requests
import os

# Read the API key from the .env file. Empty string if not set.
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

def get_price_from_alphavantage(symbol: str) -> dict:
    """
    Calls the Alpha Vantage web API to get the latest forex price.
    For example: symbol='EURUSD' → fetches EUR to USD exchange rate.
    Returns a dict with bid, ask, and price.
    Returns empty dict {} if the call fails or key is not set.
    """
    # If no API key is set in .env, skip this and return nothing
    if not ALPHA_VANTAGE_KEY:
        logger.warning("Alpha Vantage API key not set in .env file.")
        return {}

    # Split the symbol into two currencies e.g. EURUSD → EUR and USD
    if len(symbol) == 6:
        from_currency = symbol[:3]   # First 3 letters e.g. EUR
        to_currency   = symbol[3:]   # Last 3 letters e.g. USD
    else:
        logger.warning("Symbol format not supported by Alpha Vantage: %s", symbol)
        return {}

    try:
        # Build the API request URL with the currency pair and API key
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=CURRENCY_EXCHANGE_RATE"
            f"&from_currency={from_currency}"
            f"&to_currency={to_currency}"
            f"&apikey={ALPHA_VANTAGE_KEY}"
        )
        # Send the request to Alpha Vantage and get the response
        response = requests.get(url, timeout=10)
        data = response.json()

        # Extract the price data from the response
        rate_data = data.get("Realtime Currency Exchange Rate", {})
        if not rate_data:
            logger.warning("Alpha Vantage returned no data for %s", symbol)
            return {}

        # Parse the price, bid, and ask values from the response
        price = float(rate_data.get("5. Exchange Rate", 0))
        bid   = float(rate_data.get("8. Bid Price", price))
        ask   = float(rate_data.get("9. Ask Price", price))

        logger.info(
            "[Alpha Vantage API] %s → bid=%.5f ask=%.5f", symbol, bid, ask
        )

        # Return the price data in a standard format the bot understands
        return {
            "bid":    round(bid,   5),
            "ask":    round(ask,   5),
            "last":   round(price, 5),
            "volume": 0,
            "time":   0,
            "source": "alpha_vantage_api",
        }

    except Exception as e:
        logger.error("Alpha Vantage API error for %s: %s", symbol, e)
        return {}


# ── Try to import the MT5 Python package ─────────────────────────────────────
# This package only works on Windows with MT5 desktop app installed.
# If it is not found (e.g. on Mac/Linux), the bot switches to mock mode.
try:
    import MetaTrader5 as _mt5  # type: ignore
    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None                 # type: ignore
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not found – running in MOCK mode.")


# ── MT5 Timeframe constants ───────────────────────────────────────────────────
# These numbers represent different chart timeframes in MT5.
# e.g. M15 = 15-minute candles, H1 = 1-hour candles, D1 = daily candles.
class Timeframe:
    M1  = 1
    M5  = 5
    M15 = 15
    M30 = 30
    H1  = 16385
    H4  = 16388
    D1  = 16408
    W1  = 32769

# Dictionary to look up timeframe number from a string like "M15" or "H1"
TIMEFRAME_MAP: Dict[str, int] = {
    "M1":  Timeframe.M1,  "M5":  Timeframe.M5,  "M15": Timeframe.M15,
    "M30": Timeframe.M30, "H1":  Timeframe.H1,  "H4":  Timeframe.H4,
    "D1":  Timeframe.D1,  "W1":  Timeframe.W1,
}

# ── MT5 Order type constants ──────────────────────────────────────────────────
# These numbers are how MT5 identifies different order actions.
# e.g. ORDER_TYPE_BUY = 0 means place a buy order.
TRADE_ACTION_DEAL  = 1   # Execute a trade immediately
ORDER_TYPE_BUY     = 0   # Buy order
ORDER_TYPE_SELL    = 1   # Sell order
ORDER_TIME_GTC     = 0   # Good Till Cancelled
ORDER_FILLING_IOC  = 2   # Fill as much as possible immediately
RETCODE_DONE       = 10009  # MT5 success code meaning trade was executed


# ── Session data storage ──────────────────────────────────────────────────────
# Stores information about the current login session (account number, server etc.)
@dataclass
class MT5Session:
    login:        int
    server:       str
    connected:    bool = False
    account_info: Dict = field(default_factory=dict)


# ── Main MT5 Connector class ──────────────────────────────────────────────────
# This is the main class that the rest of the bot uses to talk to MT5.
# All price fetching and order sending goes through this class.
class MT5Connector:
    """
    Handles everything related to connecting to MT5 and fetching data.

    mock_mode is True when:
      - MetaTrader5 package is not installed (Mac/Linux)
      - MT5 desktop app is installed but not running (Windows)
    """

    def __init__(self) -> None:
        # Stores the current login session details
        self._session:              Optional[MT5Session] = None
        # Stores fake positions when running in mock mode
        self._mock_positions:       List[dict]           = []
        # Counter used to generate fake order/ticket numbers in mock mode
        self._mock_order_counter:   int                  = 10000
        # Flag to force mock mode even when MT5 is available
        self._force_mock:           bool                 = False

    # ── Connection methods ────────────────────────────────────────────────────

    def connect(self, login: int, password: str, server: str) -> bool:
        """
        Tries to connect to MT5 with the provided broker credentials.
        Goes through 4 cases:
          1. MT5 package not installed → uses mock mode
          2. MT5 installed but app not running → returns error
          3. MT5 running but wrong credentials → falls back to mock
          4. MT5 running and credentials correct → uses real live data
        """

        # Case 1: MT5 package not installed (Mac/Linux) — always use mock mode
        if not _MT5_AVAILABLE:
            logger.info("[MOCK] MT5 package not found. Using mock mode.")
            self._session = MT5Session(
                login=login, server=server, connected=True,
                account_info=self._mock_account(login, server),
            )
            self._force_mock = True
            return True

        # Case 2: MT5 package is installed but the MT5 desktop app is not open
        # Tell the user to open MT5 first
        if not _mt5.initialize():
            logger.warning(
                "MT5 initialize() failed: %s — MT5 app is not running.",
                _mt5.last_error()
            )
            return False

        # Case 3: MT5 is open but the login credentials are wrong
        # Fall back to mock mode so the bot can still run
        if not _mt5.login(login, password=password, server=server):
            logger.warning(
                "MT5 login failed for account %s — credentials not recognised. "
                "Falling back to mock mode.",
                login
            )
            _mt5.shutdown()
            self._force_mock = True
            self._session = MT5Session(
                login=login, server=server, connected=True,
                account_info=self._mock_account(login, server),
            )
            return True

        # Case 4: Everything worked — connected to real broker with live data
        info = _mt5.account_info()._asdict()
        self._session = MT5Session(
            login=login, server=server,
            connected=True, account_info=info
        )
        self._force_mock = False
        logger.info(
            "MT5 connected (REAL) — login=%s balance=%.2f equity=%.2f",
            login, info.get("balance", 0), info.get("equity", 0)
        )
        return True

    def connect_mock(self, login: int = 0, server: str = "Demo") -> bool:
        """
        Connects in mock/demo mode on purpose.
        Used when the user clicks Demo Mode on the login page.
        No real money or real prices — just for testing.
        """
        self._force_mock = True
        self._session = MT5Session(
            login=login, server=server, connected=True,
            account_info=self._mock_account(login, server),
        )
        logger.info("[MOCK] Demo mode explicitly selected by user.")
        return True

    def disconnect(self) -> None:
        """
        Disconnects from MT5 and clears all session data.
        Called when the user logs out or the bot stops.
        """
        if not self.mock_mode and self._session and self._session.connected:
            _mt5.shutdown()
        self._session    = None
        self._force_mock = False
        logger.info("MT5 disconnected.")

    @property
    def is_connected(self) -> bool:
        """Returns True if a session is active (real or mock)."""
        return self._session is not None and self._session.connected

    @property
    def mock_mode(self) -> bool:
        """
        Returns True if the bot is running on fake/mock prices.
        This happens when MT5 is not installed or not running.
        """
        return not _MT5_AVAILABLE or self._force_mock

    # ── Price and chart data methods ──────────────────────────────────────────

    def get_rates(self, symbol: str, timeframe: int, count: int = 500) -> pd.DataFrame:
        """
        Fetches historical OHLCV candle data for a symbol.
        e.g. get_rates('EURUSD', Timeframe.M15, 500)
        returns the last 500 15-minute candles for EURUSD.
        Returns fake data if running in mock mode.
        """
        if self.mock_mode:
            return self._mock_rates(symbol, count)

        # Fetch real candle data from MT5
        rates = _mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            logger.warning("No rates for %s: %s", symbol, _mt5.last_error())
            return pd.DataFrame()

        # Convert to a pandas DataFrame with datetime index
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        return df

    def get_tick(self, symbol: str) -> dict:
        """
        Fetches the latest live bid/ask price for a symbol.
        Tries 3 sources in order:
          1. MT5 live data (real-time from broker)
          2. Alpha Vantage web API (internet-based backup)
          3. Mock/fake price (for testing only)
        """
        # Priority 1 — Real MT5 live price from the broker
        if _MT5_AVAILABLE and self.is_connected and not self.mock_mode:
            t = _mt5.symbol_info_tick(symbol)
            return t._asdict() if t else {}

        # Priority 2 — Alpha Vantage web API (if key is set in .env)
        av_data = get_price_from_alphavantage(symbol)
        if av_data:
            return av_data

        # Priority 3 — Generate a fake price for testing
        logger.info("[Mock] Using synthetic price for %s", symbol)
        return self._mock_tick(symbol)

    def get_symbols(self) -> List[str]:
        """
        Returns the list of all trading symbols available.
        e.g. ['EURUSD', 'GBPUSD', 'USDJPY', ...]
        Returns a hardcoded list in mock mode.
        """
        if self.mock_mode:
            return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "AUDUSD"]

        syms = _mt5.symbols_get()
        return [s.name for s in syms] if syms else []

    # ── Account information methods ───────────────────────────────────────────

    def get_account_info(self) -> dict:
        """
        Returns your account details: balance, equity, margin etc.
        Shows fake account data in mock mode.
        """
        if not self._session:
            return {}
        if self.mock_mode:
            return self._session.account_info

        info = _mt5.account_info()
        return info._asdict() if info else {}

    def get_open_positions(self) -> List[dict]:
        """
        Returns all currently open trades (positions).
        Returns fake positions in mock mode.
        """
        if self.mock_mode:
            return self._mock_positions

        positions = _mt5.positions_get()
        return [p._asdict() for p in positions] if positions else []

    def get_orders(self) -> List[dict]:
        """
        Returns all pending orders waiting to be executed.
        Always empty in mock mode (no pending orders simulated).
        """
        if self.mock_mode:
            return []

        orders = _mt5.orders_get()
        return [o._asdict() for o in orders] if orders else []

    # ── Order execution methods ───────────────────────────────────────────────

    def send_order(self, request: dict) -> dict:
        """
        Sends a buy or sell order to the broker.
        In mock mode, simulates the order execution without real money.
        Returns the result including a ticket number and status code.
        """
        if self.mock_mode:
            return self._mock_send_order(request)

        result = _mt5.order_send(request)
        if result is None:
            return {"retcode": -1, "comment": str(_mt5.last_error())}
        return result._asdict()

    def close_position(self, ticket: int, symbol: str,
                       volume: float, order_type: int) -> dict:
        """
        Closes an open trade by its ticket number.
        Gets the current price and sends the opposite order to close.
        e.g. if the open trade was a BUY, it sends a SELL to close it.
        """
        # Get current price to close at
        tick       = self.get_tick(symbol)
        price      = tick.get("bid" if order_type == ORDER_TYPE_BUY else "ask", 0)
        # Opposite order type to close: BUY → SELL, SELL → BUY
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

    # ── Mock/fake data helpers ────────────────────────────────────────────────
    # These methods generate fake data when MT5 is not connected.
    # They are only used for testing — no real money involved.

    @staticmethod
    def _mock_account(login: int = 0, server: str = "MockBroker") -> dict:
        """
        Generates a fake account with $10,000 balance for testing.
        This is what you see on the dashboard when in mock mode.
        """
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
        """
        Generates fake OHLCV candle data using a random walk formula.
        Prices start from a realistic base value and move randomly.
        Used by the strategies for backtesting when MT5 is not connected.
        """
        rng = np.random.default_rng(abs(hash(symbol + str(datetime.utcnow().hour))) % (2**31))
        # Realistic starting prices for common symbols
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
        """
        Generates a fake live price that changes slightly on every call.
        Used by the dashboard to simulate price movement in mock mode.
        """
        base   = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.5,
                  "XAUUSD": 2350.0, "US30": 38500.0}.get(symbol, 1.10)
        # Add a tiny random movement to simulate price changing
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
        """
        Simulates placing a trade without real money.
        Tracks fake open positions so the dashboard can display them.
        When a position is closed, removes it from the fake positions list.
        """
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
            # If this is a close order, remove the matching open position
            if "position" in request:
                self._mock_positions = [
                    p for p in self._mock_positions
                    if p["ticket"] != request["position"]
                ]
            else:
                # Otherwise add as a new open position
                self._mock_positions.append(pos)

        # Return a fake success result
        return {
            "retcode": RETCODE_DONE,
            "order":   oid,
            "deal":    did,
            "volume":  vol,
            "price":   price,
            "comment": "mock_executed",
        }


# ── Single shared instance ────────────────────────────────────────────────────
# This creates one shared connector object that the whole bot uses.
# Instead of creating a new connection every time, everything uses this one.
connector = MT5Connector()