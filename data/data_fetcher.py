"""
data/data_fetcher.py
────────────────────
This file sits between the strategies and the market data pipeline.
It provides a stable cache and a single shared fetcher instance.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from data.data_pipeline import MarketDataPipeline
from data.mt5_connector import TIMEFRAME_MAP

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Central market data accessor for the bot.
    Uses a fallback pipeline to fetch from MT5, external API, or mock.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, pd.DataFrame] = {}
        self._pipeline = MarketDataPipeline()

    def set_force_mock(self, force: bool) -> None:
        """Enable or disable explicit mock mode for all data requests."""
        self._pipeline.set_force_mock(force)

    def get_ohlcv(
        self,
        symbol:    str,
        timeframe: str = "M15",
        count:     int = 500,
        use_cache: bool = False,
    ) -> pd.DataFrame:
        cache_key = f"{symbol}_{timeframe}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        tf = TIMEFRAME_MAP.get(timeframe.upper(), 15)
        df = self._pipeline.get_rates(symbol, tf, count)

        if df.empty:
            logger.warning("Fallback pipeline returned empty OHLCV for %s / %s", symbol, timeframe)
            return df

        if use_cache:
            self._cache[cache_key] = df.copy()
        return df

    def get_tick(self, symbol: str) -> dict:
        return self._pipeline.get_tick(symbol)

    def get_multi_symbol(
        self,
        symbols:   List[str],
        timeframe: str = "M15",
        count:     int = 200,
    ) -> Dict[str, pd.DataFrame]:
        result: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = self.get_ohlcv(sym, timeframe, count)
                if not df.empty:
                    result[sym] = df
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", sym, exc)
        return result

    def get_symbols(self) -> List[str]:
        return self._pipeline.get_symbols()

    def invalidate_cache(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._cache = {k: v for k, v in self._cache.items() if not k.startswith(symbol)}
        else:
            self._cache.clear()

    def cache_size(self) -> int:
        return len(self._cache)


fetcher = DataFetcher()
