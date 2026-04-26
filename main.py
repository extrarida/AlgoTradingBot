"""
main.py
───────
FastAPI server — the central bridge between the HTML frontend and the Python
trading backend.

This file does five things:
  1. Starts the database on application launch (creates tables if missing)
  2. Starts the automated trading scheduler (runs every 30 seconds)
  3. Serves the five HTML pages when a browser navigates to a URL
  4. Exposes a REST API that the JavaScript on each page calls for live data
  5. Wires all the other modules together — strategies, risk, executor, database

Request flow (what happens when you click something on the dashboard):
  Browser → HTTP request → FastAPI endpoint → Python module → JSON response
                                                             → JavaScript updates UI

To run:
    uvicorn main:app --reload --port 8000

Then open: http://localhost:8000
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ── Internal module imports ───────────────────────────────────────────────────
# Each import pulls in a specific layer of the application.
# Keeping imports grouped by layer makes the architecture visible at a glance.

from config.settings import get_settings

# Data layer — responsible for fetching live prices from MT5 or mock
from data.data_fetcher  import fetcher
from data.mt5_connector import connector

# Database layer — all read/write operations go through the repository
from database.repository import (
    get_performance_summary,
    get_recent_signals,
    get_trade_history,
    save_account_snapshot,
    save_signal,
)

# Execution layer — risk checks and order placement
from execution.risk_manager   import risk_manager
from execution.trade_executor import TradeRequest, executor

# Strategy layer — the 40-strategy voting engine
from services.strategy_engine import engine
from strategies.base          import Signal

# ─────────────────────────────────────────────────────────────────────────────

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level state for the automated trading bot
#
# These two variables live at module level so they persist for the lifetime
# of the server process and can be read and written by any endpoint.
#
# _auto_trading_enabled — toggled by /api/bot/toggle; when False the scheduler
#                         still runs but exits immediately without evaluating
#                         any strategies
#
# _last_trade_time      — tracks when a trade was last placed per symbol;
#                         prevents the bot placing duplicate orders on the same
#                         symbol within the same 60-second window
# ─────────────────────────────────────────────────────────────────────────────

_auto_trading_enabled: bool = True
_last_trade_time: dict      = {}   # symbol (str) → Unix timestamp (float)


# ─────────────────────────────────────────────────────────────────────────────
# Automated trading loop
#
# This function is called by APScheduler every 30 seconds. It is the core of
# the bot — the part that makes trading decisions without any human input.
#
# The decision pipeline for each symbol:
#   1. Fetch 500 candles of M15 price data from the broker
#   2. Run all 40 strategies simultaneously via the strategy engine
#   3. Check confidence — only act if the winning side is above 55%
#   4. Check the 60-second cooldown to avoid duplicate orders
#   5. Run all 5 risk manager checks
#   6. Place the trade with symbol-appropriate stop/take-profit distances
# ─────────────────────────────────────────────────────────────────────────────

async def auto_trade_loop():
    """
    The automated trading bot — evaluates all symbols every 30 seconds and
    places trades when the strategy engine produces a high-confidence signal.

    This function runs entirely in the background. The dashboard reflects its
    activity through the Bot Active badge and the auto-trade toast notifications,
    both of which poll /api/bot/status and /api/positions respectively.
    """
    # Guard 1 — bot can be paused via the /api/bot/toggle endpoint
    if not _auto_trading_enabled:
        return

    # Guard 2 — no point running if there is no active broker connection
    if not connector.is_connected:
        return

    # Guard 3 — never place automated trades in demo/mock mode; real money
    # decisions should only be made against real market data
    if connector.mock_mode:
        return

    symbols = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

    for symbol in symbols:
        try:
            # Step 1 — Fetch latest 500 M15 candles for this symbol.
            # 500 bars gives all 40 strategies enough history to calculate
            # their indicators correctly (the longest lookback is ~200 bars).
            df = fetcher.get_ohlcv(symbol, "M15", 500)
            if df.empty:
                continue   # no data available for this symbol right now

            # Step 2 — Run all 40 strategies and aggregate their votes.
            # The engine returns a single AggregatedSignal with the winning
            # direction, confidence score, and individual vote counts.
            result = engine.evaluate(df, symbol)

            # Step 3 — Skip if no clear signal or confidence is too low.
            # NONE means the strategies did not reach a consensus.
            # Below 55% means the winning side is not convincing enough.
            if result.final_signal == Signal.NONE:
                continue

            if result.confidence < 0.55:
                logger.info(
                    "AUTO: %s signal for %s but confidence too low (%.0f%%) — skipping",
                    result.final_signal, symbol, result.confidence * 100
                )
                continue

            logger.info(
                "AUTO SIGNAL: %s %s — confidence %.0f%% (%d/%d votes)",
                result.final_signal, symbol,
                result.confidence * 100,
                result.buy_votes if result.final_signal == Signal.BUY else result.sell_votes,
                result.total_evaluated,
            )

            # Step 4 — Cooldown guard: skip if this symbol was traded recently.
            # Without this, the bot could place the same order multiple times
            # in consecutive scheduler cycles before the first one even fills.
            last = _last_trade_time.get(symbol, 0)
            if time.time() - last < 60:
                logger.info("AUTO: %s traded recently — skipping", symbol)
                continue

            # Update the timestamp now (before execution) so that even if
            # execution fails, we still wait before retrying this symbol
            _last_trade_time[symbol] = time.time()

            # Step 5 — Run the 5-layer risk manager before every trade.
            # This checks kill switch, daily limit, drawdown, lot size,
            # and fat finger protection.
            account    = connector.get_account_info()
            equity     = account.get("equity", 0)
            ok, reason = risk_manager.validate_trade(lot=0.01, equity=equity)

            if not ok:
                logger.info("AUTO: Trade blocked by risk manager — %s", reason)
                continue

            # Step 6 — Build and place the order.
            # Stop loss and take profit distances vary by symbol because
            # different instruments have very different price scales:
            #   XAUUSD (Gold) at ~$2400 needs much wider pip distances than
            #   EURUSD at ~$1.10. Using a flat 50 pips for Gold would give a
            #   stop loss only $0.50 away, which IC Markets rejects as invalid.
            sl_pips, tp_pips = {
                "XAUUSD": (2000, 4000),   # Gold  — $20 SL / $40 TP
                "US30":   (2000, 4000),   # Dow Jones — wide stops needed
                "USDJPY": (50,   100),    # JPY pairs — standard pip values
            }.get(symbol, (50, 100))      # default for EURUSD, GBPUSD etc.

            req = TradeRequest(
                symbol  = symbol,
                signal  = result.final_signal,
                lot     = 0.01,
                sl_pips = sl_pips,
                tp_pips = tp_pips,
            )
            trade_result = executor.execute(req)

            if trade_result.success:
                logger.info(
                    "AUTO TRADE PLACED: %s %s @ %.5f — ticket #%s",
                    result.final_signal, symbol,
                    trade_result.price, trade_result.order_id,
                )
            else:
                logger.warning(
                    "AUTO TRADE FAILED: %s %s — %s",
                    result.final_signal, symbol, trade_result.message,
                )

        except Exception as e:
            # Catch all exceptions per symbol so one failure does not stop
            # the loop from evaluating the remaining symbols
            logger.error("Auto trade loop error for %s: %s", symbol, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI lifespan
#
# The lifespan context manager runs setup code when the server starts and
# teardown code when it stops. Using lifespan (rather than @app.on_event which
# is deprecated) is the modern FastAPI approach.
#
# On startup:
#   1. Create all 8 database tables if they do not already exist.
#      CREATE TABLE IF NOT EXISTS means existing data is never touched.
#   2. Start APScheduler to run auto_trade_loop every 30 seconds.
#
# On shutdown:
#   Stop the scheduler cleanly so in-flight jobs can finish.
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic for the FastAPI application."""

    # Initialise the database — idempotent, safe to run on every startup
    from database.init_db import create_tables
    create_tables()
    logger.info("Database initialised.")

    # Start the background scheduler that drives the automated bot
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(auto_trade_loop, "interval", seconds=30, id="auto_trade")
    scheduler.start()
    logger.info("Auto trading scheduler started — running every 30 seconds.")

    yield   # server is now running and handling requests

    # Shutdown — give in-progress jobs a moment to complete
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="AlgoTrader Bot", version="2.0.0", lifespan=lifespan)

