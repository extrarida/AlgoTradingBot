from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import pandas as pd

from config.settings import get_settings
from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)

TIMEFRAME_TO_ALPHA_INTERVAL: Dict[int, str] = {
    1: "1min",
    5: "5min",
    15: "15min",
    30: "30min",
    60: "60min",
    16385: "60min",
    16388: "60min",
    16408: "60min",
    32769: "60min",
}


class AlphaVantageMarketDataSource(MarketDataSource):
    name = "alpha_vantage"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.EXTERNAL_API_KEY
        self.base_url = settings.EXTERNAL_API_BASE_URL
        self.timeout = settings.EXTERNAL_API_TIMEOUT
        self.max_retries = max(1, settings.FALLBACK_RETRIES)
        self.retry_delay = max(0.1, settings.FALLBACK_RETRY_DELAY_SEC)
        self.client = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=self.timeout))

    def is_available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _retry_request(self, params: Dict[str, str]) -> Optional[Dict]:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Unexpected API response format")
                return data
            except Exception as exc:
                logger.warning(
                    "AlphaVantage request attempt %d failed: %s",
                    attempt, exc,
                )
                if attempt < self.max_retries:
                    import time

                    time.sleep(self.retry_delay)
        return None

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        if not self.is_available():
            return pd.DataFrame()

        if len(symbol) != 6:
            logger.debug("AlphaVantage only supports 6-character FX symbols: %s", symbol)
            return pd.DataFrame()

        interval = TIMEFRAME_TO_ALPHA_INTERVAL.get(timeframe)
        if not interval:
            logger.debug("AlphaVantage unsupported timeframe: %s", timeframe)
            return pd.DataFrame()

        from_currency = symbol[:3]
        to_currency = symbol[3:]
        params = {
            "function": "FX_INTRADAY",
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "interval": interval,
            "outputsize": "compact",
            "apikey": self.api_key,
        }

        data = self._retry_request(params)
        if not data:
            return pd.DataFrame()

        key = f"Time Series FX ({interval})"
        price_series = data.get(key) or data.get("Time Series FX (60min)")
        if not isinstance(price_series, dict):
            logger.warning("AlphaVantage returned no time series for %s", symbol)
            return pd.DataFrame()

        rows = []
        for timestamp, values in list(price_series.items())[:count]:
            try:
                rows.append(
                    {
                        "time": pd.to_datetime(timestamp).tz_localize("UTC"),
                        "open": float(values.get("1. open", 0.0)),
                        "high": float(values.get("2. high", 0.0)),
                        "low": float(values.get("3. low", 0.0)),
                        "close": float(values.get("4. close", 0.0)),
                        "tick_volume": float(values.get("5. volume", 0.0)),
                    }
                )
            except Exception as exc:
                logger.debug("Skipping invalid AlphaVantage row for %s: %s", symbol, exc)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("time")
        df = df.sort_index()
        return df[["open", "high", "low", "close", "tick_volume"]]

    def get_tick(self, symbol: str) -> dict:
        if not self.is_available() or len(symbol) != 6:
            return {}

        from_currency = symbol[:3]
        to_currency = symbol[3:]
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "apikey": self.api_key,
        }

        data = self._retry_request(params)
        if not data:
            return {}

        rate_data = data.get("Realtime Currency Exchange Rate")
        if not isinstance(rate_data, dict):
            return {}

        try:
            price = float(rate_data.get("5. Exchange Rate", 0.0))
            bid = float(rate_data.get("8. Bid Price", price))
            ask = float(rate_data.get("9. Ask Price", price))
        except Exception:
            return {}

        spread = round(ask - bid, 5)
        return {
            "symbol": symbol,
            "bid": round(bid, 5),
            "ask": round(ask, 5),
            "last": round(price, 5),
            "spread": spread,
            "volume": 0,
            "time": int(datetime.utcnow().timestamp()),
            "source": self.name,
        }
