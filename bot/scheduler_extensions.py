"""
Scheduler Extensions
Exposes register_new_schedulers() to add APScheduler jobs for
CH6/CH8/CH9 and enhanced CH5/CH7 posts without modifying bot.py.

Usage in bot.py (or a follow-up integration):
    from bot.scheduler_extensions import register_new_schedulers
    register_new_schedulers(scheduler, bot_instance, exchange, dashboard, signal_tracker, signal_router)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # avoid hard import of apscheduler at module level

logger = logging.getLogger(__name__)

try:
    from config import (
        ALTGEM_SCAN_INTERVAL_HOURS,
        ALTSEASON_POST_INTERVAL_HOURS,
        EDUCATION_LESSON_HOUR_UTC,
        EDUCATION_PATTERN_HOUR_UTC,
        OI_HEATMAP_INTERVAL_HOURS,
        SECTOR_DASHBOARD_HOUR_UTC,
        TELEGRAM_CHANNEL_ID_ALTGEMS,
        TELEGRAM_CHANNEL_ID_EDUCATION,
        TELEGRAM_CHANNEL_ID_INSIGHTS,
        TELEGRAM_CHANNEL_ID_VIP,
        TELEGRAM_CHANNEL_ID_WHALE,
    )
except Exception:  # pragma: no cover
    ALTGEM_SCAN_INTERVAL_HOURS = 2
    ALTSEASON_POST_INTERVAL_HOURS = 6
    EDUCATION_LESSON_HOUR_UTC = 10
    EDUCATION_PATTERN_HOUR_UTC = 16
    OI_HEATMAP_INTERVAL_HOURS = 4
    SECTOR_DASHBOARD_HOUR_UTC = 12
    TELEGRAM_CHANNEL_ID_ALTGEMS = 0
    TELEGRAM_CHANNEL_ID_EDUCATION = 0
    TELEGRAM_CHANNEL_ID_INSIGHTS = 0
    TELEGRAM_CHANNEL_ID_VIP = 0
    TELEGRAM_CHANNEL_ID_WHALE = 0

# ── Shared symbol lists for scheduler jobs ────────────────────────────────────
# Used by altseason index and OI heatmap jobs. Extracted here to avoid
# duplication and make maintenance easier.
ALT_PROXY_SYMBOLS: list[str] = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]
OI_HEATMAP_SYMBOLS: list[str] = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]


def register_new_schedulers(
    scheduler: Any,
    bot_instance: Any,
    exchange: Any,
    dashboard: Any,
    signal_tracker: Any,
    signal_router: Any,
) -> None:
    """
    Register APScheduler jobs for new channels (CH6/CH8/CH9) and
    enhanced CH5/CH7 posts.

    All jobs are guarded: they only run if the corresponding channel ID != 0.
    This function is designed to be called from bot.py after the main
    scheduler jobs are already registered.

    Parameters
    ----------
    scheduler:
        An APScheduler AsyncIOScheduler (or BackgroundScheduler) instance.
    bot_instance:
        The Telegram Bot instance used for sending messages.
    exchange:
        ResilientExchange instance for market data fetching.
    dashboard:
        Dashboard instance for performance data.
    signal_tracker:
        SignalTracker instance for active signal data.
    signal_router:
        SignalRouter instance for channel routing.
    """
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    # ── CH6 Altcoin Gems — every N hours ─────────────────────────────────────
    if TELEGRAM_CHANNEL_ID_ALTGEMS != 0:
        scheduler.add_job(
            _job_altgem_scan,
            trigger=IntervalTrigger(hours=ALTGEM_SCAN_INTERVAL_HOURS),
            id="ch6_altgem_scan",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_ALTGEMS,
            },
        )
        logger.info(
            "Registered CH6 altgem scan job (every %dh)", ALTGEM_SCAN_INTERVAL_HOURS
        )

    # ── CH8 Education — daily lesson at lesson_hour UTC ──────────────────────
    if TELEGRAM_CHANNEL_ID_EDUCATION != 0:
        scheduler.add_job(
            _job_education_lesson,
            trigger=CronTrigger(hour=EDUCATION_LESSON_HOUR_UTC, minute=0),
            id="ch8_education_lesson",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "channel_id": TELEGRAM_CHANNEL_ID_EDUCATION,
            },
        )
        scheduler.add_job(
            _job_education_pattern,
            trigger=CronTrigger(hour=EDUCATION_PATTERN_HOUR_UTC, minute=0),
            id="ch8_education_pattern",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_EDUCATION,
            },
        )
        logger.info(
            "Registered CH8 education jobs (lesson@%d:00 UTC, pattern@%d:00 UTC)",
            EDUCATION_LESSON_HOUR_UTC,
            EDUCATION_PATTERN_HOUR_UTC,
        )

    # ── CH5 Enhanced — Altseason Index every 6h ───────────────────────────────
    if TELEGRAM_CHANNEL_ID_INSIGHTS != 0:
        scheduler.add_job(
            _job_altseason_index,
            trigger=IntervalTrigger(hours=ALTSEASON_POST_INTERVAL_HOURS),
            id="ch5_altseason_index",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_INSIGHTS,
            },
        )
        scheduler.add_job(
            _job_sector_dashboard,
            trigger=CronTrigger(hour=SECTOR_DASHBOARD_HOUR_UTC, minute=0),
            id="ch5_sector_dashboard",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_INSIGHTS,
            },
        )
        scheduler.add_job(
            _job_oi_heatmap,
            trigger=IntervalTrigger(hours=OI_HEATMAP_INTERVAL_HOURS),
            id="ch5_oi_heatmap",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_INSIGHTS,
            },
        )
        logger.info(
            "Registered CH5 enhanced jobs: altseason/%dh, sector@%d:00 UTC, OI/%dh",
            ALTSEASON_POST_INTERVAL_HOURS,
            SECTOR_DASHBOARD_HOUR_UTC,
            OI_HEATMAP_INTERVAL_HOURS,
        )

    logger.info("scheduler_extensions: all new scheduler jobs registered")


# ── Job implementations ───────────────────────────────────────────────────────


async def _job_altgem_scan(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: scan for altcoin gems and post to CH6."""
    if channel_id == 0:
        return
    try:
        from bot.channels.altgem_scanner import (
            SECTORS,
            calculate_sector_returns,
            format_sector_rotation,
        )

        # Fetch ticker data for sector tokens
        sector_returns: dict[str, dict[str, float]] = {}
        for sector, tokens in SECTORS.items():
            token_rets: dict[str, float] = {}
            for token in tokens:
                symbol = token + "USDT"
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    if ticker:
                        token_rets[token] = float(ticker.get("percentage", 0) or 0)
                except Exception:
                    pass
            sector_returns[sector] = token_rets

        sector_avg = calculate_sector_returns(sector_returns)
        if sector_avg:
            msg = format_sector_rotation(sector_avg)
            await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH6 altgem scan job failed: %s", exc)


