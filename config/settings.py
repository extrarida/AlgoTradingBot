"""
config/settings.py
──────────────────
Central configuration via pydantic-settings.
All values can be overridden with environment variables or a .env file.
"""

from __future__ import annotations
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str  = "AlgoBot"
    VERSION:  str  = "2.0.0"
    DEBUG:    bool = False

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY:                    str = "change-me-before-production"
    JWT_ALGORITHM:                 str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES:   int = 120

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./algobot.db"

    # ── MetaTrader 5 ─────────────────────────────────────────────────────────
    MT5_PATH:    Optional[str] = None
    MT5_TIMEOUT: int           = 60000

    # ── External Market Data API ──────────────────────────────────────────────
    EXTERNAL_API_PROVIDER:    str  = "alpha_vantage"
    EXTERNAL_API_BASE_URL:    str  = "https://www.alphavantage.co/query"
    EXTERNAL_API_KEY:         Optional[str] = None
    TWELVEDATA_BASE_URL:      str  = "https://api.twelvedata.com"
    TWELVEDATA_API_KEY:       Optional[str] = None
    EXCHANGE_RATE_HOST_BASE_URL: str = "https://api.exchangerate.host"
    EXTERNAL_API_TIMEOUT:     int  = 10

    # ── Fallback behavior ─────────────────────────────────────────────────────
    FALLBACK_RETRIES:         int   = 2
    FALLBACK_RETRY_DELAY_SEC: float = 0.5

    # ── Risk ─────────────────────────────────────────────────────────────────
    DEFAULT_LOT_SIZE:          float = 0.01
    MAX_LOT_SIZE:              float = 1.0
    DEFAULT_STOP_LOSS_PIPS:    int   = 50
    DEFAULT_TAKE_PROFIT_PIPS:  int   = 100
    MAX_TRADES_PER_DAY:        int   = 20
    MAX_DRAWDOWN_PCT:          float = 5.0
    RISK_PER_TRADE_PCT:        float = 1.0

    # ── Strategy engine ───────────────────────────────────────────────────────
    MIN_STRATEGY_VOTES:         int   = 3
    CONFIDENCE_THRESHOLD:       float = 0.60
    STRATEGY_EVAL_INTERVAL_SEC: int   = 60

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    class Config:
        env_file         = ".env"
        env_file_encoding = "utf-8"
        extra            = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