# CORS middleware allows the browser to make requests to this server even when
# running on a different port (e.g. browser on 5500, server on 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve CSS, JavaScript, and image files from the ui/static directory
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

# Jinja2 renders the HTML templates with any variables we pass in
templates = Jinja2Templates(directory="ui/templates")


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
#
# Pydantic models define the shape of data coming IN from the browser.
# FastAPI automatically validates the incoming JSON against these models and
# returns a 422 error if any required field is missing or has the wrong type.
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Fields submitted by the login form."""
    login:     int    # MT5 account number
    password:  str    # MT5 account password
    server:    str    # broker server name (e.g. ICMarketsSC-Demo)
    demo_mode: bool = False   # if True, bypass MT5 and use mock data


class TradeRequestBody(BaseModel):
    """Fields submitted when the user clicks BUY or SELL."""
    symbol:  str    # e.g. "EURUSD"
    signal:  str    # "BUY" or "SELL"
    lot:     float  # trade size in lots (0.01 = one micro lot)
    sl_pips: int    # stop loss distance in pips
    tp_pips: int    # take profit distance in pips


# ─────────────────────────────────────────────────────────────────────────────
# HTML page routes
#
# These endpoints serve the actual HTML pages when a user visits a URL.
# FastAPI passes the Request object to Jinja2 so templates can access headers,
# cookies, and other request data if needed.
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the login page at the root URL."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main trading dashboard."""
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """Serve the trade history page."""
    return templates.TemplateResponse(request, "history.html")


