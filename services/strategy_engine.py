"""
services/strategy_engine.py
────────────────────────────
Layer 9 – Strategy Engine

Runs all 40 strategies on a given OHLCV DataFrame and returns an
aggregated signal using majority-vote + confidence weighting.
"""

from __future__ import annotations
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import List

import pandas as pd

from strategies.base import BaseStrategy, Signal, StrategyResult
from strategies.buy  import ALL_BUY_STRATEGIES
from strategies.sell import ALL_SELL_STRATEGIES
from config.settings import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class AggregatedSignal:
    final_signal:    Signal
    confidence:      float
    buy_votes:       int
    sell_votes:      int
    none_votes:      int
    top_strategies:  List[StrategyResult] = field(default_factory=list)
    total_evaluated: int = 0


class StrategyEngine:
    """
    Evaluates all registered strategies and aggregates results.

    Voting rules
    ────────────
    • A signal is only emitted when:
        – winning side has >= min_votes votes
        – average confidence of winning side >= confidence_threshold
    • Errors in individual strategies are caught silently.
    """

    def __init__(
        self,
        buy_strategies:       List[BaseStrategy] | None = None,
        sell_strategies:      List[BaseStrategy] | None = None,
        min_votes:            int   | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self.buy_strategies       = buy_strategies  or ALL_BUY_STRATEGIES
        self.sell_strategies      = sell_strategies or ALL_SELL_STRATEGIES
        self.min_votes            = min_votes            or settings.MIN_STRATEGY_VOTES
        self.confidence_threshold = confidence_threshold or settings.CONFIDENCE_THRESHOLD

    def evaluate(self, df: pd.DataFrame, symbol: str = "") -> AggregatedSignal:
        """Run all strategies and return an AggregatedSignal."""
        all_results: List[StrategyResult] = []

        for strategy in self.buy_strategies + self.sell_strategies:
            try:
                result = strategy.evaluate(df)
                all_results.append(result)
            except Exception as exc:
                logger.warning("Strategy %s failed on %s: %s",
                               strategy.name, symbol, exc)

        votes        = Counter(r.signal for r in all_results)
        buy_results  = [r for r in all_results if r.signal == Signal.BUY]
        sell_results = [r for r in all_results if r.signal == Signal.SELL]

        buy_conf  = (sum(r.confidence for r in buy_results)  / len(buy_results)  if buy_results  else 0)
        sell_conf = (sum(r.confidence for r in sell_results) / len(sell_results) if sell_results else 0)

        bv = votes[Signal.BUY]
        sv = votes[Signal.SELL]
        nv = votes[Signal.NONE]

        if bv >= self.min_votes and bv > sv and buy_conf >= self.confidence_threshold:
            top = sorted(buy_results, key=lambda r: r.confidence, reverse=True)[:5]
            return AggregatedSignal(Signal.BUY,  buy_conf,  bv, sv, nv, top, len(all_results))

        if sv >= self.min_votes and sv > bv and sell_conf >= self.confidence_threshold:
            top = sorted(sell_results, key=lambda r: r.confidence, reverse=True)[:5]
            return AggregatedSignal(Signal.SELL, sell_conf, bv, sv, nv, top, len(all_results))

        return AggregatedSignal(Signal.NONE, 0.0, bv, sv, nv, [], len(all_results))


# ── Module-level singleton ────────────────────────────────────────────────────
engine = StrategyEngine()
