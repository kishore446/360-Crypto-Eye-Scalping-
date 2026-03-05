"""
360 Crypto Eye Scalping Signals — Central Configuration
Validated via Pydantic Settings. All secrets must be supplied via environment variables.
"""
from __future__ import annotations

import os

try:
    from pydantic import field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        # ── Telegram ─────────────────────────────────────────────────────────
        telegram_bot_token: str = ""
        telegram_channel_id: int = 0
        admin_chat_id: int = 0

        # ── Signal Engine ─────────────────────────────────────────────────────
        leverage_min: int = 10
        leverage_max: int = 20
        default_risk_fraction: float = 0.01

        # TP R:R ratios — configurable
        tp1_rr: float = 1.5
        tp2_rr: float = 2.5
        tp3_rr: float = 4.0

        # ── Safety Protocols ─────────────────────────────────────────────────
        max_same_side_signals: int = 5
        stale_signal_hours: int = 4
        be_trigger_fraction: float = 0.50

        # ── News Filter ──────────────────────────────────────────────────────
        news_skip_window_minutes: int = 60
        coinmarketcal_api_key: str = ""

        # ── Session Filter ────────────────────────────────────────────────────
        session_filter_enabled: bool = False

        # ── Confluence Scoring ────────────────────────────────────────────────
        min_confluence_score: int = 0  # 0 = disabled

        # ── News Fail-Safe ────────────────────────────────────────────────────
        news_fail_safe_window_minutes: int = 60

        # ── Dashboard ────────────────────────────────────────────────────────
        dashboard_log_file: str = "data/dashboard.json"

        # ── Persistence ──────────────────────────────────────────────────────
        signals_file: str = "data/signals.json"
        db_path: str = "data/360eye.db"

        # ── Webhook ──────────────────────────────────────────────────────────
        webhook_host: str = "0.0.0.0"
        webhook_port: int = 5000
        webhook_secret: str = ""
        allowed_webhook_ips: str = ""  # comma-separated, empty = allow all
        webhook_rate_limit_window: int = 60  # seconds
        webhook_rate_limit_max: int = 30     # max requests per window

        # ── Auto-Scanner ─────────────────────────────────────────────────────
        auto_scan_pairs: str = ""
        auto_scan_interval_seconds: int = 60
        auto_scan_enabled_on_boot: bool = True

        @field_validator("telegram_bot_token")
        @classmethod
        def token_not_placeholder(cls, v: str) -> str:
            if v in ("YOUR_TOKEN_HERE", "PLACEHOLDER"):
                raise ValueError("TELEGRAM_BOT_TOKEN must not be a placeholder value.")
            return v

    settings = Settings()

    # ── Module-level aliases (backward compatibility) ────────────────────────
    TELEGRAM_BOT_TOKEN: str = settings.telegram_bot_token
    TELEGRAM_CHANNEL_ID: int = settings.telegram_channel_id
    ADMIN_CHAT_ID: int = settings.admin_chat_id

    LEVERAGE_MIN: int = settings.leverage_min
    LEVERAGE_MAX: int = settings.leverage_max
    DEFAULT_RISK_FRACTION: float = settings.default_risk_fraction

    TP1_RR: float = settings.tp1_rr
    TP2_RR: float = settings.tp2_rr
    TP3_RR: float = settings.tp3_rr

    MAX_SAME_SIDE_SIGNALS: int = settings.max_same_side_signals
    STALE_SIGNAL_HOURS: int = settings.stale_signal_hours
    BE_TRIGGER_FRACTION: float = settings.be_trigger_fraction

    NEWS_SKIP_WINDOW_MINUTES: int = settings.news_skip_window_minutes
    COINMARKETCAL_API_KEY: str = settings.coinmarketcal_api_key

    SESSION_FILTER_ENABLED: bool = settings.session_filter_enabled
    MIN_CONFLUENCE_SCORE: int = settings.min_confluence_score
    NEWS_FAIL_SAFE_WINDOW_MINUTES: int = settings.news_fail_safe_window_minutes

    DASHBOARD_LOG_FILE: str = settings.dashboard_log_file
    SIGNALS_FILE: str = settings.signals_file
    DB_PATH: str = settings.db_path

    WEBHOOK_HOST: str = settings.webhook_host
    WEBHOOK_PORT: int = settings.webhook_port
    WEBHOOK_SECRET: str = settings.webhook_secret
    ALLOWED_WEBHOOK_IPS: list[str] = [
        ip.strip() for ip in settings.allowed_webhook_ips.split(",") if ip.strip()
    ]
    WEBHOOK_RATE_LIMIT_WINDOW: int = settings.webhook_rate_limit_window
    WEBHOOK_RATE_LIMIT_MAX: int = settings.webhook_rate_limit_max

    _raw_pairs = settings.auto_scan_pairs
    AUTO_SCAN_PAIRS: list[str] = [p.strip().upper() for p in _raw_pairs.split(",") if p.strip()]
    AUTO_SCAN_INTERVAL_SECONDS: int = settings.auto_scan_interval_seconds
    AUTO_SCAN_ENABLED_ON_BOOT: bool = settings.auto_scan_enabled_on_boot

    TIMEFRAMES: dict[str, int] = {
        "1D": 1440,
        "4H": 240,
        "15m": 15,
        "5m": 5,
    }