@app.get("/performance", response_class=HTMLResponse)
async def performance(request: Request):
    """Serve the performance analytics page."""
    return templates.TemplateResponse(request, "performance.html")


@app.get("/risk", response_class=HTMLResponse)
async def risk(request: Request):
    """Serve the risk manager page."""
    return templates.TemplateResponse(request, "risk.html")


# ─────────────────────────────────────────────────────────────────────────────
# API routes
#
# These endpoints return JSON data. They are called by the JavaScript in each
# HTML page using the fetch() API — the browser never navigates to these URLs
# directly, it just reads the JSON response and updates the page.
#
# Every endpoint that requires an active broker session checks
# connector.is_connected first and returns 401 (Unauthorized) if not connected.
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/connect")
async def connect(body: LoginRequest):
    """
    Connect to the MT5 broker or activate demo mode.

    Two paths:
      Demo mode  → connect_mock() → simulated $10,000 account, no real broker
      Real MT5   → connector.connect() → live IC Markets session

    In both cases an account snapshot is saved to the database so the
    accounts table has a record of every login.
    """
    try:
        # ── Demo mode path ────────────────────────────────────────────────────
        if body.demo_mode:
            connector.connect_mock(body.login, body.server)
            info = connector.get_account_info()

            # Save snapshot — wrapped in try/except so a DB failure never
            # prevents the user from logging in
            try:
                save_account_snapshot(
                    login=body.login,
                    server=body.server,
                    balance=info.get("balance", 0),
                    equity=info.get("equity", 0),
                    margin=info.get("margin", 0),
                    free_margin=info.get("free_margin", 0),
                    currency=info.get("currency", "USD"),
                    mock_mode=True,
                )
            except Exception as e:
                logger.warning("Could not save account snapshot (demo): %s", e)

            return {
                "success":   True,
                "mock_mode": True,
                "account":   info,
            }

        # ── Real MT5 connection path ──────────────────────────────────────────
        success = connector.connect(body.login, body.password, body.server)

        if not success:
            # This happens on Windows when MT5 is installed but not running,
            # or when credentials are wrong (connector falls back to mock)
            raise HTTPException(
                status_code=503,
                detail=(
                    "MetaTrader 5 is not running. "
                    "Please open the MT5 application first, then try again."
                ),
            )

        info = connector.get_account_info()

        # Save account snapshot — note margin_free vs free_margin difference
        # between real MT5 (uses margin_free) and mock (uses free_margin)
        try:
            save_account_snapshot(
                login=body.login,
                server=body.server,
                balance=info.get("balance", 0),
                equity=info.get("equity", 0),
                margin=info.get("margin", 0),
                free_margin=info.get("free_margin", info.get("margin_free", 0)),
                currency=info.get("currency", "USD"),
                mock_mode=connector.mock_mode,
            )
        except Exception as e:
            logger.warning("Could not save account snapshot (real): %s", e)

        return {
            "success":   True,
            "mock_mode": connector.mock_mode,
            "account":   info,
        }

    except HTTPException:
        raise   # re-raise HTTP exceptions so FastAPI handles them correctly
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/disconnect")
async def disconnect():
    """
    Disconnect from MT5 and clear the session.

    After this call, connector.is_connected becomes False and all protected
    endpoints return 401 until the user logs in again.
    """
    connector.disconnect()
    return {"success": True}


