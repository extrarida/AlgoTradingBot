"""
services/strategy_engine.py
────────────────────────────
This file is the brain of the bot — the decision maker.
It runs all 40 trading strategies simultaneously on the latest price data,
collects their votes, and decides whether to generate a BUY, SELL, or NONE signal.

No single strategy can trigger a trade alone.
A signal is only generated when BOTH of these conditions are met:
  1. At least 3 strategies agree on the same direction (BUY or SELL)
  2. The average confidence of those agreeing strategies is 60% or above

This consensus requirement filters out noise and prevents overtrading.
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


# ── AggregatedSignal — the result returned after all strategies have voted ────
# This holds everything the rest of the system needs to know about
# what the strategies decided. It is passed to the risk manager and
# trade executor when a signal is generated.
@dataclass
class AggregatedSignal:
    final_signal:    Signal            # BUY, SELL, or NONE
    confidence:      float             # average confidence of the winning side (0 to 1)
    buy_votes:       int               # how many strategies voted BUY
    sell_votes:      int               # how many strategies voted SELL
    none_votes:      int               # how many strategies voted NONE
    top_strategies:  List[StrategyResult] = field(default_factory=list)
                                       # top 5 most confident strategies that voted
    total_evaluated: int = 0           # total number of strategies that ran


# ── StrategyEngine class ──────────────────────────────────────────────────────
# This class orchestrates all 40 strategies.
# It is the central coordinator — it runs everything, collects results,
# applies voting rules, and returns a single clear decision.
class StrategyEngine:
    """
    Runs all registered buy and sell strategies on price data and
    aggregates their individual votes into one final signal.

    Voting rules:
      - Winning side must have at least min_votes votes (default 3)
      - Winning side must have average confidence >= threshold (default 60%)
      - Winning side must have MORE votes than the opposing side
      - If none of these are met, signal is NONE and no trade is placed
    """

    def __init__(
        self,
        buy_strategies:       List[BaseStrategy] | None = None,
        sell_strategies:      List[BaseStrategy] | None = None,
        min_votes:            int   | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        # Load the strategy lists — defaults to all 20 buy and 20 sell strategies
        # Custom lists can be passed in for testing specific strategies in isolation
        self.buy_strategies  = buy_strategies  or ALL_BUY_STRATEGIES
        self.sell_strategies = sell_strategies or ALL_SELL_STRATEGIES

        # Load voting thresholds from settings — can be changed in .env file
        # min_votes = minimum number of strategies that must agree (default 3)
        # confidence_threshold = minimum average confidence required (default 0.60)
        self.min_votes            = min_votes            or settings.MIN_STRATEGY_VOTES
        self.confidence_threshold = confidence_threshold or settings.CONFIDENCE_THRESHOLD

    def evaluate(self, df: pd.DataFrame, symbol: str = "") -> AggregatedSignal:
        """
        Runs all 40 strategies on the provided price data and returns
        an AggregatedSignal with the final decision and full vote breakdown.

        df = the OHLCV candle data (open, high, low, close, volume)
        symbol = the trading pair being evaluated e.g. 'EURUSD' (used for logging)
        """
        # This list will collect the result from every strategy that runs
        all_results: List[StrategyResult] = []

        # Step 1 — Run every strategy one by one
        # buy_strategies + sell_strategies combines both lists into one loop
        for strategy in self.buy_strategies + self.sell_strategies:
            try:
                # Pass the price data to the strategy and get its vote back
                result = strategy.evaluate(df)
                all_results.append(result)
            except Exception as exc:
                # If one strategy crashes, log the error and skip it
                # The other 39 strategies still run normally
                # This prevents one broken strategy from stopping everything
                logger.warning("Strategy %s failed on %s: %s",
                               strategy.name, symbol, exc)

        # Step 2 — Count how many strategies voted for each direction
        # Counter counts occurrences of each Signal value in the results
        votes = Counter(r.signal for r in all_results)

        # Separate the results by direction for confidence calculation
        buy_results  = [r for r in all_results if r.signal == Signal.BUY]
        sell_results = [r for r in all_results if r.signal == Signal.SELL]

        # Step 3 — Calculate average confidence for each side
        # If no strategies voted BUY, buy confidence is 0
        # If no strategies voted SELL, sell confidence is 0
        buy_conf  = (sum(r.confidence for r in buy_results)  / len(buy_results)
                     if buy_results  else 0)
        sell_conf = (sum(r.confidence for r in sell_results) / len(sell_results)
                     if sell_results else 0)

        # Extract the vote counts for each direction
        bv = votes[Signal.BUY]   # number of BUY votes
        sv = votes[Signal.SELL]  # number of SELL votes
        nv = votes[Signal.NONE]  # number of NONE votes

        # Step 4 — Apply the BUY signal rules
        # All three conditions must be True simultaneously:
        #   bv >= self.min_votes      → enough strategies agreed (at least 3)
        #   bv > sv                   → BUY side has more votes than SELL side
        #   buy_conf >= threshold     → average confidence is high enough (60%+)
        if bv >= self.min_votes and bv > sv and buy_conf >= self.confidence_threshold:
            # Get the top 5 most confident buy strategies for logging and display
            top = sorted(buy_results, key=lambda r: r.confidence, reverse=True)[:5]
            return AggregatedSignal(Signal.BUY, buy_conf, bv, sv, nv, top, len(all_results))

        # Step 5 — Apply the SELL signal rules (same logic as BUY but reversed)
        # All three conditions must be True simultaneously:
        #   sv >= self.min_votes      → enough strategies agreed (at least 3)
        #   sv > bv                   → SELL side has more votes than BUY side
        #   sell_conf >= threshold    → average confidence is high enough (60%+)
        if sv >= self.min_votes and sv > bv and sell_conf >= self.confidence_threshold:
            # Get the top 5 most confident sell strategies for logging and display
            top = sorted(sell_results, key=lambda r: r.confidence, reverse=True)[:5]
            return AggregatedSignal(Signal.SELL, sell_conf, bv, sv, nv, top, len(all_results))

        # Step 6 — Neither BUY nor SELL conditions were met
        # Return NONE — no trade will be placed this cycle
        # This is the most common outcome — the bot does nothing and waits
        return AggregatedSignal(Signal.NONE, 0.0, bv, sv, nv, [], len(all_results))


# ── Single shared instance ────────────────────────────────────────────────────
# One shared StrategyEngine used by the whole bot.
# main.py and the background scheduler import this 'engine' object directly
# and call engine.evaluate() on every 60-second cycle.
engine = StrategyEngine()