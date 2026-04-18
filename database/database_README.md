# 🗄️ Database Layer — AlgoTradingBot

**Module:** `database/`  
**Owner:** Database layer (CST4160 Group Project)  
**Tech:** SQLAlchemy ORM · SQLite (default) · PostgreSQL (optional)

---

## Overview

This module handles all persistent storage for the bot.  
Every trade, signal, risk event and account snapshot is automatically saved here — no manual intervention needed once the bot is running.

---

## Files

| File | Purpose |
|------|---------|
| `models.py` | SQLAlchemy table definitions (8 tables) |
| `connection.py` | Database engine, session factory, health check |
| `repository.py` | All read/write functions — the only file other modules import from |
| `init_db.py` | CLI script to create tables and optionally seed sample data |
| `__init__.py` | Package exports |

---

## Setup (run once)

From the **project root** in your terminal:

```bash
# Create all tables
python -m database.init_db

# Create tables AND insert sample data (good for UI testing)
python -m database.init_db --seed
```

This creates `algobot.db` in the project root automatically. No additional database software needed.

> ⚠️ `algobot.db` is in `.gitignore` — do not commit it to GitHub.

---

## Tables

### `accounts`
Snapshots of the MT5 account captured on connect and periodically during a session.  
Stores balance, equity, margin, currency and whether mock mode is active.

### `trades`
One row per executed trade. Recorded automatically when a BUY or SELL order is filled.  
Stores symbol, direction, lot size, entry price, stop loss, take profit and MT5 order/deal IDs.

### `trade_outcomes`
Closing data for a trade — exit price, realised P&L, close reason (SL / TP / MANUAL) and duration.  
Linked 1-to-1 with `trades`. Null until the position is closed.

### `signals`
One row per call to the strategy engine. Records the aggregated result — final signal, confidence score and the full vote breakdown (buy / sell / none counts).

### `strategy_votes`
Per-strategy detail inside each signal evaluation. Shows which individual strategies voted BUY/SELL and at what confidence. Useful for auditing why a trade was taken.

### `risk_events`
Audit log for every risk-check failure and kill-switch toggle.  
Event types include: `KILL_SWITCH_ON`, `KILL_SWITCH_OFF`, `DAILY_LIMIT_HIT`, `DRAWDOWN_BREACH`, `LOT_REJECTED`.

### `price_snapshots`
Periodic bid/ask tick records captured by the dashboard price poller.  
Used for auditing execution quality and spread analysis.

### `performance_daily`
Rolled-up daily statistics — total trades, win rate, total P&L, best/worst trade.  
Updated automatically when `/api/performance/summary` is called.

---

## API Endpoints

These are served by `main.py` and pull data from this module:

| Endpoint | Returns |
|----------|---------|
| `GET /api/history` | Recent trades with outcomes |
| `GET /api/performance/summary` | Last 30 days of daily stats |
| `GET /api/signals/log` | Recent strategy engine evaluations |

---

## Using PostgreSQL (optional)

SQLite works fine for development. To switch to PostgreSQL, add this to a `.env` file in the project root:

```
DATABASE_URL=postgresql+psycopg2://username:password@localhost/algobot
```

No code changes needed — the connection module reads this automatically.

---

## For Teammates

You do **not** need to touch this module to use it.  
Just call the relevant function from `repository.py`:

```python
from database.repository import get_trade_history, get_performance_summary

# Get last 50 trades
trades = get_trade_history(limit=50)

# Get last 30 days of performance
stats = get_performance_summary(days=30)
```

If you run into any issues, run the health check:

```python
from database.connection import check_connection
print(check_connection())  # True = all good
```
