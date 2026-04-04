"""
data/data_fetcher.py
────────────────────
Layer 6 – Real-Time Market Cache

High-level data access layer with optional in-memory caching.
All strategies and API endpoints use this module, never the
mt5_connector directly.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from data.mt5_connector import TIMEFRAME_MAP, connector

logger = logging.getLogger(__name__)


class DataFetcher:
    """Provides clean OHLCV DataFrames and tick data with caching."""

    def __init__(self) -> None:
        self._cache: Dict[str, pd.DataFrame] = {}

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        symbol:    str,
        timeframe: str = "M15",
        count:     int = 500,
        use_cache: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV bars for a symbol.

        Returns a DataFrame with columns:
            open, high, low, close, tick_volume
        Indexed by UTC DatetimeIndex.
        """
        cache_key = f"{symbol}_{timeframe}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        tf = TIMEFRAME_MAP.get(timeframe.upper(), 15)
        df = connector.get_rates(symbol, tf, count)

        if df.empty:
            logger.warning("Empty OHLCV: %s / %s", symbol, timeframe)
            return df

        if use_cache:
            self._cache[cache_key] = df.copy()

        return df

    # ── Tick ──────────────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> dict:
        """Return the latest bid/ask tick."""
        return connector.get_tick(symbol)

    # ── Multi-symbol ──────────────────────────────────────────────────────────

    def get_multi_symbol(
        self,
        symbols:   List[str],
        timeframe: str = "M15",
        count:     int = 200,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols in one call."""
        result: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = self.get_ohlcv(sym, timeframe, count)
                if not df.empty:
                    result[sym] = df
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", sym, exc)
        return result

    # ── Cache management ──────────────────────────────────────────────────────

    def invalidate_cache(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._cache = {k: v for k, v in self._cache.items()
                           if not k.startswith(symbol)}
        else:
            self._cache.clear()

    def cache_size(self) -> int:
        return len(self._cache)


# ── Module-level singleton ────────────────────────────────────────────────────
fetcher = DataFetcher()
