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
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import logging
import os
from contextlib import asynccontextmanager

# ── Import your teammate's modules ───────────────────────────────────────────
from data.mt5_connector       import connector
from data.data_fetcher        import fetcher
from services.strategy_engine import engine
from execution.risk_manager   import risk_manager
from execution.trade_executor import executor, TradeRequest
from strategies.base          import Signal
from config.settings          import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="AlgoTrader Bot", version="2.0.0")

# Allow the browser to talk to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (CSS, JS) and HTML templates
app.mount("/static", StaticFiles(directory="ui/static"), name="static")
templates = Jinja2Templates(directory="ui/templates")


# ── Request/Response models ───────────────────────────────────────────────────
# These define the shape of data coming IN from the browser

class LoginRequest(BaseModel):
    login:    int
    password: str
    server:   str

class TradeRequestBody(BaseModel):
    symbol:   str
    signal:   str        # "BUY" or "SELL"
    lot:      float
    sl_pips:  int
    tp_pips:  int


# ── HTML Page Routes ──────────────────────────────────────────────────────────
# These serve the actual HTML pages when you visit a URL in your browser

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the login page at http://localhost:8000"""
    return templates.TemplateResponse(request, "login.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main trading dashboard"""
    return templates.TemplateResponse(request, "dashboard.html")

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """Serve the trade history page"""
    return templates.TemplateResponse(request, "history.html")

@app.get("/performance", response_class=HTMLResponse)
async def performance(request: Request):
    """Serve the performance metrics page"""
    return templates.TemplateResponse(request, "performance.html")

@app.get("/risk", response_class=HTMLResponse)
async def risk(request: Request):
    """Serve the risk management page"""
    return templates.TemplateResponse(request, "risk.html")

# ── API Routes ────────────────────────────────────────────────────────────────
# These return JSON data — called by JavaScript in the HTML pages

@app.post("/api/connect")
async def connect(body: LoginRequest):
    """
    Connect to MT5 broker.
    Called when user clicks Connect on the login page.
    """
    try:
        success = connector.connect(body.login, body.password, body.server)
        if not success:
            raise HTTPException(status_code=401, detail="Connection failed. Check credentials.")
        info = connector.get_account_info()
        return {
            "success":    True,
            "mock_mode":  connector.mock_mode,
            "account":    info,
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
    Called by the dashboard when user selects a symbol.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    try:
        df     = fetcher.get_ohlcv(symbol, timeframe, 500)
        result = engine.evaluate(df, symbol)
        return {
            "symbol":         symbol,
            "final_signal":   result.final_signal,
            "confidence":     round(result.confidence * 100, 1),
            "buy_votes":      result.buy_votes,
            "sell_votes":     result.sell_votes,
            "none_votes":     result.none_votes,
            "total_evaluated": result.total_evaluated,
            "top_strategies": [
                {
                    "name":       s.strategy,
                    "confidence": round(s.confidence * 100, 1),
                    "reason":     s.reason,
                }
                for s in result.top_strategies
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, timeframe: str = "M15", count: int = 100):
    """Return OHLCV candlestick data for charting."""
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")
    
    df = fetcher.get_ohlcv(symbol, timeframe, count)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")
    
    # Reset index to get time as a column regardless of DataFrame format
    df = df.reset_index()
    
    # Handle both 'time' and DatetimeIndex column names
    time_col = 'time' if 'time' in df.columns else df.columns[0]
    
    return {
        "symbol": symbol,
        "data": [
            {
                "time":   str(row[time_col])[:16],  # trim to YYYY-MM-DD HH:MM
                "open":   round(float(row["open"]),  5),
                "high":   round(float(row["high"]),  5),
                "low":    round(float(row["low"]),   5),
                "close":  round(float(row["close"]), 5),
                "volume": int(row["tick_volume"]),
            }
            for _, row in df.iterrows()
        ]
    }


@app.post("/api/trade")
async def place_trade(body: TradeRequestBody):
    """
    Place a trade after passing all risk checks.
    Called when user clicks BUY or SELL on the dashboard.
    """
    if not connector.is_connected:
        raise HTTPException(status_code=401, detail="Not connected")

    # Step 1 — Risk check
    account  = connector.get_account_info()
    equity   = account.get("equity", 0)
    ok, reason = risk_manager.validate_trade(lot=body.lot, equity=equity)

    if not ok:
        return {"success": False, "message": reason}

    # Step 2 — Build and execute the trade request
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
        "daily_trades":    risk_manager.daily_trade_count(),
        "max_trades":      settings.MAX_TRADES_PER_DAY,
        "drawdown_pct":    round(risk_manager.current_drawdown_pct(equity), 2),
        "max_drawdown":    settings.MAX_DRAWDOWN_PCT,
        "kill_switch":     risk_manager._kill_switch,
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

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )    