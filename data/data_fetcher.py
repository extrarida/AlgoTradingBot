"""
data/data_fetcher.py
────────────────────
This file sits between the strategies and the MT5 connector.
Instead of strategies talking to MT5 directly, they all go through
this file. It also has a caching system so the same data is not
fetched from MT5 twice unnecessarily.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

# Import the timeframe map and the shared MT5 connector instance
from data.mt5_connector import TIMEFRAME_MAP, connector

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    The main data access class for the bot.
    All strategies and dashboard API endpoints use this to get price data.
    Never talks to MT5 directly — always goes through mt5_connector.
    """

    def __init__(self) -> None:
        # In-memory cache to store recently fetched data
        # Avoids fetching the same symbol/timeframe multiple times per cycle
        self._cache: Dict[str, pd.DataFrame] = {}

    # ── OHLCV candle data ─────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        symbol:    str,
        timeframe: str = "M15",
        count:     int = 500,
        use_cache: bool = False,
    ) -> pd.DataFrame:
        """
        Fetches historical candle (OHLCV) data for a symbol.
        e.g. get_ohlcv('EURUSD', 'M15', 500) returns the last
        500 fifteen-minute candles for EURUSD.

        Returns a DataFrame with columns:
            open, high, low, close, tick_volume
        Indexed by UTC datetime.
        """
        # Create a unique key for this symbol + timeframe combination
        cache_key = f"{symbol}_{timeframe}"

        # If caching is on and we already have this data, return it directly
        # without calling MT5 again
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Convert the timeframe string (e.g. "M15") to the MT5 number
        tf = TIMEFRAME_MAP.get(timeframe.upper(), 15)

        # Fetch the actual candle data from MT5 (or mock if not connected)
        df = connector.get_rates(symbol, tf, count)

        # If nothing came back, log a warning and return empty
        if df.empty:
            logger.warning("Empty OHLCV: %s / %s", symbol, timeframe)
            return df

        # Save to cache for next time if caching is enabled
        if use_cache:
            self._cache[cache_key] = df.copy()

        return df

    # ── Live tick price ───────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> dict:
        """
        Returns the latest live bid/ask price for a symbol.
        e.g. get_tick('EURUSD') → {'bid': 1.08432, 'ask': 1.08445}
        Passes through to mt5_connector which handles MT5/API/mock priority.
        """
        return connector.get_tick(symbol)

    # ── Multiple symbols at once ──────────────────────────────────────────────

    def get_multi_symbol(
        self,
        symbols:   List[str],
        timeframe: str = "M15",
        count:     int = 200,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetches candle data for multiple symbols in one call.
        e.g. get_multi_symbol(['EURUSD', 'GBPUSD', 'USDJPY'])
        Returns a dictionary where each key is a symbol name
        and the value is its OHLCV DataFrame.
        Skips any symbol that fails and logs the error.
        """
        result: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = self.get_ohlcv(sym, timeframe, count)
                # Only add to result if data actually came back
                if not df.empty:
                    result[sym] = df
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", sym, exc)
        return result

    # ── Cache management ──────────────────────────────────────────────────────

    def invalidate_cache(self, symbol: Optional[str] = None) -> None:
        """
        Clears cached data so fresh data is fetched next time.
        Pass a symbol name to clear only that symbol's cache,
        or call with no argument to clear everything.
        """
        if symbol:
            # Remove only entries that start with this symbol name
            self._cache = {k: v for k, v in self._cache.items()
                           if not k.startswith(symbol)}
        else:
            # Clear the entire cache
            self._cache.clear()

    def cache_size(self) -> int:
        """Returns how many symbol/timeframe combinations are currently cached."""
        return len(self._cache)


# ── Single shared instance ────────────────────────────────────────────────────
# One shared DataFetcher used by the whole bot.
# All strategies and API endpoints import this 'fetcher' object directly.
fetcher = DataFetcher()