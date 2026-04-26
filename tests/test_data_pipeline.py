from __future__ import annotations

import pandas as pd

from data.data_fetcher import fetcher


def test_fetcher_returns_unified_tick_structure_in_mock_mode() -> None:
    fetcher.set_force_mock(True)
    tick = fetcher.get_tick("EURUSD")

    assert isinstance(tick, dict)
    assert tick["source"] == "mock"
    assert isinstance(tick["bid"], float)
    assert isinstance(tick["ask"], float)
    assert isinstance(tick["spread"], float)
    assert isinstance(tick["volume"], int)
    assert isinstance(tick["time"], int)

    fetcher.set_force_mock(False)


def test_fetcher_returns_mock_ohlcv_dataframe() -> None:
    fetcher.set_force_mock(True)
    df = fetcher.get_ohlcv("EURUSD", "M15", 10)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "tick_volume"]
    assert len(df) == 10
    assert df.index.tzinfo is not None or df.index.dtype == object

    fetcher.set_force_mock(False)


def test_pipeline_includes_multiple_external_api_sources() -> None:
    sources = [source.name for source in fetcher._pipeline._fetcher._secondary_sources]
    assert "alpha_vantage" in sources
    assert "twelvedata" in sources
    assert "exchange_rate_host" in sources
