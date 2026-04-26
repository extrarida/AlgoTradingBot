from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

import pandas as pd


class MarketDataSource(ABC):
    """Base interface for a market data source."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True when the source can be used."""
        raise NotImplementedError

    @abstractmethod
    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        """Return candle data normalized to MT5 format."""
        raise NotImplementedError

    @abstractmethod
    def get_tick(self, symbol: str) -> dict:
        """Return the latest bid/ask tick normalized to the shared contract."""
        raise NotImplementedError

    def get_symbols(self) -> List[str]:
        """Return a list of supported symbols if available."""
        return []
