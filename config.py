"""
360 Crypto Eye Scalping Signals — Central Configuration
All runtime secrets must be supplied via environment variables.
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: int = int(os.environ.get("TELEGRAM_CHANNEL_ID", "-1003851389127"))
ADMIN_CHAT_ID: int = int(os.environ.get("ADMIN_CHAT_ID", "710718010"))

# ── Signal Engine ─────────────────────────────────────────────────────────────
# Supported timeframes (in minutes) used by the multi-TF bias engine
TIMEFRAMES: dict[str, int] = {
    "1D": 1440,
    "4H": 240,
    "15m": 15,
    "5m": 5,
}

# Leverage range recommended to subscribers
LEVERAGE_MIN: int = 10
LEVERAGE_MAX: int = 20

# Risk per trade expressed as a fraction of account balance (1 %)
DEFAULT_RISK_FRACTION: float = 0.01

# ── Safety Protocols ──────────────────────────────────────────────────────────
# Maximum concurrent signals on the same directional side (long / short)
MAX_SAME_SIDE_SIGNALS: int = 3

# Stale-signal threshold: auto-close / alert if entry zone is untouched (hours)
STALE_SIGNAL_HOURS: int = 4

# Break-Even trigger: move SL to entry when price covers this fraction of TP1
BE_TRIGGER_FRACTION: float = 0.50

# ── News Filter ───────────────────────────────────────────────────────────────
# Skip any new signal when a high-impact event falls within this many minutes
NEWS_SKIP_WINDOW_MINUTES: int = 60

# CoinMarketCal API key — get a free key at https://coinmarketcal.com/en/api
COINMARKETCAL_API_KEY: str = os.environ.get("COINMARKETCAL_API_KEY", "")

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_LOG_FILE: str = os.environ.get("DASHBOARD_LOG_FILE", "dashboard.json")

# ── Persistence ───────────────────────────────────────────────────────────────
SIGNALS_FILE: str = os.environ.get("SIGNALS_FILE", "signals.json")

# ── Webhook ───────────────────────────────────────────────────────────────────
WEBHOOK_HOST: str = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT: int = int(os.environ.get("WEBHOOK_PORT", "5000"))
WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "")

# ── Auto-Scanner ──────────────────────────────────────────────────────────────
# Pairs to scan automatically (base symbols; USDT perpetual assumed)
_raw_pairs = os.environ.get(
    "AUTO_SCAN_PAIRS",
    "BTC,ETH,SOL,XRP,DOGE,ADA,AVAX,LINK,DOT,MATIC",
)
AUTO_SCAN_PAIRS: list[str] = [p.strip().upper() for p in _raw_pairs.split(",") if p.strip()]

AUTO_SCAN_INTERVAL_SECONDS: int = int(os.environ.get("AUTO_SCAN_INTERVAL_SECONDS", "300"))
