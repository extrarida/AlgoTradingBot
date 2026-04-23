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


# ── Main DataFetcher class ────────────────────────────────────────────────────
# This is the single access point for all price data in the bot.
# Strategies never call MT5 directly — they always use this class.
# Think of it as a librarian: strategies ask for data, and this
# class decides whether to fetch fresh data or return a stored copy.
class DataFetcher:

    def __init__(self) -> None:
        # This dictionary stores recently fetched data in memory.
        # Key = symbol + timeframe (e.g. "EURUSD_M15")
        # Value = the candle data DataFrame
        # If the same data is requested again, it is returned from here
        # instead of making another call to MT5.
        self._cache: Dict[str, pd.DataFrame] = {}

    # ── OHLCV candle data ─────────────────────────────────────────────────────
    # OHLCV stands for Open, High, Low, Close, Volume.
    # These are the four prices that make up each candle on a chart,
    # plus the volume of trades during that candle.

    def get_ohlcv(
        self,
        symbol:    str,
        timeframe: str = "M15",   # Default is 15-minute candles
        count:     int = 500,     # Default is last 500 candles
        use_cache: bool = False,  # Whether to use stored data or fetch fresh
    ) -> pd.DataFrame:
        """
        Fetches historical candle data for a trading symbol.
        Example: get_ohlcv('EURUSD', 'M15', 500)
        Returns the last 500 fifteen-minute candles for EURUSD
        as a table with columns: open, high, low, close, tick_volume.
        Each row = one candle on the chart.
        """
        # Step 1 — Create a unique label for this request
        # e.g. "EURUSD_M15" so we can check if it is already cached
        cache_key = f"{symbol}_{timeframe}"

        # Step 2 — If caching is enabled and we already have this data,
        # return the stored copy immediately without calling MT5 again.
        # This saves time and avoids hitting API rate limits.
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Step 3 — Convert the timeframe text (e.g. "M15") into the
        # number that MT5 understands (e.g. 15).
        # TIMEFRAME_MAP contains all the conversions.
        tf = TIMEFRAME_MAP.get(timeframe.upper(), 15)

        # Step 4 — Ask MT5 (or Alpha Vantage / mock) for the candle data.
        # The connector decides which price source to use automatically.
        df = connector.get_rates(symbol, tf, count)

        # Step 5 — If nothing came back, log a warning and return empty.
        # This can happen if MT5 is not connected or the symbol is wrong.
        if df.empty:
            logger.warning("Empty OHLCV: %s / %s", symbol, timeframe)
            return df

        # Step 6 — If caching is on, save this data for next time.
        # Next call with the same symbol/timeframe will return this copy.
        if use_cache:
            self._cache[cache_key] = df.copy()

        return df

    # ── Live tick price ───────────────────────────────────────────────────────
    # A "tick" is the current live price — the bid and ask right now.
    # Bid = price you can sell at. Ask = price you can buy at.
    # This is different from candle data — it is the real-time price
    # updating every second (or faster) from the broker.

    def get_tick(self, symbol: str) -> dict:
        """
        Returns the current live bid and ask price for a symbol.
        Example: get_tick('EURUSD') → {'bid': 1.08432, 'ask': 1.08445}
        Passes straight through to mt5_connector, which handles
        the MT5 → Alpha Vantage → Mock priority automatically.
        """
        # Simply pass the request to the connector.
        # The connector handles which source to use (MT5/API/mock).
        return connector.get_tick(symbol)

    # ── Multiple symbols at once ──────────────────────────────────────────────
    # Instead of calling get_ohlcv() one symbol at a time,
    # this function fetches data for several symbols in one go.
    # Useful when the bot monitors multiple currency pairs simultaneously.

    def get_multi_symbol(
        self,
        symbols:   List[str],     # List of symbols e.g. ['EURUSD', 'GBPUSD']
        timeframe: str = "M15",   # Same timeframe for all symbols
        count:     int = 200,     # Number of candles per symbol
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetches candle data for multiple symbols in one call.
        Example: get_multi_symbol(['EURUSD', 'GBPUSD', 'USDJPY'])
        Returns a dictionary...:
            'EURUSD' → DataFrame of EURUSD candles
            'GBPUSD' → DataFrame of GBPUSD candles
        If a symbol fails, it is skipped and the error is logged.
        The other symbols still return normally.
        """
        result: Dict[str, pd.DataFrame] = {}

        # Loop through each symbol and fetch its data individually
        for sym in symbols:
            try:
                df = self.get_ohlcv(sym, timeframe, count)
                # Only include this symbol if data actually came back
                if not df.empty:
                    result[sym] = df
            except Exception as exc:
                # If one symbol fails, log it and continue with the rest
                logger.error("Failed to fetch %s: %s", sym, exc)

        return result

    # ── Cache management ──────────────────────────────────────────────────────
    # These functions control the stored data in memory.
    # The cache speeds things up but sometimes you want fresh data —
    # these functions let you clear the cache when needed.

    def invalidate_cache(self, symbol: Optional[str] = None) -> None:
        """
        Clears stored data so the next request fetches fresh data.
        Two ways to use this:
          invalidate_cache('EURUSD') — clears only EURUSD data
          invalidate_cache()         — clears everything in the cache
        """
        if symbol:
            # Remove only the entries related to this specific symbol
            # e.g. clears 'EURUSD_M15', 'EURUSD_H1' but keeps 'GBPUSD_M15'
            self._cache = {k: v for k, v in self._cache.items()
                           if not k.startswith(symbol)}
        else:
            # Wipe the entire cache — next call fetches everything fresh
            self._cache.clear()

    def cache_size(self) -> int:
        """
        Returns how many symbol/timeframe datasets are stored right now.
        Useful for checking whether the cache is working correctly.
        Example: cache_size() → 3 means 3 datasets are stored in memory.
        """
        return len(self._cache)


# ── Single shared instance ────────────────────────────────────────────────────
# This creates ONE DataFetcher that the entire bot shares.
# Every strategy and every API endpoint imports this same 'fetcher' object.
# This is important — if each module created its own DataFetcher,
# the cache would not work because each would have its own separate copy....
fetcher = DataFetcher()