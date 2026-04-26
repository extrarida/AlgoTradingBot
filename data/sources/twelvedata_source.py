from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import pandas as pd

from config.settings import get_settings
from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)

TIMEFRAME_TO_TWELVE_INTERVAL: Dict[int, str] = {
    1: "1min",
    5: "5min",
    15: "15min",
    30: "30min",
    60: "1h",
    16385: "1h",
    16388: "4h",
    16408: "1day",
    32769: "1week",
}


class TwelveDataMarketDataSource(MarketDataSource):
    name = "twelvedata"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.TWELVEDATA_API_KEY
        self.base_url = settings.TWELVEDATA_BASE_URL
        self.timeout = settings.EXTERNAL_API_TIMEOUT
        self.max_retries = max(1, settings.FALLBACK_RETRIES)
        self.retry_delay = max(0.1, settings.FALLBACK_RETRY_DELAY_SEC)
        self.client = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=self.timeout))

    def is_available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _retry_request(self, path: str, params: Dict[str, str]) -> Optional[Dict]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Unexpected TwelveData response format")
                return data
            except Exception as exc:
                logger.warning(
                    "TwelveData request attempt %d failed: %s",
                    attempt, exc,
                )
                if attempt < self.max_retries:
                    import time

                    time.sleep(self.retry_delay)
        return None

    @staticmethod
    def _format_symbol(symbol: str) -> str:
        if len(symbol) == 6:
            return f"{symbol[:3]}/{symbol[3:]}"
        return symbol

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        if not self.is_available():
            return pd.DataFrame()

        interval = TIMEFRAME_TO_TWELVE_INTERVAL.get(timeframe)
        if not interval:
            logger.debug("TwelveData unsupported timeframe: %s", timeframe)
            return pd.DataFrame()

        tw_symbol = self._format_symbol(symbol)
        params = {
            "symbol": tw_symbol,
            "interval": interval,
            "outputsize": str(min(max(count, 1), 5000)),
            "format": "JSON",
            "apikey": self.api_key,
        }

        data = self._retry_request("time_series", params)
        if not data or "values" not in data:
            return pd.DataFrame()

        rows = []
        for item in reversed(data.get("values", [])[:count]):
            try:
                rows.append(
                    {
                        "time": pd.to_datetime(item["datetime"]).tz_localize("UTC"),
                        "open": float(item.get("open", 0.0)),
                        "high": float(item.get("high", 0.0)),
                        "low": float(item.get("low", 0.0)),
                        "close": float(item.get("close", 0.0)),
                        "tick_volume": float(item.get("volume", 0.0)),
                    }
                )
            except Exception as exc:
                logger.debug("Skipping invalid TwelveData row for %s: %s", symbol, exc)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("time")
        df = df.sort_index()
        return df[["open", "high", "low", "close", "tick_volume"]]

    def get_tick(self, symbol: str) -> dict:
        if not self.is_available():
            return {}

        tw_symbol = self._format_symbol(symbol)
        params = {
            "symbol": tw_symbol,
            "apikey": self.api_key,
        }

        data = self._retry_request("quote", params)
        if not data:
            return {}

        try:
            bid = float(data.get("bid", 0.0))
            ask = float(data.get("ask", 0.0))
            last = float(data.get("close", 0.0))
        except Exception:
            return {}

        spread = round(max(ask - bid, 0.0), 5)
        return {
            "symbol": symbol,
            "bid": round(bid, 5),
            "ask": round(ask, 5),
            "last": round(last, 5),
            "spread": spread,
            "volume": int(float(data.get("volume", 0) or 0)),
            "time": int(datetime.utcnow().timestamp()),
            "source": self.name,
        }
