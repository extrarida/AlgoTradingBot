"""
execution/trade_executor.py
───────────────────────────
This file is the final step before a real trade is placed.
It takes an approved BUY or SELL signal, calculates the exact
entry price, stop loss, and take profit levels, builds the
complete order, and sends it to MT5 to execute with the broker.
It also saves every trade to the database for history tracking.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional

# Import MT5 connection and order type constants
from data.mt5_connector import (
    connector, TRADE_ACTION_DEAL, ORDER_TYPE_BUY,
    ORDER_TYPE_SELL, ORDER_TIME_GTC, ORDER_FILLING_IOC, ORDER_FILLING_FOK, RETCODE_DONE,
)
# Import risk manager to record each trade toward the daily limit
from execution.risk_manager import risk_manager
# Import Signal type — BUY, SELL, or NONE
from strategies.base import Signal
# Import database function to save trade history
from database.repository import save_trade

logger = logging.getLogger(__name__)


# ── Order state labels ────────────────────────────────────────────────────────
# These labels describe what stage an order is currently at.
# Every trade starts as PENDING and ends as FILLED or REJECTED.
class OrderState(str):
    PENDING          = "PENDING"           # Order created, not sent yet
    SENT             = "SENT"              # Order sent to MT5
    FILLED           = "FILLED"            # Trade successfully executed
    REJECTED         = "REJECTED"          # Trade was blocked or failed
    CANCELLED        = "CANCELLED"         # Signal was NONE, no trade needed
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # Only part of the order was filled


# ── Trade Request — what the bot wants to do ──────────────────────────────────
# This is the instruction sent to the executor.
# It contains all the details needed to place a trade:
# which symbol, which direction, how big, and where to put SL/TP.
@dataclass
class TradeRequest:
    symbol:   str          # Trading pair e.g. 'EURUSD'
    signal:   Signal       # BUY or SELL
    lot:      float        # Trade size e.g. 0.01
    sl_pips:  int          # Stop loss distance in pips e.g. 50
    tp_pips:  int          # Take profit distance in pips e.g. 100
    comment:  str = "algobot"   # Label shown in MT5 trade history
    magic:    int = 123456      # Unique ID so the bot can identify its own trades


# ── Trade Result — what actually happened ─────────────────────────────────────
# This is returned after every trade attempt — successful or not.
# Contains full details of what happened including price, SL, TP,
# order ID from the broker, and whether the trade succeeded.
@dataclass
class TradeResult:
    success:     bool                    # True if trade was executed
    order_id:    Optional[int]   = None  # Order number from the broker
    deal_id:     Optional[int]   = None  # Deal number from the broker
    retcode:     int             = 0     # MT5 response code (10009 = success)
    message:     str             = ""    # Message from MT5 explaining result
    price:       float           = 0.0   # Price the trade was executed at
    lot:         float           = 0.0   # Lot size that was executed
    sl:          float           = 0.0   # Exact stop loss price level
    tp:          float           = 0.0   # Exact take profit price level
    state:       str             = OrderState.PENDING  # Current order status
    timestamp:   datetime        = field(default_factory=datetime.utcnow)  # Time of execution
    raw_request: Optional[dict]  = None  # The full MT5 order that was sent


# ── Main Trade Executor class ─────────────────────────────────────────────────
# This class does the actual work of building and sending orders to MT5.
# One instance is shared across the whole bot (see bottom of file).
class TradeExecutor:

    # Standard pip size for most forex pairs (e.g. EURUSD, GBPUSD)
    # JPY pairs use 0.01 instead — handled separately below
    PIP_SIZE: float = 0.0001

    def execute(self, req: TradeRequest) -> TradeResult:
        """
        Takes a TradeRequest and sends it to MT5 as a real order.
        Returns a TradeResult with everything that happened.
        """
        # Step 1 — Check MT5 is connected before doing anything
        # If not connected, reject immediately without trying anything else
        if not connector.is_connected:
            return TradeResult(False, message="MT5 not connected",
                               state=OrderState.REJECTED)

        # Step 2 — Get the current live bid/ask price for the symbol
        # Without a live price, we cannot calculate SL and TP levels
        tick = connector.get_tick(req.symbol)
        if not tick:
            return TradeResult(False, message=f"No tick for {req.symbol}",
                               state=OrderState.REJECTED)

        # Step 3 — Set the correct pip size for this symbol
        # JPY pairs move in different increments so need 0.01 instead of 0.0001
        pip = 0.01 if "JPY" in req.symbol else self.PIP_SIZE

        # Step 4 — Calculate exact prices based on BUY or SELL direction
        if req.signal == Signal.BUY:
            # For BUY: enter at the ASK price (what the broker sells at)
            # Stop loss goes BELOW entry, take profit goes ABOVE entry
            price      = tick["ask"]
            order_type = ORDER_TYPE_BUY
            sl_price   = round(price - req.sl_pips * pip, 5)
            tp_price   = round(price + req.tp_pips * pip, 5)
        elif req.signal == Signal.SELL:
            # For SELL: enter at the BID price (what the broker buys at)
            # Stop loss goes ABOVE entry, take profit goes BELOW entry
            price      = tick["bid"]
            order_type = ORDER_TYPE_SELL
            sl_price   = round(price + req.sl_pips * pip, 5)
            tp_price   = round(price - req.tp_pips * pip, 5)
        else:
            # Signal is NONE — no trade needed, cancel quietly
            return TradeResult(False, message="Signal is NONE – no trade",
                               state=OrderState.CANCELLED)

        # Step 5 — Build the complete MT5 order package
        # This is the exact format MT5 requires to process an order
        mt5_req = {
            "action":       TRADE_ACTION_DEAL,   # Execute immediately as market order
            "symbol":       req.symbol,           # e.g. 'EURUSD'
            "volume":       req.lot,              # Trade size e.g. 0.01
            "type":         order_type,           # BUY or SELL
            "price":        price,                # Entry price
            "sl":           sl_price,             # Stop loss price
            "tp":           tp_price,             # Take profit price
            "deviation":    20,                   # Max allowed price slippage in points
            "magic":        req.magic,            # Bot's unique ID number
            "comment":      req.comment,          # Label shown in MT5
            "type_time":    ORDER_TIME_GTC,       # Keep order open until cancelled
            "type_filling": ORDER_FILLING_FOK,    # Fill as much as possible immediately
        }

        # Step 6 — Log what we are about to send (visible in terminal)
        logger.info("Sending %s %s %.2f lots @ %.5f SL=%.5f TP=%.5f",
                    req.signal.value, req.symbol, req.lot,
                    price, sl_price, tp_price)

        # Step 7 — Send the order to MT5
        raw = connector.send_order(mt5_req)
        # MT5 returns code 10009 to confirm the trade was successfully filled
        success = raw.get("retcode") == RETCODE_DONE

        # Step 8 — Handle the result
        if success:
            # Trade worked — record it toward today's daily trade count
            risk_manager.record_trade()
            state = OrderState.FILLED
            # Save the trade to the database so it appears in trade history
            save_trade(
                symbol      = req.symbol,
                direction   = req.signal.value,   # 'BUY' or 'SELL'
                lot_size    = req.lot,
                entry_price = raw.get("price", price),
                sl_price    = sl_price,
                tp_price    = tp_price,
                sl_pips     = req.sl_pips,
                tp_pips     = req.tp_pips,
                order_id    = raw.get("order"),
                deal_id     = raw.get("deal"),
            )
        else:
            # Trade failed — mark as rejected (no database entry saved)
            state = OrderState.REJECTED

        # Step 9 — Return the full result back to the strategy engine
        return TradeResult(
            success     = success,
            order_id    = raw.get("order"),       # Broker's order number
            deal_id     = raw.get("deal"),        # Broker's deal number
            retcode     = raw.get("retcode", -1), # MT5 response code
            message     = raw.get("comment", ""), # MT5 message
            price       = raw.get("price", price),# Actual execution price
            lot         = raw.get("volume", req.lot), # Actual lot filled
            sl          = sl_price,               # Stop loss level
            tp          = tp_price,               # Take profit level
            state       = state,                  # FILLED or REJECTED
            raw_request = mt5_req,                # The full order that was sent
        )


# ── Single shared instance ────────────────────────────────────────────────────
# One shared TradeExecutor used by the whole bot.
# The strategy engine imports this directly to place all trades.
executor = TradeExecutor()