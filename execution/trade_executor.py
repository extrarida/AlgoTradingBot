"""
execution/trade_executor.py
───────────────────────────
Layers 11–12 – OMS + Execution Engine

Converts approved signals into MT5 trade requests,
manages order state, and returns structured results.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional

from data.mt5_connector import (
    connector, TRADE_ACTION_DEAL, ORDER_TYPE_BUY,
    ORDER_TYPE_SELL, ORDER_TIME_GTC, ORDER_FILLING_IOC, RETCODE_DONE,
)
from execution.risk_manager import risk_manager
from strategies.base import Signal

logger = logging.getLogger(__name__)


class OrderState(str):
    PENDING          = "PENDING"
    SENT             = "SENT"
    FILLED           = "FILLED"
    REJECTED         = "REJECTED"
    CANCELLED        = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"


@dataclass
class TradeRequest:
    symbol:   str
    signal:   Signal
    lot:      float
    sl_pips:  int
    tp_pips:  int
    comment:  str = "algobot"
    magic:    int = 123456


@dataclass
class TradeResult:
    success:    bool
    order_id:   Optional[int]   = None
    deal_id:    Optional[int]   = None
    retcode:    int             = 0
    message:    str             = ""
    price:      float           = 0.0
    lot:        float           = 0.0
    sl:         float           = 0.0
    tp:         float           = 0.0
    state:      str             = OrderState.PENDING
    timestamp:  datetime        = field(default_factory=datetime.utcnow)
    raw_request: Optional[dict] = None


class TradeExecutor:
    """
    Converts a TradeRequest into an MT5 order and dispatches it.
    Tracks order state through the lifecycle.
    """

    # Standard pip size for most FX pairs
    PIP_SIZE: float = 0.0001

    def execute(self, req: TradeRequest) -> TradeResult:
        """
        Build and send an MT5 market order.
        Returns a TradeResult with full execution details.
        """
        if not connector.is_connected:
            return TradeResult(False, message="MT5 not connected", state=OrderState.REJECTED)

        tick = connector.get_tick(req.symbol)
        if not tick:
            return TradeResult(False, message=f"No tick for {req.symbol}",
                               state=OrderState.REJECTED)

        # Determine pip size from symbol
        pip = 0.01 if "JPY" in req.symbol else self.PIP_SIZE

        if req.signal == Signal.BUY:
            price     = tick["ask"]
            order_type = ORDER_TYPE_BUY
            sl_price  = round(price - req.sl_pips * pip, 5)
            tp_price  = round(price + req.tp_pips * pip, 5)
        elif req.signal == Signal.SELL:
            price     = tick["bid"]
            order_type = ORDER_TYPE_SELL
            sl_price  = round(price + req.sl_pips * pip, 5)
            tp_price  = round(price - req.tp_pips * pip, 5)
        else:
            return TradeResult(False, message="Signal is NONE – no trade",
                               state=OrderState.CANCELLED)

        mt5_req = {
            "action":       TRADE_ACTION_DEAL,
            "symbol":       req.symbol,
            "volume":       req.lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl_price,
            "tp":           tp_price,
            "deviation":    20,
            "magic":        req.magic,
            "comment":      req.comment,
            "type_time":    ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        }

        logger.info("Sending %s %s %.2f lots @ %.5f SL=%.5f TP=%.5f",
                    req.signal.value, req.symbol, req.lot, price, sl_price, tp_price)

        raw = connector.send_order(mt5_req)
        success = raw.get("retcode") == RETCODE_DONE

        if success:
            risk_manager.record_trade()
            state = OrderState.FILLED
        else:
            state = OrderState.REJECTED

        return TradeResult(
            success     = success,
            order_id    = raw.get("order"),
            deal_id     = raw.get("deal"),
            retcode     = raw.get("retcode", -1),
            message     = raw.get("comment", ""),
            price       = raw.get("price", price),
            lot         = raw.get("volume", req.lot),
            sl          = sl_price,
            tp          = tp_price,
            state       = state,
            raw_request = mt5_req,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
executor = TradeExecutor()
