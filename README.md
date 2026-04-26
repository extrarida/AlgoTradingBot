# ⚡ AlgoTrader Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)
![MT5](https://img.shields.io/badge/MetaTrader5-Compatible-1565C0?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-22d3a5?style=flat-square)
![Status](https://img.shields.io/badge/Status-In%20Development-f59e0b?style=flat-square)

**A professional algorithmic trading bot powered by a 40-strategy voting engine,
real-time market data, and a full web dashboard.**

*Built for the CST4160 FinTech Coursework — University Project*

[Features](#-features) · [Architecture](#-architecture) · [Getting Started](#-getting-started) · [Usage](#-usage) · [Testing](#-testing) · [Project Structure](#-project-structure)

</div>

---

## 📌 Overview

AlgoTrader Bot is a Python-based algorithmic trading system that connects to the MetaTrader 5 (MT5) broker platform to execute trades automatically based on technical analysis signals.

The system runs **40 independent trading strategies** simultaneously — 20 for identifying buy opportunities and 20 for sell opportunities. A central strategy engine aggregates all votes and only places a trade when enough strategies agree with sufficient confidence. Every trade is protected by a 5-layer pre-trade risk management system before execution.

The application can run fully in **Mock Mode** on any machine without a real MT5 connection, making it easy to demonstrate and test on any operating system.

Currently, the trading logic, the testing for said logic and the UI is complete. External market data API integration, database integration and real MT5 broker integration testing is remaining.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **40-Strategy Engine** | RSI, MACD, EMA, Bollinger Bands, candlestick patterns, volume breakouts and more |
| 🗳️ **Voting System** | Trades only execute when multiple strategies agree — reduces false signals |
| 🛡️ **Risk Management** | 5-layer protection: kill switch, daily limits, drawdown checks, lot size guards, fat-finger prevention |
| 📊 **Live Dashboard** | Real-time prices, signal display, candlestick chart, open positions |
| 📜 **Trade History** | Full record of all placed orders with filtering |
| 📈 **Performance Analytics** | Session P&L, signal distribution charts, strategy breakdown |
| 🔌 **Mock Mode** | Runs on any OS without MT5 installed — fully simulated environment |
| ⚡ **FastAPI Backend** | Clean REST API connecting the HTML frontend to the Python trading engine |

---

## 🏗️ Architecture

The system follows a 14-layer architecture from raw market data to trade execution:

```
┌─────────────────────────────────────┐
│         Browser (HTML/CSS/JS)        │  ← 5 pages: Login, Dashboard,
│         Web Dashboard                │    History, Performance, Risk
└──────────────┬──────────────────────┘
               │ HTTP (FastAPI)
┌──────────────▼──────────────────────┐
│         main.py (FastAPI Server)     │  ← REST API bridge
└──────────────┬──────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐  ┌─────────────────────┐
│ Strategy    │  │   Data Layer        │
│ Engine      │  │                     │
│             │  │  data_fetcher.py    │
│ 40 strats   │◄─┤  mt5_connector.py  │
│ vote →      │  │  (mock or real MT5) │
│ BUY/SELL    │  └─────────────────────┘
│ /NONE       │
└──────┬──────┘
       │
┌──────▼──────────────────────────────┐
│         Risk Manager                 │  ← 5 safety checks before every trade
└──────┬──────────────────────────────┘
       │
┌──────▼──────────────────────────────┐
│         Trade Executor               │  ← Sends order to MT5 or mock
└─────────────────────────────────────┘
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

**4. Start the server**
```bash
uvicorn main:app --reload --port 8000
```

**5. Open in your browser**
```
http://localhost:8000
```

> 💡 The app starts in **Mock Mode** automatically — no MT5 account needed. Enter any credentials on the login page to connect.

---

## 🖥️ Usage

### Logging In

On the login page, enter any values in the three fields and click **Connect to MT5**.

In Mock Mode, credentials are not validated — the app will always connect successfully and load a simulated account with $10,000 balance.

| Field | Example Value |
|-------|--------------|
| Account Number | `12345678` |
| Password | `anything` |
| Broker Server | `MockBroker` |

---

### Dashboard

The main trading interface. From here you can:

- **View live prices** — updates every 5 seconds
- **Get strategy signals** — click ↻ Refresh to run all 40 strategies
- **Read the signal breakdown** — see how many strategies voted BUY, SELL, or HOLD
- **View the price chart** — switch between M5, M15, and H1 timeframes
- **Place trades** — set lot size, stop loss, and take profit, then click BUY or SELL
- **Monitor open positions** — see all active trades with live floating P&L

---

### Other Pages

| Page | URL | What it shows |
|------|-----|---------------|
| Trade History | `/history` | All orders placed this session with filters |
| Performance | `/performance` | Signal distribution chart, P&L bar chart, strategy analysis |
| Risk Manager | `/risk` | Risk gauges, pre-trade check results, kill switch |

---

### Using the Kill Switch

Navigate to the **Risk Manager** page and click **⛔ Halt Trading**. This immediately blocks all new trade orders regardless of signal strength. Click **✓ Resume** to re-enable trading.

---

## 🔌 Connecting Real MT5 (Windows Only)

The MetaTrader 5 Python package only works on Windows. To connect a real account:

1. Download and install [MetaTrader 5](https://www.metatrader5.com/en/download) from your broker
2. Open the MT5 application and log into your account
3. Ensure MT5 is **running in the background** while the server is active
4. Start the server — it will detect MT5 automatically and use real data

> ⚠️ The app will fall back to Mock Mode if MT5 is installed but not running.

---

## 🧪 Testing

The project includes **83 unit tests** covering all core modules.

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
```

**Expected output:**
```
83 passed, 1 warning in 0.76s
```

### What is tested

| Test File | What it covers |
|-----------|---------------|
| `test_indicators.py` | RSI, MACD, EMA, Bollinger Bands, ATR calculations |
| `test_strategies.py` | Individual buy and sell strategy signal logic |
| `test_strategy_engine.py` | Voting aggregation, confidence thresholds, error resilience |
| `test_risk_manager.py` | Kill switch, daily limits, drawdown, lot size, position sizing |

---

## 📁 Project Structure

```
AlgoTradingBot/
│
├── main.py                        # FastAPI server — entry point
├── requirements.txt               # Python dependencies
├── README.md
│
├── config/
│   └── settings.py                # All app settings and risk parameters
│
├── data/
│   ├── mt5_connector.py           # MT5 connection with mock fallback
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
│   └── trade_executor.py          # Builds and sends MT5 orders
│
├── ui/
│   ├── templates/
│   │   ├── login.html             # Login and MT5 connection page
│   │   ├── dashboard.html         # Live trading dashboard
│   │   ├── history.html           # Trade history with filters
│   │   ├── performance.html       # Analytics and strategy breakdown
│   │   └── risk.html              # Risk manager and kill switch
│   └── static/
│       └── css/
│           └── shared.css         # Shared styles across all pages
│
└── tests/
    ├── test_indicators.py
    ├── test_strategies.py
    ├── test_strategy_engine.py
    └── test_risk_manager.py
```

---

## ⚙️ Configuration

All settings are centralised in `config/settings.py`. Key values:

| Setting | Default | Description |
|---------|---------|-------------|
| `MIN_STRATEGY_VOTES` | `2` | Minimum strategies that must agree before trading |
| `CONFIDENCE_THRESHOLD` | `0.50` | Minimum average confidence required |
| `DEFAULT_LOT_SIZE` | `0.01` | Default trade size in lots |
| `MAX_LOT_SIZE` | `1.0` | Maximum allowed lot size |
| `MAX_TRADES_PER_DAY` | `20` | Daily trade limit |
| `MAX_DRAWDOWN_PCT` | `5.0` | Maximum account drawdown before halting |
| `RISK_PER_TRADE_PCT` | `1.0` | Percentage of equity risked per trade |

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework for the REST API |
| `uvicorn` | ASGI server to run FastAPI |
| `jinja2` | HTML template rendering |
| `pandas` | Data manipulation and OHLCV processing |
| `numpy` | Numerical calculations for indicators |
| `MetaTrader5` | MT5 broker connection (Windows only) |
| `pydantic-settings` | Settings management and validation |
| `pytest` | Unit testing framework |

---

## 👥 Team

| Member  | Role | Contribution |
|---------|-------|-------------|
| Archana | **Logic & Strategy** | 40 trading strategies, risk manager, trade executor, technical indicators |
|  Sara   | **UI & Testing** | FastAPI backend, 5-page HTML dashboard, 83 unit tests, documentation |
| Shubham | **API Integration** | External market data API integration *(in progress)* |
| Sivani  | **Database** | Persistent trade storage and history *(in progress)* |

---

## 🗺️ Roadmap

- [x] 40-strategy trading engine
- [x] Risk management system
- [x] FastAPI REST backend
- [x] Full HTML/CSS/JS dashboard
- [x] Mock mode for cross-platform development
- [x] Unit test suite (83 tests)
- [ ] External market data API integration
- [ ] SQLite database for persistent trade history
- [ ] Performance metrics from historical trade data
- [ ] Real MT5 broker integration testing

---

## ⚠️ Disclaimer

This project is built for **educational purposes** as part of a university coursework assignment. It is not financial advice. Automated trading carries significant financial risk. Do not use this system with real funds without fully understanding the risks involved and applicable regulations in your jurisdiction.

---

<div align="center">
  <sub>Built with Python · FastAPI · MetaTrader 5 · CST4160 FinTech Coursework</sub>
</div>
