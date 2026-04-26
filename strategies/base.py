"""
strategies/base.py
──────────────────
Abstract base class, Signal enum, and StrategyResult dataclass
shared by all 40 strategies.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

import pandas as pd


class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass
class StrategyResult:
    signal:     Signal
    strategy:   str
    confidence: float              = 0.0   # 0.0 – 1.0
    reason:     str                = ""
    params:     Dict[str, Any]     = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Every strategy must implement evaluate(df) which receives an OHLCV
    DataFrame and returns a StrategyResult.

    DataFrame columns expected:
        open, high, low, close, tick_volume  (float64)
    Index:
        DatetimeIndex (UTC)
    """

    name:     str = "unnamed"
    category: str = "generic"   # "swing" | "scalp" | "risk"

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> StrategyResult:
        ...

    # ── Convenience builders ──────────────────────────────────────────────────

    def _no_signal(self, reason: str = "") -> StrategyResult:
        return StrategyResult(Signal.NONE, self.name, 0.0, reason)

    def _buy(self, confidence: float = 0.70, reason: str = "",
             **params) -> StrategyResult:
        return StrategyResult(Signal.BUY, self.name, confidence, reason, params)

    def _sell(self, confidence: float = 0.70, reason: str = "",
              **params) -> StrategyResult:
        return StrategyResult(Signal.SELL, self.name, confidence, reason, params)
