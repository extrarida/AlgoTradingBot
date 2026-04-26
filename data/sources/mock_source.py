from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd

from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)


class MockMarketDataSource(MarketDataSource):
    name = "mock"

    def __init__(self) -> None:
        self._symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "AUDUSD"]

    def is_available(self) -> bool:
        return True

    def get_symbols(self) -> List[str]:
        return list(self._symbols)

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        seed = abs(hash(f"mock_rates:{symbol}:{timeframe}:{count}")) % (2**31 - 1)
        rng = np.random.default_rng(seed)

        base_values = {
            "EURUSD": 1.10,
            "GBPUSD": 1.27,
            "USDJPY": 149.50,
            "XAUUSD": 2350.00,
            "US30": 38500.00,
            "USDCAD": 1.35,
            "AUDUSD": 0.67,
        }
        base = float(base_values.get(symbol, 1.00))
        volatility = max(base * 0.0004, 0.0001)

        closes = base + np.cumsum(rng.normal(0.0, volatility, count))
        closes = np.maximum(closes, base * 0.5)
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        highs = np.maximum(opens, closes) + rng.uniform(volatility * 0.1, volatility * 1.5, count)
        lows = np.minimum(opens, closes) - rng.uniform(volatility * 0.1, volatility * 1.5, count)
        volumes = rng.integers(500, 8000, count).astype(float)

        interval_minutes = 15
        if timeframe == 1:
            interval_minutes = 1
        elif timeframe == 5:
            interval_minutes = 5
        elif timeframe == 15:
            interval_minutes = 15
        elif timeframe == 30:
            interval_minutes = 30
        elif timeframe in {16385, 16388, 16408, 32769}:
            interval_minutes = 60

        end = datetime.utcnow().replace(second=0, microsecond=0)
        index = pd.date_range(end=end, periods=count, freq=f"{interval_minutes}min", tz="UTC")

        df = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "tick_volume": volumes,
            },
            index=index,
        )
        return df

    def get_tick(self, symbol: str) -> dict:
        base_values = {
            "EURUSD": 1.10,
            "GBPUSD": 1.27,
            "USDJPY": 149.50,
            "XAUUSD": 2350.00,
            "US30": 38500.00,
            "USDCAD": 1.35,
            "AUDUSD": 0.67,
        }
        base = float(base_values.get(symbol, 1.00))
        seed = abs(hash(f"mock_tick:{symbol}")) % (2**31 - 1)
        rng = np.random.default_rng(seed)
        move = rng.normal(0.0, base * 0.0002)
        bid = round(base + move, 5)
        ask = round(bid + max(base * 0.0001, 0.00001), 5)
        spread = round(ask - bid, 5)
        if spread <= 0:
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
            "source": self.name,
        }
