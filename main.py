"""
main.py
───────
FastAPI server — the bridge between the HTML frontend and the Python backend.

How it works:
  1. The HTML pages open in your browser
  2. When you click a button or load a page, the browser sends an HTTP request here
  3. FastAPI receives the request, calls the correct Python module
  4. Returns JSON data back to the browser
  5. The JavaScript in the HTML page reads that JSON and updates what you see

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

from config.settings import get_settings
from data.data_fetcher import fetcher
from data.mt5_connector import connector
from database.repository import (
    get_performance_summary,
    get_recent_signals,
    get_trade_history,
    save_account_snapshot,
    save_signal,
)
from execution.risk_manager import risk_manager
from execution.trade_executor import TradeRequest, executor
from services.strategy_engine import engine
from strategies.base import Signal

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Auto trading state ────────────────────────────────────────────────────────
_auto_trading_enabled: bool = True
_last_trade_time: dict      = {}  # symbol → timestamp of last auto trade

# ── Automated trading loop ────────────────────────────────────────────────────

async def auto_trade_loop():
    """
    Runs every 60 seconds automatically.
    Analyses the market using all 40 strategies and places a trade
    if the signal is strong enough and passes all risk checks.
    No human click required — this is the bot behaviour.
    """
    # Only run if connected to real MT5 — never auto trade in mock/demo mode
    if not _auto_trading_enabled:
        return
    if not connector.is_connected:
        return
    if connector.mock_mode:
        return

    symbols = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

    for symbol in symbols:
        try:
            # Step 1 — Get latest price data
            df = fetcher.get_ohlcv(symbol, "M15", 500)
            if df.empty:
                continue

            # Step 2 — Run all 40 strategies
            result = engine.evaluate(df, symbol)

            # Step 3 — Only act on strong signals
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
                result.total_evaluated
            )

            # Guard — don't trade same symbol more than once per minute
            last = _last_trade_time.get(symbol, 0)
            if time.time() - last < 60:
                logger.info("AUTO: %s traded recently — skipping", symbol)
                continue
            _last_trade_time[symbol] = time.time()

            # Step 4 — Run risk checks
            account = connector.get_account_info()
            equity  = account.get("equity", 0)
            ok, reason = risk_manager.validate_trade(lot=0.01, equity=equity)

            if not ok:
                logger.info("AUTO: Trade blocked by risk manager — %s", reason)
                continue

            # Step 5 — Place the trade
            sl_pips, tp_pips = {
                "XAUUSD": (2000, 4000),   # Gold — $20 SL, $40 TP
                "US30":   (2000, 4000),   # Dow Jones — wider stops
                "USDJPY": (50,   100),    # JPY pairs — standard
            }.get(symbol, (50, 100))

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
                    trade_result.price, trade_result.order_id
                )
            else:
                logger.warning(
                    "AUTO TRADE FAILED: %s %s — %s",
                    result.final_signal, symbol, trade_result.message
                )

        except Exception as e:
            logger.error("Auto trade loop error for %s: %s", symbol, str(e))

# ── FastAPI lifespan — runs on startup ────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-initialise database tables on startup
    from database.init_db import create_tables
    create_tables()
    logger.info("Database initialised.")

    # Start the automated trading scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(auto_trade_loop, 'interval', seconds=30, id='auto_trade')
    scheduler.start()
    logger.info("Auto trading scheduler started — running every 60 seconds.")

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="AlgoTrader Bot", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="ui/static"), name="static")
templates = Jinja2Templates(directory="ui/templates")


# ── Request / Response models ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    login:     int
    password:  str
    server:    str
    demo_mode: bool = False


class TradeRequestBody(BaseModel):
    symbol:  str
    signal:  str    # "BUY" or "SELL"
    lot:     float
    sl_pips: int
    tp_pips: int


# ── HTML page routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Login page."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main trading dashboard."""
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """Trade history page."""
    return templates.TemplateResponse(request, "history.html")


@app.get("/performance", response_class=HTMLResponse)
async def performance(request: Request):
    """Performance analytics page."""
    return templates.TemplateResponse(request, "performance.html")