@app.get("/api/account")
async def get_account():
    """
    Return current account info — balance, equity, margin, server, login.

    Called by the dashboard every few seconds to keep the stat tiles updated.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    return connector.get_account_info()


@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    """
    Return live bid/ask price and spread for a symbol.

    Called every 5 seconds by the dashboard's price tile and watchlist.
    The data priority is: real MT5 → Alpha Vantage API → mock random walk.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    tick = fetcher.get_tick(symbol)
    if not tick:
        raise HTTPException(status_code=404, detail=f"No price for {symbol}")

    return tick


@app.get("/api/signal/{symbol}")
async def get_signal(symbol: str, timeframe: str = "M15"):
    """
    Run all 40 strategies against the latest price data and return the result.

    This is the most computationally expensive endpoint — it fetches 500 candles
    and evaluates every indicator and strategy before responding. Typically
    takes 1-3 seconds.

    The result is also saved to the database (signals table) so every evaluation
    is recorded for audit and analysis.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    try:
        df = fetcher.get_ohlcv(symbol, timeframe, 500)

        # Return a safe NONE response if no data is available rather than
        # crashing — this can happen for exotic symbols or outside market hours
        if df.empty:
            return {
                "symbol":          symbol,
                "final_signal":    "NONE",
                "confidence":      0,
                "buy_votes":       0,
                "sell_votes":      0,
                "none_votes":      0,
                "total_evaluated": 0,
                "top_strategies":  [],
                "note":            "No data available for this symbol",
            }

        result = engine.evaluate(df, symbol)

        # Persist the evaluation to the database before returning
        save_signal(
            symbol=symbol,
            timeframe=timeframe,
            final_signal=result.final_signal,
            confidence=result.confidence,
            buy_votes=result.buy_votes,
            sell_votes=result.sell_votes,
            none_votes=result.none_votes,
            total_evaluated=result.total_evaluated,
            top_strategies=[
                {"name": s.strategy, "confidence": s.confidence, "reason": s.reason}
                for s in result.top_strategies
            ],
        )

        return {
            "symbol":          symbol,
            "final_signal":    result.final_signal,
            "confidence":      round(result.confidence * 100, 1),  # 0-100% for the UI
            "buy_votes":       result.buy_votes,
            "sell_votes":      result.sell_votes,
            "none_votes":      result.none_votes,
            "total_evaluated": result.total_evaluated,
            "top_strategies":  [
                {
                    "name":       s.strategy,
                    "confidence": round(s.confidence * 100, 1),
                    "reason":     s.reason,
                }
                for s in result.top_strategies
            ],
        }

    except Exception as e:
        logger.error("Signal error for %s: %s", symbol, str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, timeframe: str = "M15", count: int = 100):
    """
    Return OHLCV candlestick data for the price chart on the dashboard.

    The timeframe parameter controls candle size: M5 = 5-minute candles,
    M15 = 15-minute, H1 = 1-hour, H4 = 4-hour. Each timeframe button on
    the chart calls this endpoint with a different timeframe value.

    Time strings are trimmed to YYYY-MM-DD HH:MM format (16 characters)
    to keep the chart labels concise.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    df = fetcher.get_ohlcv(symbol, timeframe, count)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")

    # Reset index so 'time' becomes a regular column regardless of whether
    # the DataFrame uses a DatetimeIndex or a plain integer index
    df       = df.reset_index()
    time_col = "time" if "time" in df.columns else df.columns[0]

    return {
        "symbol": symbol,
        "data": [
            {
                "time":   str(row[time_col])[:16],        # trim seconds
                "open":   round(float(row["open"]),  5),
                "high":   round(float(row["high"]),  5),
                "low":    round(float(row["low"]),   5),
                "close":  round(float(row["close"]), 5),
                "volume": int(row["tick_volume"]),
            }
            for _, row in df.iterrows()
        ],
    }


