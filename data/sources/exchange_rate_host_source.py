from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
import pandas as pd

from config.settings import get_settings
from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)

TIMEFRAME_TO_EXCHANGE_RATE_HOST: Dict[int, str] = {
    15: "daily",
    30: "daily",
    60: "daily",
    16385: "daily",
    16388: "daily",
    16408: "daily",
    32769: "weekly",
}


class ExchangeRateHostMarketDataSource(MarketDataSource):
    name = "exchange_rate_host"

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.EXCHANGE_RATE_HOST_BASE_URL
        self.timeout = settings.EXTERNAL_API_TIMEOUT
        self.max_retries = max(1, settings.FALLBACK_RETRIES)
        self.retry_delay = max(0.1, settings.FALLBACK_RETRY_DELAY_SEC)
        self.client = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=self.timeout))

    def is_available(self) -> bool:
        return bool(self.base_url)

    def _retry_request(self, path: str, params: Dict[str, str]) -> Optional[Dict]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Unexpected ExchangeRateHost response format")
                return data
            except Exception as exc:
                logger.warning(
                    "ExchangeRateHost request attempt %d failed: %s",
                    attempt, exc,
                )
                if attempt < self.max_retries:
                    import time

                    time.sleep(self.retry_delay)
        return None

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        if not self.is_available() or len(symbol) != 6:
            return pd.DataFrame()

        interval = TIMEFRAME_TO_EXCHANGE_RATE_HOST.get(timeframe)
        if not interval:
            logger.debug("ExchangeRateHost unsupported timeframe: %s", timeframe)
            return pd.DataFrame()

        from_currency = symbol[:3]
        to_currency = symbol[3:]
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=min(count * 2, 365))
        params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "base": from_currency,
            "symbols": to_currency,
        }

        data = self._retry_request("timeseries", params)
        if not data or not data.get("rates"):
            return pd.DataFrame()

        rows = []
        for timestamp, values in sorted(data["rates"].items()):
            rate = values.get(to_currency)
            if rate is None:
                continue
            rows.append(
                {
                    "time": pd.to_datetime(timestamp).tz_localize("UTC"),
                    "open": float(rate),
                    "high": float(rate),
                    "low": float(rate),
                    "close": float(rate),
                    "tick_volume": 0.0,
                }
            )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("time")
        if interval == "weekly":
            df = df.resample("W").last()
        else:
            df = df.resample("D").last()

        df = df.dropna().tail(count)
        return df[["open", "high", "low", "close", "tick_volume"]]

    def get_tick(self, symbol: str) -> dict:
        if not self.is_available() or len(symbol) != 6:
            return {}

        from_currency = symbol[:3]
        to_currency = symbol[3:]
        params = {
            "from": from_currency,
            "to": to_currency,
            "amount": "1",
        }

        data = self._retry_request("convert", params)
        if not data:
            return {}

        rate = data.get("result")
        try:
            last = float(rate)
        except Exception:
            return {}

        bid = round(last - last * 0.0001, 5)
        ask = round(last + last * 0.0001, 5)
        spread = round(ask - bid, 5)

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": last,
            "spread": spread,
            "volume": 0,
            "time": int(datetime.utcnow().timestamp()),
            "source": self.name,
        }
