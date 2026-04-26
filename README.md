# ⚡ AlgoTrader Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?style=flat-square&logo=sqlite&logoColor=white)
![MT5](https://img.shields.io/badge/MetaTrader5-Compatible-1565C0?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-134%20passing-22c55e?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-22d3a5?style=flat-square)

**A professional algorithmic trading bot powered by a 40-strategy voting engine,
real-time market data, persistent database storage, and a full web dashboard.**

_Built for the CST4160 FinTech Coursework — Middlesex University Dubai_

[Features](#-features) · [Architecture](#-architecture) · [Getting Started](#-getting-started) · [Usage](#-usage) · [Testing](#-testing) · [Database](#-database) · [Project Structure](#-project-structure)

</div>

---

## 📌 Overview

AlgoBot is a Python-based algorithmic trading system that connects to live financial data sources via multiple API integrations and executes trades automatically using real-time technical analysis. The architecture separates data ingestion, signal generation, risk management, and execution into independent, testable modules — reflecting professional quantitative trading system design.

---

### 🔄 How It Works

The bot runs on a pre-determined time intervals via APScheduler — fetching market data, running all 40 strategies, aggregating votes, validating through a 5-layer risk engine, and placing or skipping a trade. No human input required.

---

### 📡 Three-Tier Price Sourcing

**Tier 1 — MetaTrader5 API (Primary)**
Communicates locally with the MT5 desktop application using credential-based authentication (login, password, server name). Delivers real-time prices, OHLCV data, and live order execution.

**Tier 2 — Alpha Vantage REST API (Fallback)**
Activates automatically if MT5 is unavailable. Sends an authenticated HTTP GET request using an API key stored in `.env`, receives a JSON price response, and feeds it into the same pipeline.

**Tier 3 — Synthetic Mock Prices (Final Fallback)**
Generates realistic prices internally using a seeded random walk formula. The entire system runs identically — no external dependency needed.

---

### 🧠 40-Strategy Consensus Engine

**20 buy strategies (B01–B20)** and **20 sell strategies (S01–S20)** run simultaneously, each returning a **BUY, SELL, or NONE** vote with a confidence score. Strategies span four categories:

- **Momentum** — MACD, EMA, Golden Cross, ADX, Higher Highs, Volume Breakout
- **Oscillator** — RSI, Stochastic, VWAP, Bollinger, CCI, RSI Divergence
- **Pattern** — Hammer, Engulfing, Morning/Evening Star, Inside Bar, Squeeze
- **Risk Exit** — Stop Loss (2%), Trailing Stop (1.5%), Take Profit (3%)

A signal is generated only when **≥3 strategies agree** at **≥60% average confidence**. No single strategy can trigger a trade.

---

### 🛡️ 5-Layer Risk Engine

Every signal passes five sequential checks before reaching the broker — first failure blocks the trade:

1. **Kill Switch** — emergency halt from dashboard
2. **Daily Limit** — maximum 20 trades per day
3. **Drawdown Guard** — stops trading if account falls 5% below peak
4. **Lot Validation** — trade size must be between 0.01 and 1.0 lots
5. **Fat Finger** — blocks orders disproportionately large relative to equity

Position sizing formula: **Lot = (Equity × 1%) / (SL Pips × Pip Value)**

---

### 🧪 Unit Testing

Tests in `tests/` cover strategy logic, indicator calculations, risk checks, and mock connector behaviour using Python's `unittest` framework — all runnable without a live broker connection.

---

### 🗄️ Persistent Storage

All trades and events stored in **SQLite via SQLAlchemy ORM**. Each record includes symbol, direction, lot size, entry, SL, TP, order ID, and timestamp. Migrating to PostgreSQL requires only a `DATABASE_URL` change — production-ready by design.

---

### 🖥️ Demo Mode

When MT5 is unavailable, mock mode activates automatically — synthetic prices, simulated execution, and a virtual $10,000 account. All features work identically. Fully demonstrable on any OS without a broker account.

## ✨ Features

| Feature                      | Description                                                                                            |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| 🧠 **40-Strategy Engine**    | RSI, MACD, EMA, Bollinger Bands, candlestick patterns, volume breakouts and more                       |
| 🗳️ **Voting System**         | Trades only execute when multiple strategies agree — reduces false signals                             |
| 🤖 **Automated Bot**         | Scheduler runs every 30 seconds, evaluates all symbols and places trades automatically                 |
| 🛡️ **Risk Management**       | 5-layer protection: kill switch, daily limits, drawdown checks, lot size guards, fat-finger prevention |
| 📊 **Live Dashboard**        | Real-time prices, signal display, candlestick chart, open positions, auto-trade notifications          |
| 🗄️ **Persistent Database**   | SQLite with 8 tables — trades, signals, accounts, risk events survive server restarts                  |
| 📜 **Trade History**         | Full record of all placed orders with symbol and type filters                                          |
| 📈 **Performance Analytics** | Session P&L, signal distribution charts, strategy breakdown                                            |
| 📖 **User Onboarding Guide** | Built-in step-by-step tour with spotlight highlighting and ? tooltips on every card                    |
| 🔌 **Demo Mode**             | Runs on any OS without MT5 installed — fully simulated environment                                     |
| ⚡ **FastAPI Backend**       | Clean REST API connecting the HTML frontend to the Python trading engine                               |

---

## 🏗️ Architecture

```
       │   Broker / Exchange Feeds    │
                         │  (WebSocket / FIX / Stream)  │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   Market Data Connector      │
                         │ - auth                       │
                         │ - subscribe symbols          │
                         │ - heartbeat                  │
                         │ - reconnect                  │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   Parser / Decoder           │
                         │ - decode raw feed            │
                         │ - parse trade / bid / ask    │
                         │ - parse order book           │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   Normalizer                 │
                         │ - map to internal schema     │
                         │ - symbol mapping             │
                         │ - field standardization      │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   Timestamp / QA Layer       │
                         │ - exchange ts                │
                         │ - receive ts                 │
                         │ - duplicate check            │
                         │ - stale feed detection       │
                         │ - sequence / gap detection   │
                         └──────────────┬───────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
      ┌──────────────────────────────┐       ┌──────────────────────────────┐
      │  Real-Time Market Cache      │       │ Historical Tick Recorder     │
      │ - latest LTP                 │       │ - raw ticks                  │
      │ - best bid/ask               │       │ - normalized events          │
      │ - latest book snapshot       │       │ - replay store               │
      └──────────────┬───────────────┘       └──────────────────────────────┘
                     │
                     ▼
      ┌─────────────────────────────────────────────────────┐
      │ Feature Engine / Signal Prep                       │
      │ - rolling stats                                    │
      │ - indicators                                       │
      │ - order book features                              │
      │ - spreads / volatility / momentum                  │
      └──────────────────────┬──────────────────────────────┘
                             │
                             ▼
      ┌─────────────────────────────────────────────────────┐
      │ Strategy Engine                                     │
      │ - alpha logic                                       │
      │ - rules / ML model                                  │
      │ - buy/sell/hold signal                              │
      │ - target qty / price / urgency                      │
      └──────────────────────┬──────────────────────────────┘
                             │
                             ▼
      ┌─────────────────────────────────────────────────────┐
      │ Pre-Trade Risk Engine                               │
      │ - max order size                                    │
      │ - max position                                      │
      │ - exposure checks                                   │
      │ - daily loss limits                                 │
      │ - fat-finger checks                                 │
      │ - kill switch                                       │
      └──────────────────────┬──────────────────────────────┘
                             │
                             ▼
      ┌─────────────────────────────────────────────────────┐
      │ OMS (Order Management System)                       │
      │ - create order                                      │
      │ - maintain order state                              │
      │ - amend / cancel                                    │
      │ - track partial fills / rejections                  │
      └──────────────────────┬──────────────────────────────┘
                             │
                             ▼
      ┌─────────────────────────────────────────────────────┐
      │ EMS / Execution Engine                              │
      │ - route to broker                                   │
      │ - TWAP/VWAP/iceberg logic                           │
      │ - retry / failover                                  │
      │ - smart routing                                     │
      └──────────────────────┬──────────────────────────────┘
                             │
                             ▼
               ┌────────────────────────────────────┐
               │ Broker Order API / FIX Gateway     │
               └────────────────┬───────────────────┘
                                │
                                ▼
                         ┌───────────────┐
                         │ Exchange      │
                         └──────┬────────┘
                                │ fills / rejects / cancels
                                ▼
      ┌─────────────────────────────────────────────────────┐
      │ Execution Report Handler                            │
      │ - fill events                                       │
      │ - rejection events                                  │
      │ - cancel/replace confirmation                       │
      └──────────────────────┬──────────────────────────────┘
                             │
              ┌──────────────┼──────────────┬──────────────┐
              ▼              ▼              ▼              ▼
┌────────────────────┐ ┌────────────────┐ ┌────────────────────┐ ┌────────────────────┐
│ Position Service   │ │ PnL Engine     │ │ Risk Dashboard     │ │ Monitoring / Alerts│
│ - positions        │ │ - realized PnL │ │ - exposure         │ │ - disconnects      │
│ - avg cost         │ │ - unrealized   │ │ - limits           │ │ - latency          │
│ - cash             │ │ - fees/slippage│ │ - breaches         │ │ - stale feed       │
└────────────────────┘ └────────────────┘ └────────────────────┘ └────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- Python **3.11** or higher
- Git

Check your Python version:

```bash
python --version
```

### Installation

**1. Clone the repository**

```bash
git clone https://github.com/extrarida/AlgoTradingBot.git
cd AlgoTradingBot
```

**2. Create a virtual environment**

> ⚠️ Never commit the `venv/` folder — it is in `.gitignore` and contains machine-specific paths. Each teammate must create their own local virtual environment.

```bash
# Mac / Linux
python -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

> 💡 On Windows, also install the MT5 package for real broker connectivity:
>
> ```bash
> pip install MetaTrader5
> ```
>
> This is Windows-only and intentionally excluded from `requirements.txt` so Mac/Linux users are not affected.

**4. Start the server**

```bash
uvicorn main:app --reload --port 8000
```

The database initialises automatically on first startup — no manual setup required.

**5. Open in your browser**

```
http://localhost:8000
```

> 💡 The app starts in **Demo Mode** automatically — no MT5 account needed. Tick the Demo Mode checkbox on the login page to connect instantly.

---

## 🖥️ Usage

### Logging In

On the login page you have two options:

**Demo Mode (any machine)**
Tick the **Demo Mode** checkbox and click Connect. No credentials are validated. The app connects to a simulated account with $10,000 balance. Works on Mac, Linux, and Windows.

**Real MT5 (Windows only)**
Enter your IC Markets or other broker credentials, leave Demo Mode unchecked, and click Connect. MetaTrader 5 must be open and running with Algo Trading enabled (green button in the MT5 toolbar).

| Field          | Example (Demo) | Example (Real)          |
| -------------- | -------------- | ----------------------- |
| Account Number | `12345678`     | Your MT5 account number |
| Password       | `anything`     | Your MT5 password       |
| Broker Server  | `MockBroker`   | `ICMarketsSC-Demo`      |

---

### Dashboard

The main trading interface. From here you can:

- **View live prices** — updates every 5 seconds with colour flash on change
- **Monitor all 5 symbols** — watchlist sidebar, click any to switch the dashboard
- **Get strategy signals** — click ↻ Refresh to run all 40 strategies simultaneously
- **Read the signal breakdown** — vote counts, confidence %, top strategies, indicator chips
- **View the price chart** — switch between M5, M15, H1, H4 timeframes
- **Place trades manually** — set lot size, stop loss, take profit, then click BUY or SELL
- **Watch the bot trade** — 🤖 AUTO notifications appear when the scheduler places orders
- **Monitor open positions** — live floating P&L updated every 3 seconds

---

### Automated Trading Bot

When connected to real MT5, the bot runs automatically every 30 seconds:

1. Evaluates all 40 strategies across EURUSD, GBPUSD, XAUUSD, USDJPY
2. Places a trade only when confidence exceeds 55%
3. Enforces a 60-second cooldown per symbol to prevent duplicate orders
4. Passes all 5 risk checks before any order is sent
5. Displays a toast notification on the dashboard for each auto trade

The bot status badge in the top bar shows **🤖 Bot Active**, **⛔ Bot Halted**, or **⏸ Bot Off (Demo)**.

---

### Other Pages

| Page          | URL            | What it shows                                             |
| ------------- | -------------- | --------------------------------------------------------- |
| Trade History | `/history`     | All orders from the database with symbol/type filters     |
| Performance   | `/performance` | Signal distribution chart, P&L bar chart, account metrics |
| Risk Manager  | `/risk`        | Risk gauges, pre-trade check results, kill switch         |

---

### User Onboarding Guide

Every page includes a built-in guide accessible at any time:

- **First visit** — a welcome modal explains the application in plain English
- **Step-by-step tour** — highlights each card individually with a spotlight effect and step counter (e.g. 3 of 15)
- **? tooltips** — hover any card's question mark for a quick explanation without launching the full tour
- **App Guide button** — in the sidebar, relaunches the full tour at any time

The guide is written for users with no trading background.

---

### Using the Kill Switch

Navigate to the **Risk Manager** page and click **⛔ Halt Trading**. This immediately blocks all new trade orders — both manual and automated — regardless of signal strength. The dashboard badge switches to **⛔ Bot Halted**. Click **✓ Resume** to re-enable trading.

---

## 🔌 Connecting Real MT5 (Windows Only)

The MetaTrader 5 Python package only works on Windows. To connect a real account:

1. Download and install [MetaTrader 5](https://www.metatrader5.com/en/download) from your broker
2. Open the MT5 application and log into your account
3. Click **Algo Trading** in the MT5 toolbar — it must turn **green**
4. Start the AlgoTrader server — it detects MT5 automatically and uses real data

> ⚠️ The app falls back to Demo Mode if MT5 is installed but not running, or if credentials are incorrect.

---

## 🧪 Testing

The project includes **134 automated tests** covering every layer of the application.

**Run all tests:**

```bash
pytest tests/ -v
```

**Run a specific test file:**

```bash
pytest tests/test_indicators.py -v
pytest tests/test_risk_manager.py -v
pytest tests/test_strategies.py -v
pytest tests/test_strategy_engine.py -v
pytest tests/test_database.py -v
pytest tests/test_integration.py -v
```

**Expected output:**

```
134 passed in ~3s
```

### Test Coverage

| Test File                 | Tests | What it covers                                                    |
| ------------------------- | ----- | ----------------------------------------------------------------- |
| `test_indicators.py`      | 27    | RSI, MACD, EMA, Bollinger Bands, ATR calculations                 |
| `test_strategies.py`      | ~20   | Individual buy and sell strategy signal logic                     |
| `test_strategy_engine.py` | ~10   | Voting aggregation, confidence thresholds, error resilience       |
| `test_risk_manager.py`    | ~26   | Kill switch, daily limits, drawdown, lot size, fat-finger         |
| `test_database.py`        | 16    | All 8 database tables, relationships, data integrity, persistence |
| `test_integration.py`     | 35    | Full API endpoints, auth, price feed, trading, risk, database     |

### Testing Approach

- **Unit tests** — pure functions tested in isolation with known inputs and verified outputs
- **Database tests** — use in-memory SQLite so tests never touch the real `algobot.db`
- **Integration tests** — use FastAPI's `TestClient` with `unittest.mock.patch` to replace the MT5 connector with controlled data, so all 134 tests run on any machine without MT5 installed

---

## 🗄️ Database

Trade history, signal evaluations, account snapshots, and risk events are all stored persistently in `algobot.db` (SQLite). The database initialises automatically on every server startup using `CREATE TABLE IF NOT EXISTS` — existing data is never overwritten.

### Tables

| Table               | What it stores                                                        |
| ------------------- | --------------------------------------------------------------------- |
| `accounts`          | Account snapshot on every login (balance, equity, server)             |
| `trades`            | Every order placed — symbol, direction, entry price, lot size, SL, TP |
| `trade_outcomes`    | Exit price and P&L when trades close                                  |
| `signals`           | Every strategy evaluation — final signal, confidence, vote counts     |
| `strategy_votes`    | Individual per-strategy vote breakdown                                |
| `risk_events`       | Kill switch activations and deactivations                             |
| `price_snapshots`   | Periodic price records for spread analysis                            |
| `performance_daily` | Rolled-up daily performance statistics                                |

### Accessing Data

```bash
# Check row counts across all tables
python -c "
from database.connection import engine
from sqlalchemy import text
tables = ['accounts','trades','signals','trade_outcomes','risk_events','performance_daily']
with engine.connect() as c:
    for t in tables:
        count = c.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar()
        print(f'{t:<25} {count} rows')
"
```

Or open `algobot.db` directly using [DB Browser for SQLite](https://sqlitebrowser.org/).

The database file is in `.gitignore` — each machine maintains its own local history.

### Database API Endpoints

| Endpoint                       | Returns                      |
| ------------------------------ | ---------------------------- |
| `GET /api/history`             | All trades from the database |
| `GET /api/signals/log`         | Recent signal evaluations    |
| `GET /api/performance/summary` | Daily performance rollup     |

---

## 📁 Project Structure

```
AlgoTradingBot/
│
├── main.py                        # FastAPI server — entry point + auto trading scheduler
├── requirements.txt               # Python dependencies
├── README.md
├── .env                           # API keys (gitignored)
│
├── config/
│   └── settings.py                # All app settings and risk parameters
│
├── data/
│   ├── mt5_connector.py           # MT5 connection with mock fallback + Alpha Vantage API
│   └── data_fetcher.py            # Clean data access layer with caching
│
├── indicators/
│   ├── rsi.py                     # Relative Strength Index
│   ├── macd.py                    # MACD and crossover signals
│   ├── ema.py                     # Exponential Moving Averages
│   ├── bollinger.py               # Bollinger Bands
│   └── atr.py                     # ATR, Stochastic, ADX, VWAP, CCI
│
├── strategies/
│   ├── base.py                    # Abstract base class and Signal enum
│   ├── buy/                       # 20 buy strategies (B01–B20)
│   └── sell/                      # 20 sell strategies (S01–S20)
│
├── services/
│   └── strategy_engine.py         # Aggregates all 40 strategy votes
│
├── execution/
│   ├── risk_manager.py            # 5-layer pre-trade risk checks
│   └── trade_executor.py          # Builds and sends MT5 orders + saves to database
│
├── database/
│   ├── __init__.py
│   ├── connection.py              # SQLAlchemy engine and session management
│   ├── models.py                  # 8 table definitions (ORM models)
│   ├── repository.py              # All read/write functions — only file that touches the DB
│   ├── init_db.py                 # CLI utility: python -m database.init_db
│   └── database_README.md         # Database layer documentation
│
├── ui/
│   ├── templates/
│   │   ├── login.html             # Login and MT5 connection page
│   │   ├── dashboard.html         # Live trading dashboard
│   │   ├── history.html           # Trade history (reads from database)
│   │   ├── performance.html       # Analytics and strategy breakdown
│   │   └── risk.html              # Risk manager and kill switch
│   └── static/
│       ├── css/
│       │   ├── styling.css        # Main app styles — slate-navy theme, IBM Plex fonts
│       │   └── guide.css          # User onboarding guide styles
│       └── js/
│           └── guide.js           # Welcome modal + step tour + card tooltip engine
│
└── tests/
    ├── test_indicators.py         # 27 indicator tests
    ├── test_strategies.py         # Strategy signal tests
    ├── test_strategy_engine.py    # Voting engine tests
    ├── test_risk_manager.py       # Risk management tests
    ├── test_database.py           # 16 database layer tests
    └── test_integration.py        # 35 full-stack API integration tests
```

---

## ⚙️ Configuration

All settings are centralised in `config/settings.py`:

| Setting                | Default | Description                                       |
| ---------------------- | ------- | ------------------------------------------------- |
| `MIN_STRATEGY_VOTES`   | `2`     | Minimum strategies that must agree before trading |
| `CONFIDENCE_THRESHOLD` | `0.50`  | Minimum average confidence required               |
| `DEFAULT_LOT_SIZE`     | `0.01`  | Default trade size in lots                        |
| `MAX_LOT_SIZE`         | `1.0`   | Maximum allowed lot size                          |
| `MAX_TRADES_PER_DAY`   | `20`    | Daily trade limit                                 |
| `MAX_DRAWDOWN_PCT`     | `5.0`   | Maximum account drawdown before halting           |
| `RISK_PER_TRADE_PCT`   | `1.0`   | Percentage of equity risked per trade             |

Alpha Vantage API key goes in a `.env` file in the project root (gitignored):

```
ALPHA_VANTAGE_API_KEY=your_key_here
```

---

## 📦 Dependencies

| Package             | Purpose                                                     |
| ------------------- | ----------------------------------------------------------- |
| `fastapi`           | Web framework for the REST API                              |
| `uvicorn`           | ASGI server to run FastAPI                                  |
| `jinja2`            | HTML template rendering                                     |
| `sqlalchemy`        | ORM for the database layer                                  |
| `pandas`            | Data manipulation and OHLCV processing                      |
| `numpy`             | Numerical calculations for indicators                       |
| `apscheduler`       | Automated trading scheduler                                 |
| `python-dotenv`     | Environment variable management                             |
| `pydantic-settings` | Settings management and validation                          |
| `requests`          | HTTP client for Alpha Vantage API                           |
| `pytest`            | Unit testing framework                                      |
| `httpx`             | Async HTTP client for integration tests                     |
| `MetaTrader5`       | MT5 broker connection _(Windows only — install separately)_ |

---

## 🌐 API Endpoints

The FastAPI server exposes the following REST endpoints. Interactive documentation is available at `http://localhost:8000/docs`.

| Method | Endpoint                   | Description                             |
| ------ | -------------------------- | --------------------------------------- |
| `POST` | `/api/connect`             | Connect to MT5 or demo mode             |
| `POST` | `/api/disconnect`          | Disconnect and clear session            |
| `GET`  | `/api/account`             | Current account info                    |
| `GET`  | `/api/price/{symbol}`      | Live bid/ask price                      |
| `GET`  | `/api/signal/{symbol}`     | Run all 40 strategies and return result |
| `GET`  | `/api/ohlcv/{symbol}`      | Historical candlestick data             |
| `POST` | `/api/trade`               | Place a buy or sell order               |
| `GET`  | `/api/positions`           | Currently open positions                |
| `GET`  | `/api/risk/status`         | Risk manager state                      |
| `POST` | `/api/risk/killswitch`     | Activate or deactivate kill switch      |
| `GET`  | `/api/history`             | Trade history from database             |
| `GET`  | `/api/signals/log`         | Signal evaluation log from database     |
| `GET`  | `/api/performance/summary` | Daily performance from database         |
| `GET`  | `/api/bot/status`          | Automated bot status                    |
| `POST` | `/api/bot/toggle`          | Enable or disable the bot               |
| `GET`  | `/api/status`              | Server health check                     |

---

## 👥 Team

| Member  | Role                 | Contribution                                                                             |
| ------- | -------------------- | ---------------------------------------------------------------------------------------- |
| Archana | **Logic & Strategy** | 40 trading strategies, risk manager, trade executor, technical indicators, MT5 connector |
| Sara    | **UI & Testing**     | FastAPI backend, HTML dashboard, 134 unit and integration tests, user onboarding guide   |
| Shubham | **API Integration**  | Fallback API Integration                                                                 |
| Sivani  | **Database**         | SQLAlchemy model, database API endpoints                                                 |

---

## ⚠️ Disclaimer

This project is built for **educational purposes** as part of a university coursework assignment. It is not financial advice. Automated trading carries significant financial risk. Do not use this system with real funds without fully understanding the risks involved and applicable regulations in your jurisdiction.

---

<div align="center">
  <sub>Built with Python · FastAPI · SQLAlchemy · MetaTrader 5 · CST4160 FinTech Coursework · Middlesex University Dubai</sub>
</div>
