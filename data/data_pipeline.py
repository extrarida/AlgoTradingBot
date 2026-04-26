from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from config.settings import get_settings
from data.sources.exchange_rate_host_source import ExchangeRateHostMarketDataSource
from data.sources.external_api_source import AlphaVantageMarketDataSource
from data.sources.mt5_source import MT5MarketDataSource
from data.sources.mock_source import MockMarketDataSource
from data.sources.twelvedata_source import TwelveDataMarketDataSource
from data.sources.base import MarketDataSource

logger = logging.getLogger(__name__)


class FallbackMarketDataFetcher:
    def __init__(self, force_mock: bool = False) -> None:
        settings = get_settings()
        self._primary: MarketDataSource = MT5MarketDataSource()
        self._secondary_sources: List[MarketDataSource] = [
            AlphaVantageMarketDataSource(),
            TwelveDataMarketDataSource(),
            ExchangeRateHostMarketDataSource(),
        ]
        self._fallback: MarketDataSource = MockMarketDataSource()
        self._force_mock = force_mock
        self._settings = settings

    @property
    def force_mock(self) -> bool:
        return self._force_mock

    @force_mock.setter
    def force_mock(self, value: bool) -> None:
        self._force_mock = bool(value)

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        if self._force_mock:
            return self._fallback.get_rates(symbol, timeframe, count)

        try:
            if self._primary.is_available():
                return self._primary.get_rates(symbol, timeframe, count)
        except Exception as exc:
            logger.warning("Primary source failed for %s: %s", symbol, exc)

        for secondary in self._secondary_sources:
            try:
                if secondary.is_available():
                    result = secondary.get_rates(symbol, timeframe, count)
                    if not result.empty:
                        return result
            except Exception as exc:
                logger.warning("Secondary source %s failed for %s: %s", secondary.name, symbol, exc)

        logger.info(
            "Using mock data for %s because MT5 and all external APIs failed.", symbol
        )
        return self._fallback.get_rates(symbol, timeframe, count)

    def get_tick(self, symbol: str) -> dict:
        if self._force_mock:
            return self._fallback.get_tick(symbol)

        try:
            if self._primary.is_available():
                return self._primary.get_tick(symbol)
        except Exception as exc:
            logger.warning("Primary tick source failed for %s: %s", symbol, exc)

        for secondary in self._secondary_sources:
            try:
                if secondary.is_available():
                    tick = secondary.get_tick(symbol)
                    if tick:
                        return tick
            except Exception as exc:
                logger.warning("Secondary tick source %s failed for %s: %s", secondary.name, symbol, exc)

        logger.info(
            "Using mock tick for %s because MT5 and all external APIs failed.", symbol
        )
        return self._fallback.get_tick(symbol)

    def get_symbols(self) -> List[str]:
        if self._force_mock:
            return self._fallback.get_symbols()

        if self._primary.is_available():
            symbols = self._primary.get_symbols()
            if symbols:
                return symbols

        for secondary in self._secondary_sources:
            if secondary.is_available():
                symbols = secondary.get_symbols()
                if symbols:
                    return symbols

        return self._fallback.get_symbols()


class MarketDataPipeline:
    """Convenience wrapper for a singleton fetcher instance."""

    def __init__(self) -> None:
        self._fetcher = FallbackMarketDataFetcher()

    def set_force_mock(self, force: bool) -> None:
        self._fetcher.force_mock = force

    def get_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        return self._fetcher.get_rates(symbol, timeframe, count)

    def get_tick(self, symbol: str) -> dict:
        return self._fetcher.get_tick(symbol)

    def get_symbols(self) -> List[str]:
        return self._fetcher.get_symbols()