@app.post("/api/trade")
async def place_trade(body: TradeRequestBody):
    """
    Place a trade after running all 5 risk checks.

    Called when the user clicks BUY or SELL on the dashboard.
    The sequence is:
      1. Validate the trade against the risk manager (5 checks)
      2. Build a TradeRequest and pass it to the executor
      3. The executor sends the order to MT5 and saves it to the database
      4. Return the result (success/fail, order ID, price, SL, TP)

    Returns success: False (not a 4xx error) when the risk manager blocks
    the trade, so the frontend can display the reason without treating it
    as a network failure.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    # Risk check — runs before any order is constructed
    account        = connector.get_account_info()
    equity         = account.get("equity", 0)
    ok, reason     = risk_manager.validate_trade(lot=body.lot, equity=equity)

    if not ok:
        # Return 200 with success: False so the dashboard shows the reason
        return {"success": False, "message": reason}

    try:
        signal = Signal.BUY if body.signal == "BUY" else Signal.SELL
        req    = TradeRequest(
            symbol  = body.symbol,
            signal  = signal,
            lot     = body.lot,
            sl_pips = body.sl_pips,
            tp_pips = body.tp_pips,
        )
        result = executor.execute(req)

        return {
            "success":  result.success,
            "order_id": result.order_id,
            "price":    result.price,
            "sl":       result.sl,
            "tp":       result.tp,
            "message":  result.message,
            "state":    result.state,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions")
async def get_positions():
    """
    Return all currently open positions.

    Called every 3 seconds by the dashboard's open positions table and by
    the checkNewPositions() function that fires auto-trade notifications.
    In mock mode, returns the in-memory list of simulated positions.
    In real mode, queries MT5 for live position data.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    return {"positions": connector.get_open_positions()}