async def _job_education_lesson(bot_instance: Any, channel_id: int) -> None:
    """Scheduled job: post daily trading lesson to CH8."""
    if channel_id == 0:
        return
    try:
        from bot.channels.education import format_lesson_message, get_next_lesson

        lesson, lesson_num = get_next_lesson()
        msg = format_lesson_message(lesson, lesson_number=lesson_num)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH8 education lesson job failed: %s", exc)


async def _job_education_pattern(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: post pattern of the day to CH8."""
    if channel_id == 0:
        return
    try:
        from bot.channels.education import detect_pattern_btc_4h, format_pattern_message

        candles_raw = await exchange.fetch_ohlcv("BTCUSDT", "4h", limit=20)
        candles = [
            {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in (candles_raw or [])
        ]
        pattern = detect_pattern_btc_4h(candles)
        msg = format_pattern_message(pattern)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH8 education pattern job failed: %s", exc)


async def _job_altseason_index(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: post altseason index to CH5."""
    if channel_id == 0:
        return
    try:
        from bot.insights.altseason_index import format_altseason_index

        btc_ticker = await exchange.fetch_ticker("BTCUSDT")
        btc_7d = float(btc_ticker.get("percentage", 0) or 0) if btc_ticker else 0.0

        # Sample alt returns from a small proxy set
        alt_returns = []
        for sym in ALT_PROXY_SYMBOLS:
            try:
                t = await exchange.fetch_ticker(sym)
                if t:
                    alt_returns.append(float(t.get("percentage", 0) or 0))
            except Exception:
                pass
        alt_avg = sum(alt_returns) / len(alt_returns) if alt_returns else 0.0

        msg = format_altseason_index(btc_7d, alt_avg)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH5 altseason index job failed: %s", exc)


async def _job_sector_dashboard(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: post sector dashboard to CH5."""
    if channel_id == 0:
        return
    try:
        from bot.channels.altgem_scanner import SECTORS, calculate_sector_returns
        from bot.insights.sector_dashboard import format_sector_dashboard

        sector_returns: dict[str, dict[str, float]] = {}
        for sector, tokens in SECTORS.items():
            token_rets: dict[str, float] = {}
            for token in tokens:
                symbol = token + "USDT"
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    if ticker:
                        token_rets[token] = float(ticker.get("percentage", 0) or 0)
                except Exception:
                    pass
            sector_returns[sector] = token_rets

        sector_avg = calculate_sector_returns(sector_returns)
        msg = format_sector_dashboard(sector_avg)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH5 sector dashboard job failed: %s", exc)


async def _job_oi_heatmap(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: post OI heatmap to CH5."""
    if channel_id == 0:
        return
    try:
        from bot.insights.oi_heatmap import format_oi_heatmap

        # Fetch OI change proxy using 24h volume change
        oi_changes: dict[str, float] = {}
        for sym in OI_HEATMAP_SYMBOLS:
            try:
                ticker = await exchange.fetch_ticker(sym)
                if ticker:
                    oi_changes[sym] = float(ticker.get("percentage", 0) or 0)
            except Exception:
                pass

        msg = format_oi_heatmap(oi_changes)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH5 OI heatmap job failed: %s", exc)
