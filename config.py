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

        # ── Multi-Channel Telegram ────────────────────────────────────────────
        telegram_channel_id_hard: int = 0      # CH1: Hard Scalp (replaces telegram_channel_id)
        telegram_channel_id_medium: int = 0    # CH2: Medium Scalp
        telegram_channel_id_easy: int = 0      # CH3: Easy Breakout
        telegram_channel_id_spot: int = 0      # CH4: Spot Momentum
        telegram_channel_id_insights: int = 0  # CH5: Market Insights

        # ── Channel Thresholds ───────────────────────────────────────────────
        ch2_news_window_minutes: int = 30         # Medium channel relaxed news window
        ch3_volume_spike_ratio: float = 1.5       # 150% volume spike for easy breakout
        ch4_scan_interval_hours: int = 4          # Spot channel scan frequency
        ch4_accumulation_threshold: float = 0.15  # Within 15% of 90d low for spot

        # ── Insights ─────────────────────────────────────────────────────────
        btc_fear_greed_url: str = "https://api.alternative.me/fng/"
        regime_detector_enabled: bool = True

        # ── Signal Deduplication ─────────────────────────────────────────────
        dedup_window_minutes: int = 15  # Suppress CH2 if same symbol fired CH1 within 15min

        # ── Signal Engine ─────────────────────────────────────────────────────
        leverage_min: int = 10
        leverage_max: int = 20
        default_risk_fraction: float = 0.01

        # TP R:R ratios — configurable
        tp1_rr: float = 1.5
        tp2_rr: float = 2.5
        tp3_rr: float = 4.0

        # ── Safety Protocols ─────────────────────────────────────────────────
        max_same_side_signals: int = 3
        stale_signal_hours: int = 4
        be_trigger_fraction: float = 0.50

        # ── News Filter ──────────────────────────────────────────────────────
        news_skip_window_minutes: int = 60
        coinmarketcal_api_key: str = ""

        # ── Session Filter ────────────────────────────────────────────────────
        session_filter_enabled: bool = True
        session_filter_ch1_enabled: bool = True   # Hard scalp — session gated
        session_filter_ch2_enabled: bool = True   # Medium scalp — session gated
        session_filter_ch3_enabled: bool = False  # Easy breakout — 24/7
        session_filter_ch4_enabled: bool = False  # Spot — 24/7

        # ── Funding Rate Gate ─────────────────────────────────────────────────
        funding_rate_gate_enabled: bool = True
        funding_extreme_negative: float = -0.0001
        funding_extreme_positive: float = 0.0005

        # ── Open Interest Monitor ─────────────────────────────────────────────
        oi_monitor_enabled: bool = True
        oi_change_threshold: float = 0.05  # 5% OI change is significant

        # ── Loss Streak Cooldown ──────────────────────────────────────────────
        loss_streak_threshold: int = 3
        cooldown_signals: int = 3
        cooldown_hours: int = 24

        # ── Insights Schedule ─────────────────────────────────────────────────
        fear_greed_interval_hours: int = 6
        daily_performance_hour: int = 23  # UTC hour for daily recap

        # ── Confluence Scoring ────────────────────────────────────────────────
        min_confluence_score: int = 40  # 40 = filter out low-quality signals
        min_displacement_pct: float = 0.15  # Gate ④ displacement filter (§2.2)

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
        # Leave empty to scan ALL Binance Futures pairs (recommended).
        # Set to a comma-separated list (e.g. "BTC,ETH,SOL") to use as a whitelist.
        auto_scan_pairs: str = ""
        auto_scan_interval_seconds: int = 60
        auto_scan_enabled_on_boot: bool = True

        # ── Futures Scanner Tuning ────────────────────────────────────────────
        # Optional: filter pairs below this 24h USD volume (0 = no filter).
        futures_min_24h_volume_usdt: int = 0
        futures_scan_batch_size: int = 20
        futures_scan_batch_delay: float = 0.5

        # ── Spot Scanner ──────────────────────────────────────────────────────
        spot_scan_enabled: bool = True
        spot_scan_interval_minutes: int = 60
        spot_min_24h_volume_usdt: int = 100000  # $100k minimum
        spot_gem_volume_spike_ratio: float = 3.0  # 3x volume = dormant awakening
        spot_gem_breakout_lookback_days: int = 30  # 30-day high for breakout
        spot_gem_accumulation_range_pct: float = 0.10  # 10% tight range
        spot_new_listing_lookback_days: int = 90  # new listing window
        spot_scam_pump_threshold_pct: float = 500.0  # >500% = pump alert
        spot_scam_crash_threshold_pct: float = 50.0  # >50% crash after pump
        spot_scan_batch_size: int = 30
        spot_scan_batch_delay: float = 0.5

        # ── Whale Alert API (optional) ────────────────────────────────────────
        whale_alert_api_key: str = ""

        # ── Coinglass API (optional) ──────────────────────────────────────────
        coinglass_api_key: str = ""

        # ── Signal Broadcast Rate Limiting ────────────────────────────────────
        min_signal_gap_seconds: int = 300  # 5 minutes minimum between signals per channel

        # ── Admin Alerting ────────────────────────────────────────────────────
        admin_alert_enabled: bool = True
        admin_alert_win_rate_threshold: int = 40

        # ── OI Divergence Detection ───────────────────────────────────────────
        oi_divergence_enabled: bool = True

        # ── Chart Generation ──────────────────────────────────────────────────
        chart_enabled: bool = True

        # ── Daily Briefing ────────────────────────────────────────────────────
        briefing_enabled: bool = True
        briefing_hour_utc: int = 8

        # ── Invalidation Detector ─────────────────────────────────────────────
        invalidation_check_enabled: bool = True

        # ── Correlation Guard ─────────────────────────────────────────────────
        correlation_alert_enabled: bool = True
        correlation_max_same_group: int = 3

        # ── DB Archiving ──────────────────────────────────────────────────────
        db_archive_days: int = 90

        @field_validator("telegram_bot_token")
        @classmethod
        def token_not_placeholder(cls, v: str) -> str:
            if v in ("YOUR_TOKEN_HERE", "PLACEHOLDER"):
                raise ValueError("TELEGRAM_BOT_TOKEN must not be a placeholder value.")
            return v

    settings = Settings()

    # ── Module-level aliases (backward compatibility) ────────────────────────
    TELEGRAM_BOT_TOKEN: str = settings.telegram_bot_token
    # DEPRECATED: use TELEGRAM_CHANNEL_ID_HARD instead. Will be removed in v3.0
    TELEGRAM_CHANNEL_ID: int = settings.telegram_channel_id
    ADMIN_CHAT_ID: int = settings.admin_chat_id

    # ── Multi-channel IDs — CH1 falls back to TELEGRAM_CHANNEL_ID ───────────
    TELEGRAM_CHANNEL_ID_HARD: int = settings.telegram_channel_id_hard or settings.telegram_channel_id
    TELEGRAM_CHANNEL_ID_MEDIUM: int = settings.telegram_channel_id_medium
    TELEGRAM_CHANNEL_ID_EASY: int = settings.telegram_channel_id_easy
    TELEGRAM_CHANNEL_ID_SPOT: int = settings.telegram_channel_id_spot
    TELEGRAM_CHANNEL_ID_INSIGHTS: int = settings.telegram_channel_id_insights

    CH2_NEWS_WINDOW_MINUTES: int = settings.ch2_news_window_minutes
    CH3_VOLUME_SPIKE_RATIO: float = settings.ch3_volume_spike_ratio
    CH4_SCAN_INTERVAL_HOURS: int = settings.ch4_scan_interval_hours
    CH4_ACCUMULATION_THRESHOLD: float = settings.ch4_accumulation_threshold

    BTC_FEAR_GREED_URL: str = settings.btc_fear_greed_url
    REGIME_DETECTOR_ENABLED: bool = settings.regime_detector_enabled
    DEDUP_WINDOW_MINUTES: int = settings.dedup_window_minutes

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
    SESSION_FILTER_CH1_ENABLED: bool = settings.session_filter_ch1_enabled
    SESSION_FILTER_CH2_ENABLED: bool = settings.session_filter_ch2_enabled
    SESSION_FILTER_CH3_ENABLED: bool = settings.session_filter_ch3_enabled
    SESSION_FILTER_CH4_ENABLED: bool = settings.session_filter_ch4_enabled

    FUNDING_RATE_GATE_ENABLED: bool = settings.funding_rate_gate_enabled
    FUNDING_EXTREME_NEGATIVE: float = settings.funding_extreme_negative
    FUNDING_EXTREME_POSITIVE: float = settings.funding_extreme_positive

    OI_MONITOR_ENABLED: bool = settings.oi_monitor_enabled
    OI_CHANGE_THRESHOLD: float = settings.oi_change_threshold

    LOSS_STREAK_THRESHOLD: int = settings.loss_streak_threshold
    COOLDOWN_SIGNALS: int = settings.cooldown_signals
    COOLDOWN_HOURS: int = settings.cooldown_hours

    FEAR_GREED_INTERVAL_HOURS: int = settings.fear_greed_interval_hours
    DAILY_PERFORMANCE_HOUR: int = settings.daily_performance_hour
    MIN_CONFLUENCE_SCORE: int = settings.min_confluence_score
    MIN_DISPLACEMENT_PCT: float = settings.min_displacement_pct
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

    FUTURES_MIN_24H_VOLUME_USDT: int = settings.futures_min_24h_volume_usdt
    FUTURES_SCAN_BATCH_SIZE: int = settings.futures_scan_batch_size
    FUTURES_SCAN_BATCH_DELAY: float = settings.futures_scan_batch_delay

    SPOT_SCAN_ENABLED: bool = settings.spot_scan_enabled
    SPOT_SCAN_INTERVAL_MINUTES: int = settings.spot_scan_interval_minutes
    SPOT_MIN_24H_VOLUME_USDT: int = settings.spot_min_24h_volume_usdt
    SPOT_GEM_VOLUME_SPIKE_RATIO: float = settings.spot_gem_volume_spike_ratio
    SPOT_GEM_BREAKOUT_LOOKBACK_DAYS: int = settings.spot_gem_breakout_lookback_days
    SPOT_GEM_ACCUMULATION_RANGE_PCT: float = settings.spot_gem_accumulation_range_pct
    SPOT_NEW_LISTING_LOOKBACK_DAYS: int = settings.spot_new_listing_lookback_days
    SPOT_SCAM_PUMP_THRESHOLD_PCT: float = settings.spot_scam_pump_threshold_pct
    SPOT_SCAM_CRASH_THRESHOLD_PCT: float = settings.spot_scam_crash_threshold_pct
    SPOT_SCAN_BATCH_SIZE: int = settings.spot_scan_batch_size
    SPOT_SCAN_BATCH_DELAY: float = settings.spot_scan_batch_delay

    WHALE_ALERT_API_KEY: str = settings.whale_alert_api_key
    COINGLASS_API_KEY: str = settings.coinglass_api_key
    MIN_SIGNAL_GAP_SECONDS: int = settings.min_signal_gap_seconds
    ADMIN_ALERT_ENABLED: bool = settings.admin_alert_enabled
    ADMIN_ALERT_WIN_RATE_THRESHOLD: int = settings.admin_alert_win_rate_threshold
    OI_DIVERGENCE_ENABLED: bool = settings.oi_divergence_enabled

    CHART_ENABLED: bool = settings.chart_enabled
    BRIEFING_ENABLED: bool = settings.briefing_enabled
    BRIEFING_HOUR_UTC: int = settings.briefing_hour_utc
    INVALIDATION_CHECK_ENABLED: bool = settings.invalidation_check_enabled
    CORRELATION_ALERT_ENABLED: bool = settings.correlation_alert_enabled
    CORRELATION_MAX_SAME_GROUP: int = settings.correlation_max_same_group
    DB_ARCHIVE_DAYS: int = settings.db_archive_days

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

    TELEGRAM_CHANNEL_ID_HARD: int = int(os.environ.get("TELEGRAM_CHANNEL_ID_HARD", "0")) or TELEGRAM_CHANNEL_ID
    TELEGRAM_CHANNEL_ID_MEDIUM: int = int(os.environ.get("TELEGRAM_CHANNEL_ID_MEDIUM", "0"))
    TELEGRAM_CHANNEL_ID_EASY: int = int(os.environ.get("TELEGRAM_CHANNEL_ID_EASY", "0"))
    TELEGRAM_CHANNEL_ID_SPOT: int = int(os.environ.get("TELEGRAM_CHANNEL_ID_SPOT", "0"))
    TELEGRAM_CHANNEL_ID_INSIGHTS: int = int(os.environ.get("TELEGRAM_CHANNEL_ID_INSIGHTS", "0"))

    CH2_NEWS_WINDOW_MINUTES: int = int(os.environ.get("CH2_NEWS_WINDOW_MINUTES", "30"))
    CH3_VOLUME_SPIKE_RATIO: float = float(os.environ.get("CH3_VOLUME_SPIKE_RATIO", "1.5"))
    CH4_SCAN_INTERVAL_HOURS: int = int(os.environ.get("CH4_SCAN_INTERVAL_HOURS", "4"))
    CH4_ACCUMULATION_THRESHOLD: float = float(os.environ.get("CH4_ACCUMULATION_THRESHOLD", "0.15"))

    BTC_FEAR_GREED_URL: str = os.environ.get("BTC_FEAR_GREED_URL", "https://api.alternative.me/fng/")
    REGIME_DETECTOR_ENABLED: bool = os.environ.get("REGIME_DETECTOR_ENABLED", "true").lower() in ("true", "1", "yes")
    DEDUP_WINDOW_MINUTES: int = int(os.environ.get("DEDUP_WINDOW_MINUTES", "15"))
    LEVERAGE_MIN: int = 10
    LEVERAGE_MAX: int = 20
    DEFAULT_RISK_FRACTION: float = 0.01
    TP1_RR: float = 1.5
    TP2_RR: float = 2.5
    TP3_RR: float = 4.0
    MAX_SAME_SIDE_SIGNALS: int = 3
    STALE_SIGNAL_HOURS: int = int(os.environ.get("STALE_SIGNAL_HOURS", "4"))
    BE_TRIGGER_FRACTION: float = 0.50
    NEWS_SKIP_WINDOW_MINUTES: int = 60
    COINMARKETCAL_API_KEY: str = os.environ.get("COINMARKETCAL_API_KEY", "")
    SESSION_FILTER_ENABLED: bool = os.environ.get("SESSION_FILTER_ENABLED", "true").lower() in ("true", "1", "yes")
    SESSION_FILTER_CH1_ENABLED: bool = os.environ.get("SESSION_FILTER_CH1_ENABLED", "true").lower() in ("true", "1", "yes")
    SESSION_FILTER_CH2_ENABLED: bool = os.environ.get("SESSION_FILTER_CH2_ENABLED", "true").lower() in ("true", "1", "yes")
    SESSION_FILTER_CH3_ENABLED: bool = os.environ.get("SESSION_FILTER_CH3_ENABLED", "false").lower() in ("true", "1", "yes")
    SESSION_FILTER_CH4_ENABLED: bool = os.environ.get("SESSION_FILTER_CH4_ENABLED", "false").lower() in ("true", "1", "yes")

    FUNDING_RATE_GATE_ENABLED: bool = os.environ.get("FUNDING_RATE_GATE_ENABLED", "true").lower() in ("true", "1", "yes")
    FUNDING_EXTREME_NEGATIVE: float = float(os.environ.get("FUNDING_EXTREME_NEGATIVE", "-0.0001"))
    FUNDING_EXTREME_POSITIVE: float = float(os.environ.get("FUNDING_EXTREME_POSITIVE", "0.0005"))

    OI_MONITOR_ENABLED: bool = os.environ.get("OI_MONITOR_ENABLED", "true").lower() in ("true", "1", "yes")
    OI_CHANGE_THRESHOLD: float = float(os.environ.get("OI_CHANGE_THRESHOLD", "0.05"))

    LOSS_STREAK_THRESHOLD: int = int(os.environ.get("LOSS_STREAK_THRESHOLD", "3"))
    COOLDOWN_SIGNALS: int = int(os.environ.get("COOLDOWN_SIGNALS", "3"))
    COOLDOWN_HOURS: int = int(os.environ.get("COOLDOWN_HOURS", "24"))

    FEAR_GREED_INTERVAL_HOURS: int = int(os.environ.get("FEAR_GREED_INTERVAL_HOURS", "6"))
    DAILY_PERFORMANCE_HOUR: int = int(os.environ.get("DAILY_PERFORMANCE_HOUR", "23"))
    MIN_CONFLUENCE_SCORE: int = int(os.environ.get("MIN_CONFLUENCE_SCORE", "40"))
    MIN_DISPLACEMENT_PCT: float = float(os.environ.get("MIN_DISPLACEMENT_PCT", "0.15"))
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
    FUTURES_MIN_24H_VOLUME_USDT: int = int(os.environ.get("FUTURES_MIN_24H_VOLUME_USDT", "0"))
    FUTURES_SCAN_BATCH_SIZE: int = int(os.environ.get("FUTURES_SCAN_BATCH_SIZE", "20"))
    FUTURES_SCAN_BATCH_DELAY: float = float(os.environ.get("FUTURES_SCAN_BATCH_DELAY", "0.5"))
    SPOT_SCAN_ENABLED: bool = os.environ.get("SPOT_SCAN_ENABLED", "true").lower() in ("true", "1", "yes")
    SPOT_SCAN_INTERVAL_MINUTES: int = int(os.environ.get("SPOT_SCAN_INTERVAL_MINUTES", "60"))
    SPOT_MIN_24H_VOLUME_USDT: int = int(os.environ.get("SPOT_MIN_24H_VOLUME_USDT", "100000"))
    SPOT_GEM_VOLUME_SPIKE_RATIO: float = float(os.environ.get("SPOT_GEM_VOLUME_SPIKE_RATIO", "3.0"))
    SPOT_GEM_BREAKOUT_LOOKBACK_DAYS: int = int(os.environ.get("SPOT_GEM_BREAKOUT_LOOKBACK_DAYS", "30"))
    SPOT_GEM_ACCUMULATION_RANGE_PCT: float = float(os.environ.get("SPOT_GEM_ACCUMULATION_RANGE_PCT", "0.10"))
    SPOT_NEW_LISTING_LOOKBACK_DAYS: int = int(os.environ.get("SPOT_NEW_LISTING_LOOKBACK_DAYS", "90"))
    SPOT_SCAM_PUMP_THRESHOLD_PCT: float = float(os.environ.get("SPOT_SCAM_PUMP_THRESHOLD_PCT", "500.0"))
    SPOT_SCAM_CRASH_THRESHOLD_PCT: float = float(os.environ.get("SPOT_SCAM_CRASH_THRESHOLD_PCT", "50.0"))
    SPOT_SCAN_BATCH_SIZE: int = int(os.environ.get("SPOT_SCAN_BATCH_SIZE", "30"))
    SPOT_SCAN_BATCH_DELAY: float = float(os.environ.get("SPOT_SCAN_BATCH_DELAY", "0.5"))
    WHALE_ALERT_API_KEY: str = os.environ.get("WHALE_ALERT_API_KEY", "")
    COINGLASS_API_KEY: str = os.environ.get("COINGLASS_API_KEY", "")
    MIN_SIGNAL_GAP_SECONDS: int = int(os.environ.get("MIN_SIGNAL_GAP_SECONDS", "300"))
    ADMIN_ALERT_ENABLED: bool = os.environ.get("ADMIN_ALERT_ENABLED", "true").lower() in ("true", "1", "yes")
    ADMIN_ALERT_WIN_RATE_THRESHOLD: int = int(os.environ.get("ADMIN_ALERT_WIN_RATE_THRESHOLD", "40"))
    OI_DIVERGENCE_ENABLED: bool = os.environ.get("OI_DIVERGENCE_ENABLED", "true").lower() in ("true", "1", "yes")
    CHART_ENABLED: bool = os.environ.get("CHART_ENABLED", "true").lower() in ("true", "1", "yes")
    BRIEFING_ENABLED: bool = os.environ.get("BRIEFING_ENABLED", "true").lower() in ("true", "1", "yes")
    BRIEFING_HOUR_UTC: int = int(os.environ.get("BRIEFING_HOUR_UTC", "8"))
    INVALIDATION_CHECK_ENABLED: bool = os.environ.get("INVALIDATION_CHECK_ENABLED", "true").lower() in ("true", "1", "yes")
    CORRELATION_ALERT_ENABLED: bool = os.environ.get("CORRELATION_ALERT_ENABLED", "true").lower() in ("true", "1", "yes")
    CORRELATION_MAX_SAME_GROUP: int = int(os.environ.get("CORRELATION_MAX_SAME_GROUP", "3"))
    DB_ARCHIVE_DAYS: int = int(os.environ.get("DB_ARCHIVE_DAYS", "90"))
    TIMEFRAMES: dict[str, int] = {"1D": 1440, "4H": 240, "15m": 15, "5m": 5}