except ImportError:
    # Fallback if pydantic-settings not installed yet
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID: int = int(os.environ.get("TELEGRAM_CHANNEL_ID", "0"))
    ADMIN_CHAT_ID: int = int(os.environ.get("ADMIN_CHAT_ID", "0"))
    LEVERAGE_MIN: int = 10
    LEVERAGE_MAX: int = 20
    DEFAULT_RISK_FRACTION: float = 0.01
    TP1_RR: float = 1.5
    TP2_RR: float = 2.5
    TP3_RR: float = 4.0
    MAX_SAME_SIDE_SIGNALS: int = 5
    STALE_SIGNAL_HOURS: int = 4
    BE_TRIGGER_FRACTION: float = 0.50
    NEWS_SKIP_WINDOW_MINUTES: int = 60
    COINMARKETCAL_API_KEY: str = os.environ.get("COINMARKETCAL_API_KEY", "")
    SESSION_FILTER_ENABLED: bool = os.environ.get("SESSION_FILTER_ENABLED", "false").lower() in ("true", "1", "yes")
    MIN_CONFLUENCE_SCORE: int = int(os.environ.get("MIN_CONFLUENCE_SCORE", "0"))
    NEWS_FAIL_SAFE_WINDOW_MINUTES: int = int(os.environ.get("NEWS_FAIL_SAFE_WINDOW_MINUTES", "60"))
    DASHBOARD_LOG_FILE: str = os.environ.get("DASHBOARD_LOG_FILE", "data/dashboard.json")
    SIGNALS_FILE: str = os.environ.get("SIGNALS_FILE", "data/signals.json")
    DB_PATH: str = os.environ.get("DB_PATH", "data/360eye.db")
    WEBHOOK_HOST: str = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT: int = int(os.environ.get("WEBHOOK_PORT", "5000"))
    WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "")
    ALLOWED_WEBHOOK_IPS: list[str] = []
    WEBHOOK_RATE_LIMIT_WINDOW: int = int(os.environ.get("WEBHOOK_RATE_LIMIT_WINDOW", "60"))
    WEBHOOK_RATE_LIMIT_MAX: int = int(os.environ.get("WEBHOOK_RATE_LIMIT_MAX", "30"))
    _raw_pairs = os.environ.get("AUTO_SCAN_PAIRS", "")
    AUTO_SCAN_PAIRS: list[str] = [p.strip().upper() for p in _raw_pairs.split(",") if p.strip()]
    AUTO_SCAN_INTERVAL_SECONDS: int = int(os.environ.get("AUTO_SCAN_INTERVAL_SECONDS", "60"))
    AUTO_SCAN_ENABLED_ON_BOOT: bool = os.environ.get("AUTO_SCAN_ENABLED_ON_BOOT", "true").lower() in ("true", "1", "yes")
    TIMEFRAMES: dict[str, int] = {"1D": 1440, "4H": 240, "15m": 15, "5m": 5}