@app.get("/risk", response_class=HTMLResponse)
async def risk(request: Request):
    """Risk manager page."""
    return templates.TemplateResponse(request, "risk.html")


# ── API routes ────────────────────────────────────────────────────────────────

@app.post("/api/connect")
async def connect(body: LoginRequest):
    """
    Connect to MT5 broker or demo mode.
    Saves an account snapshot to the database on every successful login.
    """
    try:
        # ── Demo mode — bypass MT5 entirely ──────────────────────────────────
        if body.demo_mode:
            connector.connect_mock(body.login, body.server)
            info = connector.get_account_info()

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

        # ── Real MT5 connection attempt ───────────────────────────────────────
        success = connector.connect(body.login, body.password, body.server)

        if not success:
            raise HTTPException(
                status_code=503,
                detail=(
                    "MetaTrader 5 is not running. "
                    "Please open the MT5 application first, then try again."
                ),
            )

        info = connector.get_account_info()

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
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/disconnect")
async def disconnect():
    """Disconnect from MT5."""
    connector.disconnect()
    return {"success": True}


@app.get("/api/account")
async def get_account():
    """Return current account info — balance, equity, margin."""
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    return connector.get_account_info()


@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    """
    Return live bid/ask price for a symbol.
    Called every few seconds by the dashboard to update the price display.
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
    Run all 40 strategies and return the aggregated signal.
    Saves the result to the database.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    try:
        df = fetcher.get_ohlcv(symbol, timeframe, 500)

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
            "confidence":      round(result.confidence * 100, 1),
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
    """Return OHLCV candlestick data for charting."""
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    df = fetcher.get_ohlcv(symbol, timeframe, count)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")

    df = df.reset_index()
    time_col = "time" if "time" in df.columns else df.columns[0]

    return {
        "symbol": symbol,
        "data": [
            {
                "time":   str(row[time_col])[:16],
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
    Place a trade after passing all risk checks.
    Called when user clicks BUY or SELL on the dashboard.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    account        = connector.get_account_info()
    equity         = account.get("equity", 0)
    ok, reason     = risk_manager.validate_trade(lot=body.lot, equity=equity)

    if not ok:
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
    """Return all currently open positions."""
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    return {"positions": connector.get_open_positions()}


@app.get("/api/risk/status")
async def get_risk_status():
    """Return current risk manager status."""
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
    """Activate or deactivate the kill switch."""
    if activate:
        risk_manager.activate_kill_switch()
    else:
        risk_manager.deactivate_kill_switch()
    return {"kill_switch": risk_manager._kill_switch}


@app.get("/api/symbols")
async def get_symbols():
    """Return available trading symbols."""
    return {"symbols": connector.get_symbols()}


@app.get("/api/status")
async def get_status():
    """Health check — is the server running and connected?"""
    return {
        "server":    "running",
        "connected": connector.is_connected,
        "mock_mode": connector.mock_mode,
    }


@app.get("/api/history")
async def api_history(symbol: str = None, limit: int = 50):
    """Return trade history from database."""
    return {"trades": get_trade_history(symbol=symbol, limit=limit)}


@app.get("/api/performance/summary")
async def api_performance():
    """Return daily performance summary from database."""
    return {"performance": get_performance_summary(days=30)}


@app.get("/api/signals/log")
async def api_signals_log(symbol: str = None, limit: int = 20):
    """Return recent signal evaluations from database."""
    return {"signals": get_recent_signals(symbol=symbol, limit=limit)}

# ── Bot control endpoints ─────────────────────────────────────────────────────

@app.post("/api/bot/toggle")
async def toggle_bot(enabled: bool = True):
    """Enable or disable the automated trading bot."""
    global _auto_trading_enabled
    _auto_trading_enabled = enabled
    logger.info("Auto trading %s", "enabled" if enabled else "disabled")
    return {"auto_trading": _auto_trading_enabled}


@app.get("/api/bot/status")
async def bot_status():
    """Return whether the auto trading bot is currently active."""
    return {
        "auto_trading": _auto_trading_enabled,
        "connected":    connector.is_connected,
        "mock_mode":    connector.mock_mode,
        "will_trade":   _auto_trading_enabled and connector.is_connected and not connector.mock_mode,
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )