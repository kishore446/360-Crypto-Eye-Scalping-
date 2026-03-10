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

# Interval constants for new channel jobs
_WHALE_ALERT_INTERVAL_HOURS = 4
_VIP_BRIEFING_HOUR_UTC = 8  # Daily VIP briefing at 08:00 UTC

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

    # ── CH7 Whale — periodic OI + liquidation summary ─────────────────────────
    if TELEGRAM_CHANNEL_ID_WHALE != 0:
        scheduler.add_job(
            _job_whale_alert,
            trigger=IntervalTrigger(hours=_WHALE_ALERT_INTERVAL_HOURS),
            id="ch7_whale_alert",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "channel_id": TELEGRAM_CHANNEL_ID_WHALE,
            },
        )
        logger.info(
            "Registered CH7 whale alert job (every %dh)", _WHALE_ALERT_INTERVAL_HOURS
        )

    # ── CH9 VIP — daily briefing ───────────────────────────────────────────────
    if TELEGRAM_CHANNEL_ID_VIP != 0:
        scheduler.add_job(
            _job_vip_briefing,
            trigger=CronTrigger(hour=_VIP_BRIEFING_HOUR_UTC, minute=0),
            id="ch9_vip_briefing",
            replace_existing=True,
            kwargs={
                "bot_instance": bot_instance,
                "exchange": exchange,
                "dashboard": dashboard,
                "channel_id": TELEGRAM_CHANNEL_ID_VIP,
            },
        )
        logger.info(
            "Registered CH9 VIP briefing job (@%d:00 UTC daily)", _VIP_BRIEFING_HOUR_UTC
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
            detect_dormant_awakening,
            format_sector_rotation,
        )

        # Fetch ticker data for sector tokens
        sector_returns: dict[str, dict[str, float]] = {}
        ticker_cache: dict[str, Any] = {}
        for sector, tokens in SECTORS.items():
            token_rets: dict[str, float] = {}
            for token in tokens:
                symbol = token + "USDT"
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    if ticker:
                        token_rets[token] = float(ticker.get("percentage", 0) or 0)
                        ticker_cache[token] = ticker
                except Exception:
                    pass
            sector_returns[sector] = token_rets

        # Post sector rotation summary
        sector_avg = calculate_sector_returns(sector_returns)
        if sector_avg:
            msg = format_sector_rotation(sector_avg)
            await bot_instance.send_message(chat_id=channel_id, text=msg)

        # Scan each sector token for dormant awakening gems
        gem_alerts_posted = 0
        for sector, tokens in SECTORS.items():
            for token in tokens:
                try:
                    ticker = ticker_cache.get(token)
                    if not ticker:
                        continue
                    volume_24h = float(ticker.get("quoteVolume", 0) or 0)
                    price = float(ticker.get("last", 0) or 0)
                    price_change_24h = float(ticker.get("percentage", 0) or 0)
                    # Fetch 20-period candles for average volume
                    symbol = token + "USDT"
                    candles_raw = await exchange.fetch_ohlcv(symbol, "1d", limit=22)
                    if not candles_raw or len(candles_raw) < 5:
                        continue
                    volumes = [float(c[5]) for c in candles_raw[:-1]]
                    avg_volume_20 = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0.0
                    current_volume = float(candles_raw[-1][5])
                    gem = detect_dormant_awakening(
                        symbol=token,
                        volume_24h_usdt=volume_24h,
                        current_volume=current_volume,
                        avg_volume_20=avg_volume_20,
                        price=price,
                        price_change_24h=price_change_24h,
                    )
                    if gem is not None:
                        alert_msg = gem.format_message()
                        await bot_instance.send_message(chat_id=channel_id, text=alert_msg)
                        gem_alerts_posted += 1
                except Exception as _gem_exc:
                    logger.debug("Altgem scan skipped %s: %s", token, _gem_exc)

        if gem_alerts_posted:
            logger.info("CH6 altgem scan: posted %d gem alerts", gem_alerts_posted)
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


async def _job_whale_alert(
    bot_instance: Any, exchange: Any, channel_id: int
) -> None:
    """Scheduled job: post OI + price change summary to CH7 (Whale Tracker)."""
    if channel_id == 0:
        return
    try:
        from bot.insights.oi_heatmap import format_oi_heatmap

        oi_changes: dict[str, float] = {}
        price_changes: dict[str, float] = {}
        volumes: dict[str, float] = {}

        for sym in OI_HEATMAP_SYMBOLS:
            try:
                ticker = await exchange.fetch_ticker(sym)
                if ticker:
                    oi_changes[sym] = float(ticker.get("percentage", 0) or 0)
                    price_changes[sym] = float(ticker.get("percentage", 0) or 0)
                    volumes[sym] = float(ticker.get("quoteVolume", 0) or 0)
            except Exception:
                pass

        # Identify top movers (absolute % change)
        sorted_movers = sorted(
            price_changes.items(), key=lambda x: abs(x[1]), reverse=True
        )[:5]

        lines = ["🐋 WHALE TRACKER — OI & Volume Summary\n"]
        for sym, chg in sorted_movers:
            vol_m = volumes.get(sym, 0) / 1_000_000
            arrow = "📈" if chg >= 0 else "📉"
            base = sym.replace("USDT", "")
            lines.append(f"{arrow} {base}: {chg:+.2f}% | Vol ${vol_m:.1f}M")

        # Append full OI heatmap
        oi_msg = format_oi_heatmap(oi_changes)
        full_msg = "\n".join(lines) + "\n\n" + oi_msg
        await bot_instance.send_message(chat_id=channel_id, text=full_msg)
    except Exception as exc:
        logger.warning("CH7 whale alert job failed: %s", exc)


async def _job_vip_briefing(
    bot_instance: Any, exchange: Any, dashboard: Any, channel_id: int
) -> None:
    """Scheduled job: post daily VIP briefing to CH9."""
    if channel_id == 0:
        return
    try:
        import datetime

        lines = [
            "👑 VIP DAILY BRIEFING",
            f"📅 {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "─────────────────────────────",
        ]

        # Market regime
        try:
            from bot.state import get_bot_state

            state = get_bot_state()
            regime = getattr(state, "market_regime", "UNKNOWN")
            lines.append(f"📊 Regime: {regime}")
        except Exception:
            lines.append("📊 Regime: UNKNOWN")

        # BTC snapshot
        try:
            btc = await exchange.fetch_ticker("BTCUSDT")
            if btc:
                btc_price = float(btc.get("last", 0) or 0)
                btc_chg = float(btc.get("percentage", 0) or 0)
                arrow = "📈" if btc_chg >= 0 else "📉"
                lines.append(f"{arrow} BTC: ${btc_price:,.0f} ({btc_chg:+.2f}%)")
        except Exception:
            pass

        # ETH snapshot
        try:
            eth = await exchange.fetch_ticker("ETHUSDT")
            if eth:
                eth_price = float(eth.get("last", 0) or 0)
                eth_chg = float(eth.get("percentage", 0) or 0)
                arrow = "📈" if eth_chg >= 0 else "📉"
                lines.append(f"{arrow} ETH: ${eth_price:,.0f} ({eth_chg:+.2f}%)")
        except Exception:
            pass

        lines.append("─────────────────────────────")

        # Performance stats from dashboard
        try:
            total = dashboard.total_trades() if hasattr(dashboard, "total_trades") else 0
            wr = dashboard.win_rate() if hasattr(dashboard, "win_rate") else 0.0
            lines.append(f"📈 Win Rate: {wr:.1f}% | Trades: {total}")
        except Exception:
            lines.append("📈 Performance: N/A")

        lines.append("─────────────────────────────")
        lines.append("🔔 Stay disciplined. Follow the plan. Let edge play out.")

        msg = "\n".join(lines)
        await bot_instance.send_message(chat_id=channel_id, text=msg)
    except Exception as exc:
        logger.warning("CH9 VIP briefing job failed: %s", exc)
