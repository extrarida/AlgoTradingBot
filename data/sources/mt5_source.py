from __future__ import annotations

import logging
from typing import List

import pandas as pd

from data.mt5_connector import connector
from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)


class MT5MarketDataSource(MarketDataSource):
    name = "mt5"

    def is_available(self) -> bool:
        return connector.is_connected and not connector.mock_mode

    def get_rates(self, symbol: str, timeframe: int, count: int) -> "pd.DataFrame":
        try:
            df = connector.get_rates(symbol, timeframe, count)
        except Exception as exc:
            logger.warning("MT5 get_rates failed for %s: %s", symbol, exc)
            raise
        if df.empty:
            raise RuntimeError(f"MT5 returned no candle data for {symbol}")
        return df

    def get_tick(self, symbol: str) -> dict:
        try:
            tick = connector.get_tick(symbol)
        except Exception as exc:
            logger.warning("MT5 get_tick failed for %s: %s", symbol, exc)
            raise
        if not tick:
            raise RuntimeError(f"MT5 returned no tick for {symbol}")
        tick["source"] = self.name
        return tick

    def get_symbols(self) -> List[str]:
        if self.is_available():
            return connector.get_symbols()
        return []