@app.get("/api/risk/status")
async def get_risk_status():
    """
    Return the current state of the risk manager.

    Drives the two gauges on the Risk Manager page:
      daily_trades / max_trades   → trade count gauge
      drawdown_pct / max_drawdown → drawdown gauge

    Also returns kill_switch (True/False) which controls the shield icon
    and the Halt/Resume button states.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    account = connector.get_account_info()
    equity  = account.get("equity", 10000)

    return {
        "daily_trades": risk_manager.daily_trade_count(),
        "max_trades":   settings.MAX_TRADES_PER_DAY,
        "drawdown_pct": round(risk_manager.current_drawdown_pct(equity), 2),
        "max_drawdown": settings.MAX_DRAWDOWN_PCT,
        "kill_switch":  risk_manager._kill_switch,
    }


@app.post("/api/risk/killswitch")
async def toggle_kill_switch(activate: bool = True):
    """
    Activate or deactivate the emergency kill switch.

    When activate=True:  all new trades (manual and automated) are blocked
    When activate=False: trading resumes normally

    The dashboard's bot status badge updates within 5 seconds of this call
    through the updateBotStatus() polling function.
    """
    if activate:
        risk_manager.activate_kill_switch()
    else:
        risk_manager.deactivate_kill_switch()

    return {"kill_switch": risk_manager._kill_switch}


@app.get("/api/symbols")
async def get_symbols():
    """Return the list of available trading symbols from the connector."""
    return {"symbols": connector.get_symbols()}


@app.get("/api/status")
async def get_status():
    """
    Server health check — returns running state, connection status, and mode.

    Called every 8 seconds by the dashboard to keep the connection badge
    in the sidebar up to date. Also used by integration tests to confirm
    the server started successfully.
    """
    return {
        "server":    "running",
        "connected": connector.is_connected,
        "mock_mode": connector.mock_mode,
    }


# ── Database read endpoints ───────────────────────────────────────────────────
# These endpoints power the Trade History, Performance, and Signal Log pages.
# They read directly from the SQLite database so data persists across restarts.

@app.get("/api/history")
async def api_history(symbol: str = None, limit: int = 50):
    """
    Return trade history from the database.

    The optional symbol parameter filters to a specific trading pair.
    The history page uses this endpoint instead of /api/positions so that
    closed trades (which are no longer in MT5's active position list) are
    still visible.
    """
    return {"trades": get_trade_history(symbol=symbol, limit=limit)}


@app.get("/api/performance/summary")
async def api_performance():
    """Return daily performance rollup from the database (last 30 days)."""
    return {"performance": get_performance_summary(days=30)}


@app.get("/api/signals/log")
async def api_signals_log(symbol: str = None, limit: int = 20):
    """
    Return recent signal evaluations from the database.

    Every call to /api/signal/{symbol} saves a row to the signals table.
    This endpoint reads those rows back so the signal history can be reviewed.
    """
    return {"signals": get_recent_signals(symbol=symbol, limit=limit)}


# ── Bot control endpoints ─────────────────────────────────────────────────────

@app.post("/api/bot/toggle")
async def toggle_bot(enabled: bool = True):
    """
    Enable or disable the automated trading bot without stopping the server.

    The scheduler continues running on its 30-second interval, but
    auto_trade_loop() exits immediately when _auto_trading_enabled is False,
    so no strategy evaluations or trades are made.
    """
    global _auto_trading_enabled
    _auto_trading_enabled = enabled
    logger.info("Auto trading %s", "enabled" if enabled else "disabled")
    return {"auto_trading": _auto_trading_enabled}


@app.get("/api/bot/status")
async def bot_status():
    """
    Return the current state of the automated trading bot.

    will_trade is True only when all three conditions are met:
      - The bot is enabled (_auto_trading_enabled is True)
      - There is an active broker connection
      - The session is not in mock/demo mode

    The dashboard's bot status badge reads will_trade to decide which colour
    and label to display (Active, Halted, or Off/Demo).
    """
    return {
        "auto_trading": _auto_trading_enabled,
        "connected":    connector.is_connected,
        "mock_mode":    connector.mock_mode,
        "will_trade":   (
            _auto_trading_enabled
            and connector.is_connected
            and not connector.mock_mode
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
#
# This block only runs when the file is executed directly with:
#   python main.py
#
# When using uvicorn (the recommended way), this block is not reached.
# uvicorn handles the server lifecycle itself and calls the lifespan function
# on startup.
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )