"""
Telegram Bot — 360 Crypto Eye Scalping Signals
================================================
Implements all admin & user commands from Section IV of the master blueprint:

  /signal_gen        — Auto-scans and generates a formatted 360 Eye signal.
  /move_be           — Broadcasts "Move SL to Entry (Risk-Free Mode ON)."
  /trail_sl on|off   — Explicitly enable/disable trailing SL.
  /auto_scan on|off  — Explicitly enable/disable auto-scanner.
  /news_caution on|off — Explicitly enable/disable news freeze.
  /risk_calc         — Calculates exact position size from balance & SL distance.
  /status            — Show bot status dashboard.
  /health            — Show detailed health diagnostics.

The bot also handles incoming TradingView webhook payloads forwarded by
the Flask receiver (webhook.py) via the shared ``process_webhook`` function.

Required environment variable:
  TELEGRAM_BOT_TOKEN — Bot token issued by @BotFather.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import platform
import time
from typing import Optional

try:
    import resource as _resource
except ImportError:
    _resource = None  # type: ignore[assignment]

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from bot.auto_close_monitor import AutoCloseMonitor
from bot.backtester import Backtester, HistoricalDataFetcher
from bot.dashboard import Dashboard, TradeResult
from bot.exchange import _resilient_exchange, _spot_resilient_exchange
from bot.loss_streak_cooldown import CooldownManager
from bot.news_fetcher import fetch_and_reload
from bot.news_filter import NewsCalendar
from bot.risk_manager import RiskManager, calculate_position_size
from bot.signal_engine import (
    CandleData,
    Confidence,
    Side,
    SignalResult,
    run_confluence_check,
)
from bot.signal_router import ChannelTier, SignalRouter
from bot.signal_tracker import SignalTracker
from bot.spot_scanner import SpotScanner, validate_symbol
from bot.state import BotState
from bot.ws_manager import MarketDataStore, WebSocketManager
from config import (
    ADMIN_CHAT_ID,
    AUTO_SCAN_ENABLED_ON_BOOT,
    AUTO_SCAN_INTERVAL_SECONDS,
    AUTO_SCAN_PAIRS,
    BRIEFING_ENABLED,
    BRIEFING_HOUR_UTC,
    CH4_SCAN_INTERVAL_HOURS,
    CORRELATION_ALERT_ENABLED,
    CORRELATION_MAX_SAME_GROUP,
    DB_ARCHIVE_DAYS,
    FUTURES_SCAN_BATCH_DELAY,
    FUTURES_SCAN_BATCH_SIZE,
    MIN_SIGNAL_GAP_SECONDS,
    SPOT_SCAN_ENABLED,
    SPOT_SCAN_INTERVAL_MINUTES,
    STALE_SIGNAL_HOURS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_CHANNEL_ID_EASY,
    TELEGRAM_CHANNEL_ID_HARD,
    TELEGRAM_CHANNEL_ID_INSIGHTS,
    TELEGRAM_CHANNEL_ID_MEDIUM,
    TELEGRAM_CHANNEL_ID_SPOT,
)

logger = logging.getLogger(__name__)

# ── Shared state (singleton per process) ─────────────────────────────────────

risk_manager = RiskManager()
news_calendar = NewsCalendar()
dashboard = Dashboard()
signal_tracker = SignalTracker()
cooldown_manager = CooldownManager()

# Multi-channel signal router
signal_router = SignalRouter(
    channel_hard=TELEGRAM_CHANNEL_ID_HARD,
    channel_medium=TELEGRAM_CHANNEL_ID_MEDIUM,
    channel_easy=TELEGRAM_CHANNEL_ID_EASY,
    channel_spot=TELEGRAM_CHANNEL_ID_SPOT,
    channel_insights=TELEGRAM_CHANNEL_ID_INSIGHTS,
)

# Background scheduler — refreshes the news calendar every 30 minutes
_scheduler = BackgroundScheduler(daemon=True)

# Thread-safe bot state singleton
_bot_state = BotState()

# Futures market data store and manager (CH1/CH2/CH3)
futures_market_data = MarketDataStore(market_type="futures")
futures_ws = WebSocketManager(store=futures_market_data, market_type="futures")

# Backward-compatible aliases (used by existing code and tests)
market_data = futures_market_data
ws_manager = futures_ws

# Spot market data store and manager (CH4 spot scanner)
spot_market_data = MarketDataStore(market_type="spot")
spot_ws = WebSocketManager(store=spot_market_data, market_type="spot")

# Spot scanner instance
spot_scanner = SpotScanner(spot_market_data=spot_market_data)

# Rate limiting: track last broadcast time per channel tier
_last_signal_broadcast_time: dict[str, float] = {}

# Auto-close monitor — watches TP/SL hits for all active signals
auto_close_monitor = AutoCloseMonitor(
    signal_tracker=risk_manager,
    dashboard=dashboard,
    cooldown_manager=cooldown_manager,
    market_data_store=market_data,
    signal_router=signal_router,
    bot_state=_bot_state,
)

# Reference to the main asyncio event loop (set in build_application)
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# Boot time — used by /status and /health to compute uptime
_boot_time: float = time.time()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == ADMIN_CHAT_ID


async def _reply(update: Update, text: str, parse_mode: str = "Markdown") -> None:
    if update.message:
        await update.message.reply_text(text, parse_mode=parse_mode)


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send *text* to the primary Telegram channel (CH1 Hard or legacy fallback)."""
    channel_id = TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID
    if channel_id == 0:
        logger.debug("Skipping _broadcast — no channel ID configured.")
        return
    await context.bot.send_message(
        chat_id=channel_id,
        text=text,
        parse_mode="Markdown",
    )


async def _broadcast_to_channel(text: str, channel_id: int) -> None:
    """Send *text* to a specific Telegram channel ID using a fresh bot instance."""
    if channel_id == 0:
        logger.debug("Skipping broadcast — channel_id is 0 (not configured).")
        return
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="Markdown",
        )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_signal_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /signal_gen [SYMBOL] [LONG|SHORT]

    Admin-only: auto-scan the specified pair and broadcast a 360 Eye signal
    when all confluence conditions are met.

    Example:
        /signal_gen BTCUSDT LONG
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    if _bot_state.news_freeze:
        await _reply(update, "⚠️ Signal generation is currently *frozen* due to news caution mode.")
        return

    args = context.args or []
    if len(args) < 2:
        await _reply(update, "Usage: `/signal_gen SYMBOL LONG|SHORT`")
        return

    raw_symbol = args[0].upper()
    side_str = args[1].upper()
    if side_str not in ("LONG", "SHORT"):
        await _reply(update, "Side must be `LONG` or `SHORT`.")
        return
    side = Side(side_str)

    # Normalise to CCXT futures format, e.g. BTC/USDT:USDT
    ccxt_symbol = _normalise_symbol(raw_symbol)
    # Short name used in signal messages (e.g. "BTC")
    symbol = ccxt_symbol.split("/")[0]

    if not risk_manager.can_open_signal(side):
        await _reply(
            update,
            f"🚫 3-Pair Cap reached — cannot open another {side.value} signal.",
        )
        return

    try:
        candles = _fetch_binance_candles(ccxt_symbol, side)
    except Exception as exc:
        logger.error("Binance fetch failed for %s: %s", ccxt_symbol, exc)
        await _reply(update, f"⚠️ Failed to fetch market data for `{ccxt_symbol}`: {exc}")
        return

    result = run_confluence_check(
        symbol=symbol,
        current_price=candles["price"],
        side=side,
        range_low=candles["range_low"],
        range_high=candles["range_high"],
        key_liquidity_level=candles["key_level"],
        five_min_candles=candles["5m"],
        daily_candles=candles["1D"],
        four_hour_candles=candles["4H"],
        news_in_window=news_calendar.is_high_impact_imminent(),
        stop_loss=candles["stop_loss"],
    )

    if result is None:
        await _reply(update, f"❌ No valid setup found for #{symbol}/USDT {side.value}. Confluence checks failed.")
        return

    # Route to the correct channel based on confidence level
    if result.confidence == Confidence.HIGH:
        tier = ChannelTier.HARD
    elif result.confidence == Confidence.MEDIUM:
        tier = ChannelTier.MEDIUM
    else:
        tier = ChannelTier.EASY

    target_channel = signal_router.get_channel_id(tier)
    risk_manager.add_signal(result, origin_channel=target_channel)
    message = result.format_message()
    signal_router.record_signal(symbol, tier)

    if target_channel:
        await _broadcast_to_channel(message, target_channel)
    # Fallback to legacy channel if different
    if TELEGRAM_CHANNEL_ID and TELEGRAM_CHANNEL_ID != target_channel:
        await _broadcast(context, message)
    await _reply(update, f"✅ Signal broadcast for #{symbol}/USDT {side.value}.")
    logger.info("Signal generated: %s %s", symbol, side.value)


async def cmd_move_be(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /move_be [SYMBOL]

    Admin-only: broadcast "Move SL to Entry" for all (or a specific) open signal.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    symbol_filter = args[0].upper() if args else None

    targets = [
        s for s in risk_manager.active_signals
        if symbol_filter is None or s.result.symbol == symbol_filter
    ]

    if not targets:
        await _reply(update, "No open signals found.")
        return

    for sig in targets:
        if not sig.be_triggered:
            sig.trigger_be()
            # TP1 hit: record a partial WIN in the transparency dashboard
            pnl_pct = abs(sig.result.tp1 - sig.entry_mid) / sig.entry_mid * 100
            dashboard.record_result(
                TradeResult(
                    symbol=sig.result.symbol,
                    side=sig.result.side.value,
                    entry_price=sig.entry_mid,
                    exit_price=sig.result.tp1,
                    stop_loss=sig.result.stop_loss,
                    tp1=sig.result.tp1,
                    tp2=sig.result.tp2,
                    tp3=sig.result.tp3,
                    opened_at=sig.opened_at,
                    closed_at=time.time(),
                    outcome="WIN",
                    pnl_pct=round(pnl_pct, 4),
                    timeframe="5m",
                )
            )
        msg = (
            f"🔒 #{sig.result.symbol}/USDT {sig.result.side.value}: "
            f"Move SL to Entry **{sig.entry_mid:.4f}** (Risk-Free Mode ON)."
        )
        await _broadcast(context, msg)

    await _reply(update, f"BE broadcast sent for {len(targets)} signal(s).")


async def cmd_trail_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /trail_sl [on|off]

    Admin-only: explicitly enable or disable auto-trailing SL.
    With no argument, reports current state without changing it.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        state = "ACTIVE ✅" if _bot_state.trail_active else "INACTIVE ❌"
        await _reply(update, f"📈 Auto-Trailing SL is currently *{state}*.")
        return

    arg = args[0].lower()
    if arg == "on":
        _bot_state.trail_active = True
        msg = "📈 Auto-Trailing SL *ACTIVATED* ✅."
        await _broadcast(context, msg)
        await _reply(update, msg)
    elif arg == "off":
        _bot_state.trail_active = False
        msg = "📈 Auto-Trailing SL *DEACTIVATED* ❌."
        await _broadcast(context, msg)
        await _reply(update, msg)
    else:
        await _reply(update, "Usage: `/trail_sl on` or `/trail_sl off`")


async def cmd_auto_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /auto_scan [on|off]

    Admin-only: explicitly enable or disable the background auto-scanner.
    With no argument, reports current state without changing it.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        state = "ACTIVE ✅" if _bot_state.auto_scan_active else "INACTIVE ❌"
        mode = " (WebSocket mode)" if ws_manager.is_healthy() else " (fallback polling)"
        await _reply(update, f"🔍 Auto-Scanner is currently *{state}*{mode}.")
        return

    arg = args[0].lower()
    if arg == "on":
        _bot_state.auto_scan_active = True
        mode = "WebSocket" if ws_manager.is_healthy() else "fallback polling"
        msg = (
            f"🔍 Auto-Scanner *ACTIVATED* ✅ — {mode} mode, "
            f"monitoring {len(_dynamic_pairs)} pairs."
        )
        await _broadcast(context, msg)
        await _reply(update, msg)
    elif arg == "off":
        _bot_state.auto_scan_active = False
        msg = "🔍 Auto-Scanner *DEACTIVATED* ❌ — both WS-triggered and fallback scanning halted."
        await _broadcast(context, msg)
        await _reply(update, msg)
    else:
        await _reply(update, "Usage: `/auto_scan on` or `/auto_scan off`")


async def cmd_news_caution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /news_caution [on|off]

    Admin-only: explicitly enable or disable news-freeze mode.
    With no argument, reports current state without changing it.
    When activated:
      • New signals are blocked.
      • A partial-close recommendation is broadcast to the channel.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        state = "ACTIVE ✅" if _bot_state.news_freeze else "INACTIVE ❌"
        await _reply(update, f"⚠️ News Caution Mode is currently *{state}*.")
        return

    arg = args[0].lower()
    if arg == "on":
        _bot_state.news_freeze = True
        active_list = "\n".join(
            f"  • #{s.result.symbol}/USDT {s.result.side.value}"
            for s in risk_manager.active_signals
        ) or "  (none)"
        msg = (
            "⚠️ *NEWS CAUTION MODE ACTIVATED*\n\n"
            "🚫 New signals are FROZEN until further notice.\n\n"
            "📌 Active signals — consider closing partials:\n"
            f"{active_list}\n\n"
            + news_calendar.format_caution_message()
        )
        await _broadcast(context, msg)
        await _reply(update, msg)
    elif arg == "off":
        _bot_state.news_freeze = False
        msg = "✅ *News Caution Mode DEACTIVATED.* Signal generation is now active."
        await _broadcast(context, msg)
        await _reply(update, msg)
    else:
        await _reply(update, "Usage: `/news_caution on` or `/news_caution off`")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /status

    Admin-only: show a comprehensive status dashboard of all bot systems.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    auto_scan_label = "ACTIVE ✅" if _bot_state.auto_scan_active else "INACTIVE ❌"
    ws_mode = " (WebSocket mode)" if ws_manager.is_healthy() else " (fallback polling)"
    news_label = "ACTIVE ✅" if _bot_state.news_freeze else "INACTIVE ❌"

    # ── Trailing SL label (Bug 4) ─────────────────────────────────────────────
    trail_label = "ACTIVE ✅" if _bot_state.trail_active else "INACTIVE ❌"
    signals_with_trail = 0
    for sig in risk_manager.active_signals:
        sig_state = signal_tracker._state.get(
            getattr(sig.result, "signal_id", ""), {}
        )
        if sig_state.get("trailing_stop_loss") is not None:
            signals_with_trail += 1
    if signals_with_trail > 0:
        trail_label += (
            f" ({signals_with_trail} signal"
            f"{'s' if signals_with_trail != 1 else ''} trailing)"
        )

    ws_conn = "Connected ✅" if ws_manager.is_connected else "Disconnected ❌"
    if ws_manager.last_message_at > 0.0:
        ws_age = int(time.monotonic() - ws_manager.last_message_at)
        ws_conn += f" (last msg {ws_age}s ago)"

    uptime_secs = int(time.time() - _boot_time)
    hours, rem = divmod(uptime_secs, 3600)
    minutes, _ = divmod(rem, 60)

    # ── Per-channel active signal breakdown (Bug 2) ───────────────────────────
    active_sigs = risk_manager.active_signals
    total_active = len(active_sigs)
    channel_counts: dict[str, int] = {"Hard": 0, "Medium": 0, "Easy": 0, "Spot": 0, "Other": 0}
    for sig in active_sigs:
        ch = sig.origin_channel
        if ch and ch == signal_router.get_channel_id(ChannelTier.HARD):
            channel_counts["Hard"] += 1
        elif ch and ch == signal_router.get_channel_id(ChannelTier.MEDIUM):
            channel_counts["Medium"] += 1
        elif ch and ch == signal_router.get_channel_id(ChannelTier.EASY):
            channel_counts["Easy"] += 1
        elif ch and ch == signal_router.get_channel_id(ChannelTier.SPOT):
            channel_counts["Spot"] += 1
        else:
            channel_counts["Other"] += 1
    active_breakdown = (
        f"  🔴 Hard: {channel_counts['Hard']} | "
        f"🟡 Medium: {channel_counts['Medium']} | "
        f"🔵 Easy: {channel_counts['Easy']} | "
        f"💎 Spot: {channel_counts['Spot']}"
    )

    # ── Performance stats (Bug 3) ─────────────────────────────────────────────
    total_closed = dashboard.total_trades()
    perf_section = ""
    if total_closed > 0:
        win_rate_all = dashboard.win_rate()
        protected_wr_all = dashboard.protected_win_rate()
        pf = dashboard.profit_factor()
        perf_section = (
            f"\n📊 *Performance:*\n"
            f"  Total Closed: {total_closed}\n"
            f"  Win Rate: {win_rate_all:.1f}%\n"
            f"  Protected Win Rate: {protected_wr_all:.1f}% (BE counted as win)\n"
            f"  Profit Factor: {pf:.2f}\n"
        )
        ch_stats = dashboard.per_channel_stats()
        for tier_key, label in [
            ("CH1_HARD", "Hard"),
            ("CH2_MEDIUM", "Medium"),
            ("CH3_EASY", "Easy"),
            ("CH4_SPOT", "Spot"),
        ]:
            s = ch_stats.get(tier_key, {})
            if s.get("total_signals", 0) > 0:
                perf_section += (
                    f"  {label}: {s['win_rate']:.1f}% WR | "
                    f"{s['protected_win_rate']:.1f}% Safe WR "
                    f"({s['total_signals']} signals)\n"
                )

    msg = (
        "📊 *360 Crypto Eye — Status Dashboard*\n\n"
        f"🔍 Auto-Scanner: {auto_scan_label}{ws_mode}\n"
        f"📈 Trailing SL: {trail_label}\n"
        f"⚠️ News Caution: {news_label}\n"
        f"📡 WebSocket: {ws_conn}\n"
        f"📋 Scan Pairs: {len(_dynamic_pairs)} loaded\n"
        f"📌 Active Signals: {total_active} open\n"
        f"{active_breakdown}\n"
        f"🌍 Market Regime: {_bot_state.market_regime}\n"
        f"🕐 Uptime: {hours}h {minutes}m\n"
        f"{perf_section}\n"
        f"📢 Channel IDs:\n"
        f"  CH1 Hard:    {signal_router.get_channel_id(ChannelTier.HARD) or 'not set'}\n"
        f"  CH2 Medium:  {signal_router.get_channel_id(ChannelTier.MEDIUM) or 'not set'}\n"
        f"  CH3 Easy:    {signal_router.get_channel_id(ChannelTier.EASY) or 'not set'}\n"
        f"  CH4 Spot:    {signal_router.get_channel_id(ChannelTier.SPOT) or 'not set'}\n"
        f"  CH5 Insights:{signal_router.get_channel_id(ChannelTier.INSIGHTS) or 'not set'}"
    )
    await _reply(update, msg)


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /health

    Admin-only: show detailed technical diagnostics.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    ws_conn = "Connected ✅" if ws_manager.is_connected else "Disconnected ❌"
    if ws_manager.last_message_at > 0.0:
        ws_age = round(time.monotonic() - ws_manager.last_message_at, 1)
    else:
        ws_age = None
    ws_tasks = len(ws_manager._tasks)

    scheduler_running = _scheduler.running
    jobs = _scheduler.get_jobs()
    job_lines = "\n".join(f"   - {j.id}" for j in jobs) if jobs else "   (none)"

    if _resource is not None:
        rss = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
        # Linux: ru_maxrss is in KiB; macOS: ru_maxrss is in bytes
        divisor = 1024 if platform.system() != "Darwin" else (1024 * 1024)
        mem_str = f"{rss / divisor:.1f} MiB"
    else:
        mem_str = "N/A"

    auto_scan_label = "ACTIVE ✅" if _bot_state.auto_scan_active else "INACTIVE ❌"
    trail_label = "ACTIVE ✅" if _bot_state.trail_active else "INACTIVE ❌"
    news_label = "ACTIVE ✅" if _bot_state.news_freeze else "INACTIVE ❌"

    ws_detail = f"📡 WebSocket: {ws_conn}\n"
    if ws_age is not None:
        ws_detail += f"   Last message: {ws_age}s ago\n"
    ws_detail += f"   Connections: {ws_tasks} active\n"

    scheduler_status = "Running" if scheduler_running else "Stopped"
    sched_detail = (
        f"🔄 Scheduler: {scheduler_status} ({len(jobs)} jobs)\n"
        f"{job_lines}\n"
    )

    msg = (
        "🏥 *360 Crypto Eye — Health Check*\n\n"
        "🟢 Bot Process: Running\n"
        + ws_detail
        + sched_detail
        + f"💾 Memory: {mem_str}\n"
        f"📊 Active Signals: {len(risk_manager.active_signals)}\n"
        f"🔍 Auto-Scanner: {auto_scan_label}\n"
        f"📈 Trailing SL: {trail_label}\n"
        f"⚠️ News Freeze: {news_label}"
    )
    await _reply(update, msg)


async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /regime

    Admin-only: show the current market regime (BULL/BEAR/SIDEWAYS) and
    its effect on signal generation.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    regime = _bot_state.market_regime
    regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "SIDEWAYS": "🟡"}.get(regime, "⚪")

    if regime == "BEAR":
        effect = "⚠️ LONG signals are SUPPRESSED on CH1 and CH2. SHORT setups only."
    elif regime == "BULL":
        effect = "✅ All signal directions active. Bias favors LONG setups."
    elif regime == "SIDEWAYS":
        effect = "ℹ️ Both directions active. Trade setups evaluated on their own merit."
    else:
        effect = "ℹ️ Regime not yet determined (regime detector runs at 09:00 UTC)."

    msg = (
        f"🌍 *Market Regime: {regime} {regime_emoji}*\n\n"
        f"{effect}\n\n"
        f"CH1 Hard Scalp:  {'LONGS SUPPRESSED' if regime == 'BEAR' else 'active'}\n"
        f"CH2 Medium Scalp: {'LONGS SUPPRESSED' if regime == 'BEAR' else 'active'}\n"
        f"CH3 Easy Breakout: always active (regime-independent)\n"
        f"CH4 Spot Momentum: always active (regime-independent)"
    )
    await _reply(update, msg)


async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /channels

    Admin-only: show all 5 channel IDs and their status.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    def _ch_status(tier: ChannelTier) -> str:
        cid = signal_router.get_channel_id(tier)
        if cid == 0:
            return "NOT CONFIGURED ❌"
        return f"ID: `{cid}` ✅"

    msg = (
        "📢 *360 Crypto Eye — Channel Status*\n\n"
        f"CH1 Hard Scalp:    {_ch_status(ChannelTier.HARD)}\n"
        f"CH2 Medium Scalp:  {_ch_status(ChannelTier.MEDIUM)}\n"
        f"CH3 Easy Breakout: {_ch_status(ChannelTier.EASY)}\n"
        f"CH4 Spot Momentum: {_ch_status(ChannelTier.SPOT)}\n"
        f"CH5 Insights:      {_ch_status(ChannelTier.INSIGHTS)}"
    )
    await _reply(update, msg)


async def cmd_risk_calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /risk_calc <balance> <entry> <stop_loss>

    User command: calculate exact position size.

    Example:
        /risk_calc 1000 65000 64000
    """
    args = context.args or []
    if len(args) < 3:
        await _reply(update, "Usage: `/risk_calc <balance_usdt> <entry_price> <stop_loss_price>`")
        return

    try:
        balance = float(args[0])
        entry = float(args[1])
        sl = float(args[2])
    except ValueError:
        await _reply(update, "⚠️ All three values must be numbers.")
        return

    try:
        calc = calculate_position_size(balance, entry, sl)
    except ValueError as exc:
        await _reply(update, f"⚠️ {exc}")
        return

    reply = (
        "🧮 *360 Eye Position Size Calculator*\n\n"
        f"Account Balance  : ${balance:,.2f} USDT\n"
        f"Entry Price      : ${entry:,.4f}\n"
        f"Stop Loss Price  : ${sl:,.4f}\n"
        f"SL Distance      : {calc['sl_distance_pct']:.4f}%\n\n"
        f"Risk Amount (1%) : ${calc['risk_amount']:,.4f} USDT\n"
        f"Position Size    : ${calc['position_size_usdt']:,.4f} USDT\n"
        f"Position (Units) : {calc['position_size_units']:,.6f} coins"
    )
    await _reply(update, reply)


# ── Background trailing SL job ────────────────────────────────────────────────

def _run_trailing_sl_job(context_or_bot=None) -> None:
    """
    APScheduler background job — runs every 60 s when ``_trail_active`` is True.

    For each open signal:
      • LONG  → trail SL to the minimum low of the last 3 × 5m candles
                (Higher Low); only moves SL *upward*.
      • SHORT → trail SL to the maximum high of the last 3 × 5m candles
                (Lower High); only moves SL *downward*.

    Broadcasts a Telegram message for each SL update to the channel
    that originated the signal (``sig.origin_channel``), falling back
    to ``TELEGRAM_CHANNEL_ID`` for signals without an origin channel.
    """
    if not _bot_state.trail_active:
        return

    updates: list[tuple[str, int]] = []  # (message_text, target_channel_id)
    for sig in list(risk_manager.active_signals):
        symbol_base = sig.result.symbol  # e.g. "BTC"
        ccxt_symbol = f"{symbol_base}/USDT:USDT"

        # Prefer in-memory WS buffer; fall back to REST if empty
        raw_5m_rows = market_data.get_candles(symbol_base, "5m")
        if len(raw_5m_rows) < 3:
            try:
                raw_5m_rows = _resilient_exchange.fetch_ohlcv(ccxt_symbol, "5m", limit=5)
            except Exception as exc:
                logger.warning("Trailing SL fetch failed for %s: %s", symbol_base, exc)
                continue

        if len(raw_5m_rows) < 3:
            continue

        last_3 = raw_5m_rows[-3:]
        current_sl = sig.result.stop_loss
        target_channel = sig.origin_channel if sig.origin_channel else (TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID)

        if sig.result.side == Side.LONG:
            # Per the spec: "Higher Low" = min low of the last 3 candles.
            # SL only moves up (never down) for LONG.
            new_sl = min(row[3] for row in last_3)
            if new_sl > current_sl:
                sig.result.stop_loss = new_sl
                updates.append((
                    f"📈 #{sig.result.symbol}/USDT LONG: "
                    f"Trailing SL raised {current_sl:.4f} → {new_sl:.4f} "
                    f"(Higher Low trail)",
                    target_channel,
                ))
        else:
            # Per the spec: "Lower High" = max high of the last 3 candles.
            # SL only moves down (never up) for SHORT.
            new_sl = max(row[2] for row in last_3)
            if new_sl < current_sl:
                sig.result.stop_loss = new_sl
                updates.append((
                    f"📉 #{sig.result.symbol}/USDT SHORT: "
                    f"Trailing SL lowered {current_sl:.4f} → {new_sl:.4f} "
                    f"(Lower High trail)",
                    target_channel,
                ))

    if not updates:
        return

    # Persist updated stop-losses via public API
    try:
        risk_manager.save()
    except Exception as exc:
        logger.error("Failed to persist trailing SL update: %s", exc)

    # Broadcast from background thread — use run_coroutine_threadsafe when main loop is available
    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            for text, chat_id in updates:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.error("Trailing SL broadcast error: %s", exc)

    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_send(), _main_loop)
    else:
        try:
            new_loop = asyncio.new_event_loop()
            new_loop.run_until_complete(_send())
        except Exception as exc:
            logger.error("Trailing SL job failed to send broadcasts: %s", exc)
        finally:
            new_loop.close()


# ── Stale signal cleanup job ──────────────────────────────────────────────────

def _run_stale_signal_job() -> None:
    """Auto-close signals open longer than STALE_SIGNAL_HOURS."""
    for sig in list(risk_manager.active_signals):
        if sig.is_stale():
            symbol = sig.result.symbol
            target_channel = sig.origin_channel if sig.origin_channel else (TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID)
            risk_manager.close_signal(symbol, reason="stale")
            signal_tracker.clear_signal(sig.result.signal_id)
            logger.info("Auto-closed stale signal: %s", symbol)

            async def _send(sym: str = symbol, chat_id: int = target_channel) -> None:
                async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"⏰ #{sym}/USDT signal auto-closed — *STALE* "
                            f"(exceeded {STALE_SIGNAL_HOURS}h limit)."
                        ),
                        parse_mode="Markdown",
                    )

            if _main_loop is not None and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(_send(), _main_loop)
            else:
                new_loop = asyncio.new_event_loop()
                try:
                    new_loop.run_until_complete(_send())
                finally:
                    new_loop.close()


# ── WebSocket candle-close callback (replaces _run_auto_scan_job) ─────────────

async def on_candle_close(base_symbol: str, timeframe: str) -> None:
    """
    Async callback fired by WebSocketManager every time a 5m candle closes.

    Checks open signal lifecycle events (TP/SL hits) for *base_symbol* first,
    then runs the full confluence engine if no signal is currently active.
    """
    _candle_close_ts = time.time()  # record when the candle-close event fires

    if not _bot_state.auto_scan_active:
        return

    if _bot_state.news_freeze or news_calendar.is_high_impact_imminent():
        return

    # Loss streak cooldown gate — skip signal generation during active cooldown
    if cooldown_manager.is_cooldown_active():
        logger.debug("on_candle_close: skipping %s — loss streak cooldown active.", base_symbol)
        return

    price = market_data.get_price(base_symbol)
    if price is None:
        return

    # ── Signal lifecycle tracking for the current symbol ─────────────────────
    active_for_symbol = [s for s in risk_manager.active_signals if s.result.symbol == base_symbol]
    for sig in active_for_symbol:
        messages = signal_tracker.check_signal(sig, price)
        for msg in messages:
            try:
                async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
                    await bot.send_message(
                        chat_id=sig.origin_channel or TELEGRAM_CHANNEL_ID,
                        text=msg,
                        parse_mode="Markdown",
                    )
            except Exception as exc:
                logger.error("Signal tracker broadcast error for %s: %s", base_symbol, exc)

            if "SL HIT" in msg:
                risk_manager.close_signal(base_symbol, reason="sl")
                signal_tracker.clear_signal(sig.result.signal_id)
                logger.info("Auto-closed signal on SL hit: %s", base_symbol)
                # Generate and broadcast postmortem analysis to CH5 Insights
                try:
                    from bot.dashboard import TradeResult as _TradeResult
                    from bot.postmortem import generate_postmortem
                    _pnl_pct = -(abs(sig.result.stop_loss - sig.entry_mid) / sig.entry_mid * 100)
                    _pm_result = _TradeResult(
                        symbol=sig.result.symbol,
                        side=sig.result.side.value,
                        entry_price=sig.entry_mid,
                        exit_price=sig.result.stop_loss,
                        stop_loss=sig.result.stop_loss,
                        tp1=sig.result.tp1,
                        tp2=sig.result.tp2,
                        tp3=sig.result.tp3,
                        opened_at=sig.opened_at,
                        closed_at=time.time(),
                        outcome="LOSS",
                        pnl_pct=round(_pnl_pct, 4),
                        timeframe="5m",
                        channel_tier="CH1_HARD",
                    )
                    _pm_msg = generate_postmortem(
                        trade_result=_pm_result,
                        gates_fired=["discount_zone", "liquidity_sweep", "market_structure_shift"],
                        regime=_bot_state.market_regime,
                        session="UNKNOWN",
                    )
                    _insights_id = signal_router.get_channel_id(ChannelTier.INSIGHTS)
                    if _insights_id:
                        await _broadcast_to_channel(_pm_msg, _insights_id)
                except Exception as _pm_exc:
                    logger.warning("Postmortem generation failed for %s: %s", base_symbol, _pm_exc)
            elif "TP3 HIT" in msg:
                risk_manager.close_signal(base_symbol, reason="tp3")
                signal_tracker.clear_signal(sig.result.signal_id)
                logger.info("Auto-closed signal on TP3 hit: %s", base_symbol)
            elif "TP1 HIT" in msg and not sig.be_triggered:
                sig.trigger_be()
                pnl_pct = abs(sig.result.tp1 - sig.entry_mid) / sig.entry_mid * 100
                dashboard.record_result(
                    TradeResult(
                        symbol=sig.result.symbol,
                        side=sig.result.side.value,
                        entry_price=sig.entry_mid,
                        exit_price=sig.result.tp1,
                        stop_loss=sig.result.stop_loss,
                        tp1=sig.result.tp1,
                        tp2=sig.result.tp2,
                        tp3=sig.result.tp3,
                        opened_at=sig.opened_at,
                        closed_at=time.time(),
                        outcome="WIN",
                        pnl_pct=round(pnl_pct, 4),
                        timeframe="5m",
                    )
                )
                logger.info("Auto-triggered BE on TP1 hit: %s", base_symbol)
                if not _bot_state.trail_active:
                    _bot_state.trail_active = True
                    logger.info("Auto-enabled trailing SL after TP1 hit: %s", base_symbol)

    if active_for_symbol:
        # Symbol already has an active signal — skip new signal generation.
        logger.debug("on_candle_close: skipping new signal for %s — signal already active.", base_symbol)
        return

    if not market_data.has_sufficient_data(base_symbol):
        logger.debug("on_candle_close: insufficient data for %s.", base_symbol)
        return

    candles_5m_raw = market_data.get_candles(base_symbol, "5m")
    candles_4h_raw = market_data.get_candles(base_symbol, "4h")
    candles_1d_raw = market_data.get_candles(base_symbol, "1d")
    candles_15m_raw = market_data.get_candles(base_symbol, "15m")

    def _to_candles(rows: list) -> list[CandleData]:
        return [
            CandleData(
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in rows
        ]

    four_h_candles = _to_candles(candles_4h_raw)
    daily_candles = _to_candles(candles_1d_raw)
    five_m_candles = _to_candles(candles_5m_raw)
    fifteen_m_candles = _to_candles(candles_15m_raw)

    # Fetch funding rate for score adjustment (best-effort; None on failure)
    try:
        from bot.funding_rate import fetch_funding_rate
        funding_rate = fetch_funding_rate(base_symbol)
    except Exception:
        funding_rate = None

    # range_low / range_high from last 10 4H candles
    recent_4h = four_h_candles[-10:] if len(four_h_candles) >= 10 else four_h_candles
    range_low = min(c.low for c in recent_4h) if recent_4h else price * 0.99
    range_high = max(c.high for c in recent_4h) if recent_4h else price * 1.01

    atr_proxy = (range_high - range_low) * 0.01

    # ── Session-aware signal quality gate ────────────────────────────────────
    try:
        from bot.session_filter import get_current_session as _get_session
        _current_session = _get_session()
        _session_map = {
            "LONDON": "LONDON",
            "NEW_YORK": "NYC",
            "LONDON+NYC_OVERLAP": "OVERLAP",
            "ASIA": "ASIA",
        }
        _dashboard_session = _session_map.get(_current_session, "UNKNOWN")
        _session_stats = dashboard.per_session_stats()
        _session_wr = _session_stats.get(_dashboard_session, {}).get("win_rate", 50.0)
        _session_total = _session_stats.get(_dashboard_session, {}).get("total_signals", 0)
    except Exception:
        _session_wr = 50.0
        _session_total = 0
        _dashboard_session = "UNKNOWN"

    for side in (Side.LONG, Side.SHORT):
        if not risk_manager.can_open_signal(side):
            continue

        recent_5m = five_m_candles[-10:] if len(five_m_candles) >= 10 else five_m_candles
        if side == Side.LONG:
            key_level = min(c.low for c in recent_5m) if recent_5m else price
        else:
            key_level = max(c.high for c in recent_5m) if recent_5m else price

        stop_loss = (
            key_level - atr_proxy if side == Side.LONG else key_level + atr_proxy
        )

        regime = _bot_state.market_regime

        # ── CH1 Hard Scalp ─────────────────────────────────────────────────
        try:
            from bot.channels import hard_scalp as _hard_scalp
            ch1_result = _hard_scalp.run(
                symbol=base_symbol,
                current_price=price,
                side=side,
                five_min_candles=five_m_candles,
                daily_candles=daily_candles,
                four_hour_candles=four_h_candles,
                news_calendar=news_calendar,
                risk_manager=risk_manager,
                range_low=range_low,
                range_high=range_high,
                key_liquidity_level=key_level,
                stop_loss=stop_loss,
                market_regime=regime,
                fifteen_min_candles=fifteen_m_candles,
                funding_rate=funding_rate,
            )
        except Exception as exc:
            logger.error("CH1 confluence error for %s %s: %s", base_symbol, side.value, exc)
            ch1_result = None

        # Session-aware quality gate: suppress LOW confidence signals during weak sessions
        if (
            ch1_result is not None
            and _session_total >= 10
            and _session_wr < 40.0
            and ch1_result.confidence == Confidence.LOW
        ):
            logger.info(
                "Suppressing LOW confidence CH1 signal for %s during weak session %s (WR=%.1f%%)",
                base_symbol, _dashboard_session, _session_wr,
            )
            ch1_result = None

        if ch1_result is not None and not signal_router.should_suppress_duplicate(base_symbol, ChannelTier.HARD):
            risk_manager.add_signal(ch1_result, origin_channel=signal_router.get_channel_id(ChannelTier.HARD), created_regime=regime)
            signal_router.record_signal(base_symbol, ChannelTier.HARD)
            # ── Correlation guard check ──────────────────────────────────────
            if CORRELATION_ALERT_ENABLED:
                from bot.correlation_guard import check_correlation_risk
                corr_warn = check_correlation_risk(risk_manager.active_signals, max_same_group=CORRELATION_MAX_SAME_GROUP)
                if corr_warn and ADMIN_CHAT_ID:
                    try:
                        async def _send_corr_alert(msg: str = corr_warn) -> None:
                            async with Bot(token=TELEGRAM_BOT_TOKEN) as _b:
                                await _b.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
                        await _send_corr_alert()
                    except Exception as _corr_exc:
                        logger.warning("Correlation alert DM failed: %s", _corr_exc)
            logger.info("CH1 signal: %s %s", base_symbol, side.value)
            _now = time.time()
            _tier_key = ChannelTier.HARD.value
            _last_broadcast = _last_signal_broadcast_time.get(_tier_key, 0.0)
            if _now - _last_broadcast >= MIN_SIGNAL_GAP_SECONDS:
                _last_signal_broadcast_time[_tier_key] = _now
                try:
                    await _broadcast_to_channel(ch1_result.format_message(), signal_router.get_channel_id(ChannelTier.HARD))
                    # Fallback: also send to legacy TELEGRAM_CHANNEL_ID if different
                    if TELEGRAM_CHANNEL_ID and TELEGRAM_CHANNEL_ID != signal_router.get_channel_id(ChannelTier.HARD):
                        await _broadcast_to_channel(ch1_result.format_message(), TELEGRAM_CHANNEL_ID)
                    _signal_broadcast_ts = time.time()
                    _delivery_latency_ms = int((_signal_broadcast_ts - _candle_close_ts) * 1000)
                    logger.info(
                        "signal_delivery_latency_ms=%d symbol=%s tier=CH1",
                        _delivery_latency_ms, base_symbol,
                    )
                    if _delivery_latency_ms > 10_000 and ADMIN_CHAT_ID:
                        try:
                            _lat_msg = (
                                f"⚠️ Signal delivery latency {_delivery_latency_ms}ms "
                                f"for {base_symbol} (CH1) — exceeds 10s threshold."
                            )
                            async def _send_latency_alert() -> None:
                                async with Bot(token=TELEGRAM_BOT_TOKEN) as _b:
                                    await _b.send_message(chat_id=ADMIN_CHAT_ID, text=_lat_msg)
                            await _send_latency_alert()
                        except Exception as _lat_exc:
                            logger.warning("Latency alert DM failed: %s", _lat_exc)
                    _bot_state.record_signal_generated()
                except Exception as exc:
                    logger.error("CH1 broadcast error for %s: %s", base_symbol, exc)
            else:
                logger.debug(
                    "CH1 signal rate-limited for %s — %ds since last broadcast (min gap %ds).",
                    base_symbol,
                    int(_now - _last_broadcast),
                    MIN_SIGNAL_GAP_SECONDS,
                )
            break  # one signal per symbol per candle close

        # ── CH2 Medium Scalp ───────────────────────────────────────────────
        if signal_router.is_channel_enabled(ChannelTier.MEDIUM):
            try:
                from bot.channels import medium_scalp as _medium_scalp
                ch2_result = _medium_scalp.run(
                    symbol=base_symbol,
                    current_price=price,
                    side=side,
                    five_min_candles=five_m_candles,
                    daily_candles=daily_candles,
                    four_hour_candles=four_h_candles,
                    news_calendar=news_calendar,
                    risk_manager=risk_manager,
                    range_low=range_low,
                    range_high=range_high,
                    key_liquidity_level=key_level,
                    stop_loss=stop_loss,
                    market_regime=regime,
                    fifteen_min_candles=fifteen_m_candles,
                    funding_rate=funding_rate,
                )
            except Exception as exc:
                logger.error("CH2 confluence error for %s %s: %s", base_symbol, side.value, exc)
                ch2_result = None

            if ch2_result is not None and not signal_router.should_suppress_duplicate(base_symbol, ChannelTier.MEDIUM):
                risk_manager.add_signal(ch2_result, origin_channel=signal_router.get_channel_id(ChannelTier.MEDIUM), created_regime=regime)
                signal_router.record_signal(base_symbol, ChannelTier.MEDIUM)
                logger.info("CH2 signal: %s %s", base_symbol, side.value)
                _now = time.time()
                _tier_key = ChannelTier.MEDIUM.value
                _last_broadcast = _last_signal_broadcast_time.get(_tier_key, 0.0)
                if _now - _last_broadcast >= MIN_SIGNAL_GAP_SECONDS:
                    _last_signal_broadcast_time[_tier_key] = _now
                    try:
                        await _broadcast_to_channel(ch2_result.format_message(), signal_router.get_channel_id(ChannelTier.MEDIUM))
                        _signal_broadcast_ts = time.time()
                        _delivery_latency_ms = int((_signal_broadcast_ts - _candle_close_ts) * 1000)
                        logger.info(
                            "signal_delivery_latency_ms=%d symbol=%s tier=CH2",
                            _delivery_latency_ms, base_symbol,
                        )
                        _bot_state.record_signal_generated()
                    except Exception as exc:
                        logger.error("CH2 broadcast error for %s: %s", base_symbol, exc)
                else:
                    logger.debug(
                        "CH2 signal rate-limited for %s — %ds since last broadcast.",
                        base_symbol,
                        int(_now - _last_broadcast),
                    )

        # ── CH3 Easy Breakout ──────────────────────────────────────────────
        if signal_router.is_channel_enabled(ChannelTier.EASY):
            try:
                from bot.channels import easy_breakout as _easy_breakout
                ch3_result = _easy_breakout.run(
                    symbol=base_symbol,
                    current_price=price,
                    five_min_candles=five_m_candles,
                    four_hour_candles=four_h_candles,
                )
            except Exception as exc:
                logger.error("CH3 breakout error for %s: %s", base_symbol, exc)
                ch3_result = None

            if ch3_result is not None and not signal_router.should_suppress_duplicate(base_symbol, ChannelTier.EASY):
                # Convert BreakoutResult → SignalResult for risk_manager compatibility.
                # entry_price is split into a ±0.5% zone; tp3 is extrapolated from tp1/tp2.
                _entry_low = ch3_result.entry_price * 0.995
                _entry_high = ch3_result.entry_price * 1.005
                _tp3 = ch3_result.tp2 + (ch3_result.tp2 - ch3_result.tp1)  # linear extrapolation
                ch3_signal_result = SignalResult(
                    symbol=base_symbol,
                    side=ch3_result.side,
                    confidence=Confidence.LOW,
                    entry_low=_entry_low,
                    entry_high=_entry_high,
                    tp1=ch3_result.tp1,
                    tp2=ch3_result.tp2,
                    tp3=_tp3,
                    stop_loss=ch3_result.stop_loss,
                    structure_note="",
                    context_note="",
                    leverage_min=3,
                    leverage_max=5,
                )
                try:
                    risk_manager.add_signal(
                        ch3_signal_result,
                        origin_channel=signal_router.get_channel_id(ChannelTier.EASY),
                        created_regime=regime,
                    )
                    signal_router.record_signal(base_symbol, ChannelTier.EASY)
                except RuntimeError as _cap_exc:
                    logger.warning("CH3 3-pair cap reached for %s: %s", base_symbol, _cap_exc)
                    return
                except Exception as _add_exc:
                    logger.error("CH3 signal registration error for %s: %s", base_symbol, _add_exc)
                    return
                logger.info("CH3 breakout: %s %s", base_symbol, ch3_result.side.value)
                _now = time.time()
                _tier_key = ChannelTier.EASY.value
                _last_broadcast = _last_signal_broadcast_time.get(_tier_key, 0.0)
                if _now - _last_broadcast >= MIN_SIGNAL_GAP_SECONDS:
                    _last_signal_broadcast_time[_tier_key] = _now
                    try:
                        await _broadcast_to_channel(ch3_result.format_message(), signal_router.get_channel_id(ChannelTier.EASY))
                        _signal_broadcast_ts = time.time()
                        _delivery_latency_ms = int((_signal_broadcast_ts - _candle_close_ts) * 1000)
                        logger.info(
                            "signal_delivery_latency_ms=%d symbol=%s tier=CH3",
                            _delivery_latency_ms, base_symbol,
                        )
                        _bot_state.record_signal_generated()
                    except Exception as exc:
                        logger.error("CH3 broadcast error for %s: %s", base_symbol, exc)
                else:
                    logger.debug(
                        "CH3 signal rate-limited for %s — %ds since last broadcast.",
                        base_symbol,
                        int(_now - _last_broadcast),
                    )


# ── Fallback polling scan (runs only when WebSocket stream is unhealthy) ────────

def _fallback_to_candles(rows: list) -> list[CandleData]:
    """Convert raw OHLCV rows to CandleData objects."""
    return [
        CandleData(
            open=row[1], high=row[2], low=row[3], close=row[4], volume=row[5],
        )
        for row in rows
    ]


def _run_fallback_scan_job() -> None:
    """
    APScheduler synchronous job: lightweight fallback scan across all
    monitored pairs in batches.

    Runs the same per-symbol confluence path as ``on_candle_close`` but is
    triggered by the scheduler rather than a WS candle-close event.  The
    job is a no-op when the WebSocket stream is healthy or when auto-scan
    is inactive, preventing duplicate signal generation.

    When the WS is unhealthy, fresh candle data is fetched via REST before
    running the confluence check to avoid operating on stale data.
    Pairs are scanned in batches of FUTURES_SCAN_BATCH_SIZE with a small
    sleep between batches to respect Binance API rate limits.
    """
    if not _bot_state.auto_scan_active:
        return

    if ws_manager.is_healthy():
        # WS is live — primary path is active, skip fallback
        return

    pairs = list(_dynamic_pairs)
    logger.info("Fallback scan: WS unhealthy — running poll-based scan for %d pairs.", len(pairs))

    for batch_start in range(0, len(pairs), FUTURES_SCAN_BATCH_SIZE):
        batch = pairs[batch_start : batch_start + FUTURES_SCAN_BATCH_SIZE]
        for base_symbol in batch:
            try:
                if _bot_state.news_freeze or news_calendar.is_high_impact_imminent():
                    return  # news freeze applies globally; exit the entire scan

                active_symbols = {sig.result.symbol for sig in risk_manager.active_signals}
                if base_symbol in active_symbols:
                    continue

                # Fetch fresh REST data since WS is unhealthy and store data is stale
                ccxt_symbol = _normalise_symbol(base_symbol)
                try:
                    for timeframe, limit in (("1d", 30), ("4h", 30), ("5m", 50)):
                        rows = _resilient_exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
                        for row in rows:
                            market_data.update_candle(base_symbol, timeframe, row)
                    ticker = _resilient_exchange.fetch_ticker(ccxt_symbol)
                    price = float(ticker["last"])
                    market_data.set_price(base_symbol, price)
                except Exception as exc:
                    logger.warning("Fallback scan REST fetch failed for %s: %s", base_symbol, exc)
                    # Fall back to cached data if REST fetch fails
                    price = market_data.get_price(base_symbol)
                    if price is None:
                        continue

                if not market_data.has_sufficient_data(base_symbol):
                    continue

                candles_5m_raw = market_data.get_candles(base_symbol, "5m")
                candles_4h_raw = market_data.get_candles(base_symbol, "4h")
                candles_1d_raw = market_data.get_candles(base_symbol, "1d")

                four_h_candles = _fallback_to_candles(candles_4h_raw)
                daily_candles = _fallback_to_candles(candles_1d_raw)
                five_m_candles = _fallback_to_candles(candles_5m_raw)

                recent_4h = four_h_candles[-10:] if len(four_h_candles) >= 10 else four_h_candles
                range_low = min(c.low for c in recent_4h) if recent_4h else price * 0.99
                range_high = max(c.high for c in recent_4h) if recent_4h else price * 1.01
                atr_proxy = (range_high - range_low) * 0.01

                for side in (Side.LONG, Side.SHORT):
                    if not risk_manager.can_open_signal(side):
                        continue

                    recent_5m = five_m_candles[-10:] if len(five_m_candles) >= 10 else five_m_candles
                    key_level = (
                        min(c.low for c in recent_5m) if side == Side.LONG else max(c.high for c in recent_5m)
                    ) if recent_5m else price
                    stop_loss = key_level - atr_proxy if side == Side.LONG else key_level + atr_proxy

                    regime = _bot_state.market_regime

                    # CH1 Hard Scalp (fallback path)
                    try:
                        from bot.channels import hard_scalp as _hard_scalp
                        ch1_result = _hard_scalp.run(
                            symbol=base_symbol,
                            current_price=price,
                            side=side,
                            five_min_candles=five_m_candles,
                            daily_candles=daily_candles,
                            four_hour_candles=four_h_candles,
                            news_calendar=news_calendar,
                            risk_manager=risk_manager,
                            range_low=range_low,
                            range_high=range_high,
                            key_liquidity_level=key_level,
                            stop_loss=stop_loss,
                            market_regime=regime,
                        )
                    except Exception as exc:
                        logger.error("Fallback CH1 error for %s %s: %s", base_symbol, side.value, exc)
                        ch1_result = None

                    if ch1_result is not None and not signal_router.should_suppress_duplicate(base_symbol, ChannelTier.HARD):
                        risk_manager.add_signal(ch1_result, origin_channel=signal_router.get_channel_id(ChannelTier.HARD), created_regime=regime)
                        signal_router.record_signal(base_symbol, ChannelTier.HARD)
                        logger.info("Fallback CH1 signal: %s %s", base_symbol, side.value)

                        async def _send_ch1(msg: str = ch1_result.format_message()) -> None:
                            await _broadcast_to_channel(msg, signal_router.get_channel_id(ChannelTier.HARD))
                            if TELEGRAM_CHANNEL_ID and TELEGRAM_CHANNEL_ID != signal_router.get_channel_id(ChannelTier.HARD):
                                await _broadcast_to_channel(msg, TELEGRAM_CHANNEL_ID)

                        try:
                            if _main_loop is not None and _main_loop.is_running():
                                asyncio.run_coroutine_threadsafe(_send_ch1(), _main_loop)
                            else:
                                new_loop = asyncio.new_event_loop()
                                try:
                                    new_loop.run_until_complete(_send_ch1())
                                finally:
                                    new_loop.close()
                        except Exception as exc:
                            logger.error("Fallback CH1 broadcast error for %s: %s", base_symbol, exc)
                        break  # one signal per symbol per scan pass
                time.sleep(0.2)  # ~5 pairs/sec → stays well within Binance 1200 req/min limit
            except Exception as exc:
                logger.error("Fallback scan error for %s: %s", base_symbol, exc)

        # Inter-batch pause to respect Binance API rate limits
        if batch_start + FUTURES_SCAN_BATCH_SIZE < len(pairs):
            time.sleep(FUTURES_SCAN_BATCH_DELAY)


async def cmd_close_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /close_signal SYMBOL OUTCOME PNL

    Admin-only: close a signal, record it in the dashboard, and broadcast a
    trade summary to the channel.

    OUTCOME must be WIN, LOSS, or BE.
    PNL is the percentage profit/loss (e.g. 2.5 for +2.5 %).

    Example:
        /close_signal BTC WIN 2.5
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if len(args) < 3:
        await _reply(
            update,
            "Usage: `/close_signal SYMBOL OUTCOME PNL`\n"
            "Example: `/close_signal BTC WIN 2.5`",
        )
        return

    symbol = args[0].upper()
    outcome = args[1].upper()
    if outcome not in ("WIN", "LOSS", "BE"):
        await _reply(update, "⚠️ OUTCOME must be `WIN`, `LOSS`, or `BE`.")
        return

    try:
        pnl = float(args[2])
    except ValueError:
        await _reply(update, "⚠️ PNL must be a number.")
        return

    sig = next(
        (s for s in risk_manager.active_signals if s.result.symbol == symbol),
        None,
    )
    if sig is None:
        await _reply(update, f"No open signal found for `{symbol}`.")
        return

    direction = 1 if sig.result.side == Side.LONG else -1
    exit_price = sig.entry_mid * (1 + direction * pnl / 100)

    dashboard.record_result(
        TradeResult(
            symbol=sig.result.symbol,
            side=sig.result.side.value,
            entry_price=sig.entry_mid,
            exit_price=round(exit_price, 4),
            stop_loss=sig.result.stop_loss,
            tp1=sig.result.tp1,
            tp2=sig.result.tp2,
            tp3=sig.result.tp3,
            opened_at=sig.opened_at,
            closed_at=time.time(),
            outcome=outcome,
            pnl_pct=pnl,
            timeframe="5m",
        )
    )
    risk_manager.close_signal(symbol, reason=outcome.lower())

    summary = dashboard.summary()
    msg = (
        f"🔒 #{symbol}/USDT signal CLOSED — *{outcome}* | PnL: `{pnl:+.2f}%`\n\n"
        f"{summary}"
    )
    await _broadcast(context, msg)
    await _reply(update, f"✅ Signal `{symbol}` closed as {outcome} with {pnl:+.2f}% PnL.")


async def cmd_channel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /channel_stats

    Admin-only: Show per-channel win rate and performance statistics (30-day window).
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    report = dashboard.format_per_channel_report(days=30)
    await _reply(update, report)


# ── Webhook processor (called by webhook.py) ──────────────────────────────────

def process_webhook(payload: dict) -> Optional[tuple[str, ChannelTier]]:
    """
    Parse an incoming TradingView webhook payload and return a
    ``(message, tier)`` tuple if all confluence checks pass, otherwise None.

    Expected payload keys:
        symbol, side

    All market data (price, candles, levels) is fetched live from Binance.
    The channel tier is determined by signal confidence so the webhook can
    route through the SignalRouter instead of the legacy single channel.
    The bot.py caller is responsible for broadcasting the returned message.
    """
    try:
        raw_symbol = str(payload["symbol"]).upper()
        side = Side(str(payload["side"]).upper())
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Invalid webhook payload: %s", exc)
        return None

    if _bot_state.news_freeze or news_calendar.is_high_impact_imminent():
        return None

    if not risk_manager.can_open_signal(side):
        return None

    # Normalise symbol to CCXT futures format e.g. BTC/USDT:USDT
    ccxt_symbol = _normalise_symbol(raw_symbol)
    symbol = ccxt_symbol.split("/")[0]

    # Fetch LIVE Binance candle data
    try:
        candles = _fetch_binance_candles(ccxt_symbol, side)
    except Exception as exc:
        logger.error("Binance fetch failed in webhook for %s: %s", ccxt_symbol, exc)
        return None

    result = run_confluence_check(
        symbol=symbol,
        current_price=candles["price"],
        side=side,
        range_low=candles["range_low"],
        range_high=candles["range_high"],
        key_liquidity_level=candles["key_level"],
        five_min_candles=candles["5m"],
        daily_candles=candles["1D"],
        four_hour_candles=candles["4H"],
        news_in_window=news_calendar.is_high_impact_imminent(),
        stop_loss=candles["stop_loss"],
    )

    if result is None:
        return None

    # Dynamic risk sizing based on confidence + cooldown state
    risk_fraction = risk_manager.dynamic_risk_fraction(
        confidence=result.confidence.value,
        cooldown_manager=cooldown_manager,
    )
    if risk_fraction == 0.0:
        logger.info(
            "Signal suppressed for %s: LOW confidence during cooldown.", symbol
        )
        return None

    # Determine the target channel tier from signal confidence
    if result.confidence == Confidence.HIGH:
        tier = ChannelTier.HARD
    elif result.confidence == Confidence.MEDIUM:
        tier = ChannelTier.MEDIUM
    else:
        tier = ChannelTier.EASY

    risk_manager.add_signal(result, origin_channel=signal_router.get_channel_id(tier))
    signal_router.record_signal(symbol, tier)  # Track for dedup
    return result.format_message(), tier


# ── Binance live data helpers ─────────────────────────────────────────────────

# Tokens whose names end in "BTC" but are USDT-settled perpetuals on Binance Futures
_BTC_SUFFIX_TOKENS = {"PUMPBTC"}


def _normalise_symbol(raw: str) -> str:
    """
    Normalise a user-supplied symbol string to the CCXT Binance Futures
    format ``BASE/QUOTE:SETTLE``.

    Examples
    --------
    ``BTCUSDT``    → ``BTC/USDT:USDT``
    ``BTC/USDT``   → ``BTC/USDT:USDT``
    ``BTC``        → ``BTC/USDT:USDT``
    ``ETH/BTC``    → ``ETH/BTC:BTC``  (non-USDT quote preserved)
    """
    raw = raw.upper().strip()

    # Already in CCXT futures format
    if ":" in raw:
        return raw

    # Special-case tokens whose names end in "BTC" but are USDT-settled
    if raw in _BTC_SUFFIX_TOKENS:
        return f"{raw}/USDT:USDT"

    if "/" in raw:
        base, quote = raw.split("/", 1)
    elif raw.endswith("USDT"):
        base = raw[:-4]
        quote = "USDT"
    elif raw.endswith("BTC") and len(raw) > 3:
        base = raw[:-3]
        quote = "BTC"
    else:
        base = raw
        quote = "USDT"

    return f"{base}/{quote}:{quote}"


# Dynamically populated list of USDT-M perpetual pairs (base symbols)
_dynamic_pairs: list[str] = []


def fetch_binance_futures_pairs() -> list[str]:
    """
    Fetch all active USDT-M perpetual futures pairs from Binance.
    Returns a list of base symbols like ['BTC', 'ETH', 'SOL', '1000PEPE', ...].

    Uses ResilientExchange to load markets with retry and circuit breaker.
    Filters for:
    - Only USDT-settled contracts (quote = 'USDT', settle = 'USDT')
    - Only active/trading pairs (not delisted)
    - Only perpetual swaps (not delivery futures)

    Falls back to config.AUTO_SCAN_PAIRS if fetch fails.
    """
    try:
        _resilient_exchange.load_markets()
        pairs = []
        for _sym, market in _resilient_exchange.markets.items():
            if (
                market.get("settle") == "USDT"
                and market.get("quote") == "USDT"
                and market.get("active", False)
                and market.get("swap", False)  # perpetual only
            ):
                pairs.append(market["base"])  # e.g., 'BTC', '1000PEPE', 'POL'
        pairs.sort()
        return pairs
    except Exception as exc:
        logger.warning(
            "Failed to fetch Binance futures pairs: %s. Using config fallback.", exc
        )
        return list(AUTO_SCAN_PAIRS)


def _refresh_dynamic_pairs() -> None:
    """
    Periodic job: re-fetch the active Binance USDT-M pairs (every 6 hours).

    When AUTO_SCAN_PAIRS is empty (default), uses ALL fetched pairs.
    When AUTO_SCAN_PAIRS is set, treats it as a whitelist override for testing.
    """
    global _dynamic_pairs
    fetched = fetch_binance_futures_pairs()
    if AUTO_SCAN_PAIRS:
        # Whitelist override mode (e.g. for testing or manual curation)
        fetched_set = set(fetched)
        filtered = [p for p in AUTO_SCAN_PAIRS if p in fetched_set]
        missing = [p for p in AUTO_SCAN_PAIRS if p not in fetched_set]
        if missing:
            logger.warning(
                "AUTO_SCAN_PAIRS contains pairs not found on Binance Futures: %s",
                ", ".join(missing),
            )
        _dynamic_pairs = filtered or fetched
    else:
        # Default: scan ALL Binance Futures USDT-M pairs
        _dynamic_pairs = fetched
    logger.info(
        "Pairs refreshed — %d Binance Futures USDT pairs loaded.", len(_dynamic_pairs)
    )


def _fetch_binance_candles(symbol: str, side: Side) -> dict:
    """
    Fetch live OHLCV data from Binance Futures via CCXT for the given
    *symbol* (CCXT format, e.g. ``BTC/USDT:USDT``).

    Returns a dict with keys ``price``, ``range_low``, ``range_high``,
    ``key_level``, ``stop_loss``, ``5m``, ``1D``, ``4H``.
    """

    # Fetch OHLCV for each required timeframe
    # CCXT returns [[timestamp, open, high, low, close, volume], ...]
    raw_1d = _resilient_exchange.fetch_ohlcv(symbol, "1d", limit=210)
    raw_4h = _resilient_exchange.fetch_ohlcv(symbol, "4h", limit=30)
    raw_5m = _resilient_exchange.fetch_ohlcv(symbol, "5m", limit=50)

    def _to_candles(rows: list) -> list[CandleData]:
        return [
            CandleData(
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in rows
        ]

    daily_candles = _to_candles(raw_1d)
    four_h_candles = _to_candles(raw_4h)
    five_m_candles = _to_candles(raw_5m)

    if len(daily_candles) < 2 or len(four_h_candles) < 2 or len(five_m_candles) < 3:
        raise ValueError(
            f"Insufficient candle data for {symbol}: "
            f"1D={len(daily_candles)}, 4H={len(four_h_candles)}, 5m={len(five_m_candles)}"
        )

    # Current price from ticker
    ticker = _resilient_exchange.fetch_ticker(symbol)
    current_price = float(ticker["last"])

    # range_low / range_high from 4H recent swings (last 10 candles)
    recent_4h = four_h_candles[-10:] if len(four_h_candles) >= 10 else four_h_candles
    range_low = min(c.low for c in recent_4h)
    range_high = max(c.high for c in recent_4h)

    # key_level based on the requested trade side:
    #   LONG  → lowest low of last 10 5m candles (stop-hunt of longs)
    #   SHORT → highest high of last 10 5m candles (stop-hunt of shorts)
    recent_5m = five_m_candles[-10:] if len(five_m_candles) >= 10 else five_m_candles
    if side == Side.LONG:
        key_level = min(c.low for c in recent_5m)
    else:
        key_level = max(c.high for c in recent_5m)

    # stop_loss: a small buffer beyond the key_level
    atr_proxy = (range_high - range_low) * 0.01  # 1% of range as buffer
    stop_loss = key_level - atr_proxy if side == Side.LONG else key_level + atr_proxy

    return {
        "price": current_price,
        "range_low": range_low,
        "range_high": range_high,
        "key_level": key_level,
        "stop_loss": stop_loss,
        "5m": five_m_candles,
        "1D": daily_candles,
        "4H": four_h_candles,
    }


def _seed_historical_candles(symbols: list[str]) -> None:
    """
    REST-fetch initial candle history at startup using parallel threads.

    Uses up to 10 concurrent workers with a short sleep between batches
    to respect Binance rate limits while reducing boot time from ~2.5min to ~15s.
    Fetches 1D (210), 4H (30), and 5m (50) candles for every pair so the
    signal engine has enough data before the first WS events arrive.
    210 daily candles are required for the 200-day SMA used by the regime detector.
    """
    total = len(symbols)
    logger.info("Seeding historical candles for %d pairs (parallel)…", total)

    def _seed_one(base: str) -> None:
        ccxt_symbol = _normalise_symbol(base)
        try:
            for timeframe, limit in (("1d", 210), ("4h", 30), ("5m", 50), ("15m", 50)):
                rows = _resilient_exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
                for row in rows:
                    market_data.update_candle(base, timeframe, row)
            rows_5m = market_data.get_candles(base, "5m")
            if rows_5m:
                market_data.set_price(base, float(rows_5m[-1][4]))
        except Exception as exc:
            logger.warning("Seed failed for %s: %s", base, exc)

    BATCH_SIZE = 10
    for i in range(0, total, BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            list(executor.map(_seed_one, batch))
        if i + BATCH_SIZE < total:
            time.sleep(1.0)  # inter-batch pause to stay within rate limits
        if (i + BATCH_SIZE) % 50 == 0:
            logger.info("Seeded ~%d/%d pairs…", min(i + BATCH_SIZE, total), total)

    logger.info("Historical candle seeding complete.")


def _seed_spot_historical_candles(pairs: list[dict]) -> None:
    """
    REST-fetch initial candle history for spot pairs at startup.

    Uses up to 10 concurrent workers with a short sleep between batches
    to respect Binance rate limits.  Fetches 1D (100), 4H (30), and 1H (50)
    candles for every spot pair so the spot signal engine has data on boot.
    """
    total = len(pairs)
    logger.info("Seeding spot historical candles for %d pairs (parallel)…", total)

    def _seed_one_spot(pair_info: dict) -> None:
        base = pair_info["symbol"]
        ccxt_symbol = pair_info["ccxt_symbol"]  # e.g. "BTC/USDT" (no :USDT suffix)
        try:
            for timeframe, limit in (("1d", 100), ("4h", 30), ("1h", 50)):
                rows = _spot_resilient_exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
                for row in rows:
                    spot_market_data.update_candle(base, timeframe, row)
            rows_1h = spot_market_data.get_candles(base, "1h")
            if rows_1h:
                spot_market_data.set_price(base, float(rows_1h[-1][4]))
        except Exception as exc:
            logger.warning("Spot seed failed for %s: %s", base, exc)

    BATCH_SIZE = 10
    for i in range(0, total, BATCH_SIZE):
        batch = pairs[i:i + BATCH_SIZE]
        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            list(executor.map(_seed_one_spot, batch))
        if i + BATCH_SIZE < total:
            time.sleep(1.0)  # inter-batch pause to stay within rate limits
        if (i + BATCH_SIZE) % 50 == 0:
            logger.info("Seeded ~%d/%d spot pairs…", min(i + BATCH_SIZE, total), total)

    logger.info("Spot historical candle seeding complete.")


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /pairs — Show currently loaded scan pairs count and list.
    Admin only.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    count = len(_dynamic_pairs)
    sample = ", ".join(_dynamic_pairs[:30])
    more = f"\n... and {count - 30} more" if count > 30 else ""
    msg = f"🔍 *Loaded {count} Binance Futures pairs:*\n{sample}{more}"
    await _reply(update, msg)


async def cmd_spot_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /spot_scan [on|off]

    Admin-only: toggle the spot scanner on or off.
    With no argument, reports current state.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        state = "ACTIVE ✅" if spot_scanner.is_enabled else "INACTIVE ❌"
        await _reply(update, f"💎 Spot Scanner is currently *{state}*.")
        return

    arg = args[0].lower()
    if arg == "on":
        spot_scanner.set_enabled(True)
        await _reply(update, "💎 Spot Scanner *ACTIVATED* ✅")
    elif arg == "off":
        spot_scanner.set_enabled(False)
        await _reply(update, "💎 Spot Scanner *DEACTIVATED* ❌")
    else:
        await _reply(update, "Usage: `/spot_scan on` or `/spot_scan off`")


async def cmd_spot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /spot_status — Show spot scanner status.
    Admin only.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    status = spot_scanner.get_status()
    import datetime as _dt
    last_scan = (
        _dt.datetime.fromtimestamp(status["last_scan"], tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if status["last_scan"] > 0
        else "Never"
    )
    msg = (
        f"💎 *Spot Scanner Status*\n\n"
        f"State: {'ACTIVE ✅' if status['enabled'] else 'INACTIVE ❌'}\n"
        f"Pairs Loaded: {status['pairs_loaded']}\n"
        f"Last Scan: {last_scan}\n"
        f"Gems Found (total): {status['gems_found_total']}\n"
        f"Scam Alerts (total): {status['scams_found_total']}"
    )
    await _reply(update, msg)


async def cmd_scam_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /scam_check SYMBOL — Manual scam pattern check for a spot pair.
    Admin only.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        await _reply(update, "Usage: `/scam_check SYMBOL` e.g. `/scam_check PEPE`")
        return

    raw_symbol = args[0].upper()
    # Validate symbol: alphanumeric only, max 20 chars
    if not validate_symbol(raw_symbol):
        await _reply(update, "⛔ Invalid symbol. Use alphanumeric characters only (max 20 chars).")
        return

    scam = spot_scanner.scam_check_symbol(raw_symbol)
    if scam is None:
        await _reply(update, f"✅ No scam patterns detected for #{raw_symbol}/USDT.")
    else:
        await _reply(update, scam.format_message())


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /backtest SYMBOL START [END]

    Admin-only: run a historical backtest for *SYMBOL* over the given date
    range and reply with the performance report.

    START and END must be in YYYY-MM-DD format.  END defaults to today.

    Example:
        /backtest BTCUSDT 2024-01-01 2024-04-01
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    args = context.args or []
    if len(args) < 2:
        await _reply(update, "Usage: `/backtest SYMBOL START [END]`\nExample: `/backtest BTCUSDT 2024-01-01 2024-04-01`")
        return

    raw_symbol = args[0].upper()
    ccxt_symbol = _normalise_symbol(raw_symbol)
    base_symbol = ccxt_symbol.split("/")[0]

    from datetime import datetime, timezone

    try:
        start_dt = datetime.strptime(args[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        await _reply(update, "⚠️ START must be YYYY-MM-DD.")
        return

    if len(args) >= 3:
        try:
            end_dt = datetime.strptime(args[2], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            await _reply(update, "⚠️ END must be YYYY-MM-DD.")
            return
    else:
        end_dt = datetime.now(tz=timezone.utc)

    await _reply(update, f"⏳ Running backtest for `{raw_symbol}` from `{args[1]}` to `{end_dt.strftime('%Y-%m-%d')}` …")

    def _run_backtest() -> str:
        """Blocking backtest — called via run_in_executor."""
        since_ms = int(start_dt.timestamp() * 1000)
        until_ms = int(end_dt.timestamp() * 1000)
        fetcher = HistoricalDataFetcher()
        try:
            candles_5m = fetcher.fetch(ccxt_symbol, "5m", since_ms, until_ms)
            candles_4h = fetcher.fetch(ccxt_symbol, "4h", since_ms, until_ms)
            candles_1d = fetcher.fetch(ccxt_symbol, "1d", since_ms, until_ms)
        except Exception as exc:  # noqa: BLE001
            return f"❌ Failed to fetch data: {exc}"

        if len(candles_5m) < 50 or len(candles_4h) < 2 or len(candles_1d) < 20:
            return (
                f"⚠️ Insufficient historical data for `{raw_symbol}`: "
                f"5m={len(candles_5m)}, 4H={len(candles_4h)}, 1D={len(candles_1d)}"
            )

        bt = Backtester(
            symbol=ccxt_symbol,
            five_min_candles=candles_5m,
            four_hour_candles=candles_4h,
            daily_candles=candles_1d,
        )
        result = bt.run()

        checks = [
            ("Trades ≥ 30", result.total_trades >= 30),
            ("Win rate ≥ 50%", result.win_rate >= 0.50),
            ("Profit factor ≥ 1.5", result.profit_factor >= 1.5),
            ("Max DD ≤ 20%", result.max_drawdown_pct <= 20.0),
            ("Sharpe ≥ 1.0", result.sharpe_ratio >= 1.0),
        ]
        check_lines = "\n".join(
            f"{'✅' if ok else '❌'} {name}" for name, ok in checks
        )
        all_pass = all(ok for _, ok in checks)
        verdict = "✅ READY FOR LIVE DEPLOYMENT" if all_pass else "❌ NOT READY — review metrics"

        return (
            f"📊 *Backtest Results — #{base_symbol}/USDT*\n"
            f"Period: `{args[1]}` → `{end_dt.strftime('%Y-%m-%d')}`\n\n"
            f"Trades: {result.total_trades} "
            f"(W:{result.wins} L:{result.losses} BE:{result.break_evens} S:{result.stale_closes})\n"
            f"Win Rate: `{result.win_rate:.1%}`\n"
            f"Profit Factor: `{result.profit_factor:.2f}`\n"
            f"Sharpe: `{result.sharpe_ratio:.2f}`\n"
            f"Max Drawdown: `{result.max_drawdown_pct:.1f}%`\n"
            f"Calmar: `{result.calmar_ratio:.2f}`\n"
            f"Equity: `{result.initial_capital:,.0f}` → `{result.final_equity:,.2f}` USDT\n\n"
            f"*Go-live checks:*\n{check_lines}\n\n"
            f"*Verdict:* {verdict}"
        )

    loop = asyncio.get_event_loop()
    try:
        report = await loop.run_in_executor(None, _run_backtest)
    except Exception as exc:  # noqa: BLE001
        logger.error("Backtest error for %s: %s", raw_symbol, exc)
        report = f"❌ Backtest failed: {exc}"

    await _reply(update, report)


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /briefing

    Admin-only: generate and post the daily market briefing on demand.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    from bot.insights.market_briefing import generate_daily_briefing
    briefing_text = generate_daily_briefing(dashboard, risk_manager, _bot_state, market_data)
    channel_id = signal_router.get_channel_id(ChannelTier.INSIGHTS)
    if channel_id:
        await _broadcast_to_channel(briefing_text, channel_id)
    await _reply(update, "✅ Daily briefing posted to CH5.")


async def cmd_db_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /db_maintenance

    Admin-only: archive old signals and run VACUUM on the database.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    from bot.database import archive_old_signals
    try:
        archived = archive_old_signals(days=DB_ARCHIVE_DAYS)
        await _reply(update, f"✅ DB maintenance complete — {archived} signals archived (>{DB_ARCHIVE_DAYS}d old).")
    except Exception as exc:
        logger.error("DB maintenance error: %s", exc)
        await _reply(update, f"❌ DB maintenance failed: {exc}")


# ── Application bootstrap ─────────────────────────────────────────────────────

def build_application() -> Application:
    """Create and configure the Telegram bot application."""
    global _dynamic_pairs, _main_loop
    if not TELEGRAM_BOT_TOKEN:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN environment variable is not set."
        )

    # Define post_init callback before building the app
    async def _post_init(application: Application) -> None:
        global _main_loop
        _main_loop = asyncio.get_event_loop()
        await ws_manager.start(_dynamic_pairs, on_candle_close)
        spot_symbols = [p["symbol"] for p in spot_scanner._pairs]
        if spot_symbols:
            await spot_ws.start(spot_symbols, None)
            logger.info(
                "Spot WebSocket manager started for %d pairs.",
                len(spot_symbols),
            )
        await auto_close_monitor.start()
        logger.info(
            "WebSocket manager started for %d pairs (primary scanning path).",
            len(_dynamic_pairs),
        )

    async def _post_shutdown(application: Application) -> None:
        await auto_close_monitor.stop()
        await ws_manager.stop()
        await spot_ws.stop()
        logger.info("WebSocket manager stopped.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("signal_gen", cmd_signal_gen))
    app.add_handler(CommandHandler("move_be", cmd_move_be))
    app.add_handler(CommandHandler("trail_sl", cmd_trail_sl))
    app.add_handler(CommandHandler("auto_scan", cmd_auto_scan))
    app.add_handler(CommandHandler("news_caution", cmd_news_caution))
    app.add_handler(CommandHandler("risk_calc", cmd_risk_calc))
    app.add_handler(CommandHandler("close_signal", cmd_close_signal))
    app.add_handler(CommandHandler("channel_stats", cmd_channel_stats))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("regime", cmd_regime))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("db_maintenance", cmd_db_maintenance))
    app.add_handler(CommandHandler("spot_scan", cmd_spot_scan))
    app.add_handler(CommandHandler("spot_status", cmd_spot_status))
    app.add_handler(CommandHandler("scam_check", cmd_scam_check))

    # Fetch Binance USDT-M perpetual pairs dynamically at startup
    _refresh_dynamic_pairs()

    # Seed historical candle buffers via REST so signal engine has data on boot
    _seed_historical_candles(_dynamic_pairs)

    # Wire live news calendar — fetch immediately then refresh every 30 minutes
    fetch_and_reload(news_calendar)   # first fetch at startup (blocking, fast)
    _scheduler.add_job(
        fetch_and_reload,
        "interval",
        minutes=30,
        args=[news_calendar],
        id="news_refresh",
        replace_existing=True,
    )

    # Auto-trailing SL job — active only when _trail_active is True
    _scheduler.add_job(
        _run_trailing_sl_job,
        "interval",
        seconds=60,
        id="trailing_sl",
        replace_existing=True,
    )

    # Stale signal cleanup — auto-close signals open beyond STALE_SIGNAL_HOURS
    _scheduler.add_job(
        _run_stale_signal_job,
        "interval",
        minutes=15,
        id="stale_signal_cleanup",
        replace_existing=True,
    )

    # Pairs refresh — re-fetch active Binance USDT-M pairs every 6 hours
    _scheduler.add_job(
        _refresh_dynamic_pairs,
        "interval",
        hours=6,
        id="pairs_refresh",
        replace_existing=True,
    )

    # Refresh 1D candles every 6 hours to keep daily buffers current
    def _refresh_daily_candles() -> None:
        for base in _dynamic_pairs:
            ccxt_symbol = _normalise_symbol(base)
            try:
                rows = _resilient_exchange.fetch_ohlcv(ccxt_symbol, "1d", limit=30)
                for row in rows:
                    market_data.update_candle(base, "1d", row)
            except Exception as exc:
                logger.warning("1D refresh failed for %s: %s", base, exc)
            time.sleep(0.5)

    _scheduler.add_job(
        _refresh_daily_candles,
        "interval",
        hours=6,
        id="daily_candles_refresh",
        replace_existing=True,
    )

    # Fallback polling scan — runs at the configured interval but is a no-op
    # whenever the WebSocket stream is healthy.  Activates automatically when
    # the stream is degraded so 24/7 signal generation continues uninterrupted.
    _scheduler.add_job(
        _run_fallback_scan_job,
        "interval",
        seconds=AUTO_SCAN_INTERVAL_SECONDS,
        id="fallback_scan",
        replace_existing=True,
    )

    # ── CH4 — Spot Momentum scan (every CH4_SCAN_INTERVAL_HOURS hours) ─────
    def _run_spot_scan_job() -> None:
        if not signal_router.is_channel_enabled(ChannelTier.SPOT):
            return
        from bot.channels import spot_momentum as _spot_momentum
        for pair_info in list(spot_scanner._pairs):
            base_symbol = pair_info["symbol"]
            try:
                candles_1d_raw = spot_market_data.get_candles(base_symbol, "1d")
                candles_4h_raw = spot_market_data.get_candles(base_symbol, "4h")
                price = spot_market_data.get_price(base_symbol)
                if price is None or len(candles_1d_raw) < 70 or len(candles_4h_raw) < 4:
                    continue
                daily_candles = _fallback_to_candles(candles_1d_raw)
                four_h_candles = _fallback_to_candles(candles_4h_raw)
                spot_result = _spot_momentum.run(
                    symbol=base_symbol,
                    current_price=price,
                    daily_candles=daily_candles,
                    four_hour_candles=four_h_candles,
                )
                if spot_result is not None:
                    logger.info("CH4 spot signal: %s", base_symbol)
                    # Wrap SpotSignalResult into SignalResult for risk tracking
                    signal_result = SignalResult(
                        symbol=base_symbol,
                        side=Side.LONG,
                        confidence=Confidence.MEDIUM,
                        entry_low=spot_result.entry_low,
                        entry_high=spot_result.entry_high,
                        tp1=spot_result.tp1,
                        tp2=spot_result.tp2,
                        tp3=spot_result.tp3,
                        stop_loss=spot_result.stop_loss,
                        structure_note="",
                        context_note="",
                        leverage_min=1,
                        leverage_max=1,
                    )
                    try:
                        risk_manager.add_signal(
                            signal_result,
                            origin_channel=signal_router.get_channel_id(ChannelTier.SPOT),
                            created_regime=_bot_state.market_regime,
                        )
                        signal_router.record_signal(base_symbol, ChannelTier.SPOT)
                    except RuntimeError as _cap_exc:
                        logger.warning("CH4 3-pair cap reached for %s: %s", base_symbol, _cap_exc)
                        continue
                    msg_text = spot_result.format_message()

                    async def _send_spot(m: str = msg_text) -> None:
                        await _broadcast_to_channel(m, signal_router.get_channel_id(ChannelTier.SPOT))

                    if _main_loop is not None and _main_loop.is_running():
                        asyncio.run_coroutine_threadsafe(_send_spot(), _main_loop)
                    else:
                        new_loop = asyncio.new_event_loop()
                        try:
                            new_loop.run_until_complete(_send_spot())
                        finally:
                            new_loop.close()
            except Exception as exc:
                logger.error("CH4 spot scan error for %s: %s", base_symbol, exc)

    _scheduler.add_job(
        _run_spot_scan_job,
        "interval",
        hours=CH4_SCAN_INTERVAL_HOURS,
        id="spot_scan",
        replace_existing=True,
    )

    # ── SpotScanner: load pair list on boot ────────────────────────────────
    if SPOT_SCAN_ENABLED:
        spot_scanner.refresh_pairs()
        _seed_spot_historical_candles(spot_scanner._pairs)

    # ── SpotScanner pair list refresh (every 6 hours) ──────────────────────
    _scheduler.add_job(
        spot_scanner.refresh_pairs,
        "interval",
        hours=6,
        id="spot_pairs_refresh",
        replace_existing=True,
    )

    # ── SpotScanner gem/scam detection (every SPOT_SCAN_INTERVAL_MINUTES) ──
    def _run_spot_scanner_job() -> None:
        if not SPOT_SCAN_ENABLED:
            return
        if not signal_router.is_channel_enabled(ChannelTier.SPOT):
            return
        try:
            gems, scams = spot_scanner.scan_once()
            for gem in gems:
                if signal_router.should_suppress_duplicate(gem.symbol, ChannelTier.SPOT):
                    logger.debug("CH4 gem dedup suppressed for %s", gem.symbol)
                    continue
                # Wrap SpotGemResult into SignalResult for risk tracking.
                # Spot gems are always LONG, no leverage.
                gem_signal_result = SignalResult(
                    symbol=gem.symbol,
                    side=Side.LONG,
                    confidence=Confidence.MEDIUM,
                    entry_low=gem.entry_low,
                    entry_high=gem.entry_high,
                    tp1=gem.tp1,
                    tp2=gem.tp2,
                    tp3=gem.tp3,
                    stop_loss=gem.stop_loss,
                    structure_note="",
                    context_note="",
                    leverage_min=1,
                    leverage_max=1,
                )
                try:
                    risk_manager.add_signal(
                        gem_signal_result,
                        origin_channel=signal_router.get_channel_id(ChannelTier.SPOT),
                        created_regime=_bot_state.market_regime,
                    )
                    signal_router.record_signal(gem.symbol, ChannelTier.SPOT)
                except RuntimeError as _cap_exc:
                    logger.warning("CH4 gem 3-pair cap reached for %s: %s", gem.symbol, _cap_exc)
                    continue
                except Exception as _add_exc:
                    logger.error("CH4 gem signal registration error for %s: %s", gem.symbol, _add_exc)
                    continue
                logger.info("CH4 spot gem: %s (%s, score=%d)", gem.symbol, gem.gem_type, gem.score)
                _now_gem = time.time()
                _gem_tier_key = ChannelTier.SPOT.value
                _last_gem_broadcast = _last_signal_broadcast_time.get(_gem_tier_key, 0.0)
                if _now_gem - _last_gem_broadcast >= MIN_SIGNAL_GAP_SECONDS:
                    _last_signal_broadcast_time[_gem_tier_key] = _now_gem
                    msg_text = gem.format_message()

                    async def _send_gem(m: str = msg_text) -> None:
                        await _broadcast_to_channel(m, signal_router.get_channel_id(ChannelTier.SPOT))

                    if _main_loop is not None and _main_loop.is_running():
                        asyncio.run_coroutine_threadsafe(_send_gem(), _main_loop)
                    else:
                        new_loop = asyncio.new_event_loop()
                        try:
                            new_loop.run_until_complete(_send_gem())
                        finally:
                            new_loop.close()
                else:
                    logger.debug(
                        "CH4 gem rate-limited for %s — %ds since last broadcast.",
                        gem.symbol,
                        int(_now_gem - _last_gem_broadcast),
                    )
            for scam in scams:
                msg_text = scam.format_message()

                async def _send_scam(m: str = msg_text) -> None:
                    await _broadcast_to_channel(m, signal_router.get_channel_id(ChannelTier.INSIGHTS))

                if _main_loop is not None and _main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(_send_scam(), _main_loop)
        except Exception as exc:
            logger.error("Spot scanner job error: %s", exc)

    _scheduler.add_job(
        _run_spot_scanner_job,
        "interval",
        minutes=SPOT_SCAN_INTERVAL_MINUTES,
        id="spot_scanner",
        replace_existing=True,
    )


    def _post_btc_structure() -> None:
        if not signal_router.is_channel_enabled(ChannelTier.INSIGHTS):
            return
        from bot.insights.btc_structure import format_btc_structure_message
        btc_price = market_data.get_price("BTC")
        if btc_price is None:
            return
        btc_4h_raw = market_data.get_candles("BTC", "4h")
        if len(btc_4h_raw) < 10:
            return
        btc_4h_candles = _fallback_to_candles(btc_4h_raw)
        msg_text = format_btc_structure_message(btc_4h_candles, btc_price)

        async def _send() -> None:
            await _broadcast_to_channel(msg_text, signal_router.get_channel_id(ChannelTier.INSIGHTS))

        if _main_loop is not None and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    _scheduler.add_job(
        _post_btc_structure,
        "interval",
        hours=4,
        id="btc_structure",
        replace_existing=True,
    )

    # ── CH5B — Daily news digest at 08:00 UTC ───────────────────────────────
    def _post_news_digest() -> None:
        if not signal_router.is_channel_enabled(ChannelTier.INSIGHTS):
            return
        from bot.insights.news_digest import format_news_digest
        msg_text = format_news_digest(news_calendar)

        async def _send() -> None:
            await _broadcast_to_channel(msg_text, signal_router.get_channel_id(ChannelTier.INSIGHTS))

        if _main_loop is not None and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    _scheduler.add_job(
        _post_news_digest,
        "cron",
        hour=8,
        minute=0,
        id="news_digest",
        replace_existing=True,
    )

    # ── CH5C — Regime detector at 09:00 UTC daily ───────────────────────────
    def _run_regime_detector() -> None:
        if not signal_router.is_channel_enabled(ChannelTier.INSIGHTS):
            return
        from bot.insights.regime_detector import run as _regime_run
        btc_price = market_data.get_price("BTC")
        btc_1d_raw = market_data.get_candles("BTC", "1d")
        if btc_price is None or len(btc_1d_raw) < 10:
            return
        btc_daily_candles = _fallback_to_candles(btc_1d_raw)
        msg_text = _regime_run(btc_daily_candles, btc_price, _bot_state)

        async def _send() -> None:
            await _broadcast_to_channel(msg_text, signal_router.get_channel_id(ChannelTier.INSIGHTS))

        if _main_loop is not None and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    _scheduler.add_job(
        _run_regime_detector,
        "cron",
        hour=9,
        minute=0,
        id="regime_detector",
        replace_existing=True,
    )

    # ── CH5D — Weekly BTC briefing every Sunday at 18:00 UTC ────────────────
    def _post_weekly_briefing() -> None:
        if not signal_router.is_channel_enabled(ChannelTier.INSIGHTS):
            return
        from bot.insights.weekly_briefing import format_weekly_briefing
        btc_price = market_data.get_price("BTC")
        btc_1d_raw = market_data.get_candles("BTC", "1d")
        if btc_price is None or len(btc_1d_raw) < 14:
            return
        btc_daily_candles = _fallback_to_candles(btc_1d_raw)
        msg_text = format_weekly_briefing(btc_daily_candles, btc_price)

        async def _send() -> None:
            await _broadcast_to_channel(msg_text, signal_router.get_channel_id(ChannelTier.INSIGHTS))

        if _main_loop is not None and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    _scheduler.add_job(
        _post_weekly_briefing,
        "cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        id="weekly_briefing",
        replace_existing=True,
    )

    # ── CH5E — Daily Market Briefing at BRIEFING_HOUR_UTC ───────────────────
    def _post_daily_briefing() -> None:
        if not BRIEFING_ENABLED:
            return
        if not signal_router.is_channel_enabled(ChannelTier.INSIGHTS):
            return
        from bot.insights.market_briefing import generate_daily_briefing
        msg_text = generate_daily_briefing(dashboard, risk_manager, _bot_state, market_data)

        async def _send() -> None:
            await _broadcast_to_channel(msg_text, signal_router.get_channel_id(ChannelTier.INSIGHTS))

        if _main_loop is not None and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _main_loop)

    _scheduler.add_job(
        _post_daily_briefing,
        "cron",
        hour=BRIEFING_HOUR_UTC,
        minute=0,
        id="daily_briefing",
        replace_existing=True,
    )

    # ── Weekly DB maintenance — every Sunday at 04:00 UTC ───────────────────
    def _run_db_maintenance() -> None:
        from bot.database import archive_old_signals
        try:
            archived = archive_old_signals(days=DB_ARCHIVE_DAYS)
            logger.info("Scheduled DB maintenance: archived %d signals.", archived)
        except Exception as exc:
            logger.error("Scheduled DB maintenance failed: %s", exc)

    _scheduler.add_job(
        _run_db_maintenance,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="db_maintenance",
        replace_existing=True,
    )

    # ── Dead-Man Switch — hourly check for signal silence ───────────────────
    _DEAD_MAN_SILENCE_HOURS = 24

    def _run_dead_man_check() -> None:
        """Alert admin if no signal has been generated in the past 24h."""
        if not _bot_state.auto_scan_active:
            return
        silence_seconds = _bot_state.seconds_since_last_signal()
        if silence_seconds > _DEAD_MAN_SILENCE_HOURS * 3600:
            silence_hours = silence_seconds / 3600
            alert_msg = (
                f"🚨 DEAD-MAN SWITCH TRIGGERED\n"
                f"No signal generated in the past {silence_hours:.1f}h "
                f"(threshold: {_DEAD_MAN_SILENCE_HOURS}h).\n"
                f"Check WS connection, scanner state, and logs."
            )
            logger.warning(
                "Dead-man switch: no signal generated in %.1fh (threshold %dh).",
                silence_hours, _DEAD_MAN_SILENCE_HOURS,
            )
            if ADMIN_CHAT_ID and _main_loop is not None and _main_loop.is_running():
                _dm_text = alert_msg

                async def _send_dead_man() -> None:
                    async with Bot(token=TELEGRAM_BOT_TOKEN) as _b:
                        await _b.send_message(chat_id=ADMIN_CHAT_ID, text=_dm_text)
                asyncio.run_coroutine_threadsafe(_send_dead_man(), _main_loop)

    _scheduler.add_job(
        _run_dead_man_check,
        "interval",
        hours=1,
        id="dead_man_switch",
        replace_existing=True,
    )

    # ── Weekly Performance Report — every Sunday at 20:00 UTC ───────────────
    def _run_weekly_report() -> None:
        from bot.weekly_report import generate_weekly_report
        try:
            report_text = generate_weekly_report(dashboard, days=7)
        except Exception as exc:
            logger.error("Weekly report generation failed: %s", exc)
            return
        insights_id = signal_router.get_channel_id(ChannelTier.INSIGHTS)
        target_id = insights_id or TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID
        if target_id == 0:
            logger.debug("Weekly report: no target channel configured.")
            return
        if _main_loop is not None and _main_loop.is_running():
            _report_text = report_text
            _target_ch = target_id

            async def _send_report() -> None:
                await _broadcast_to_channel(_report_text, _target_ch)
            asyncio.run_coroutine_threadsafe(_send_report(), _main_loop)

    _scheduler.add_job(
        _run_weekly_report,
        "cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        id="weekly_performance_report",
        replace_existing=True,
    )

    if not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started.")

    logger.info(
        "Auto-scan boot state: %s (AUTO_SCAN_ENABLED_ON_BOOT=%s).",
        "ACTIVE" if _bot_state.auto_scan_active else "INACTIVE",
        AUTO_SCAN_ENABLED_ON_BOOT,
    )
    logger.info(
        "Fallback polling scheduled every %ds (activates when WS stream is unhealthy).",
        AUTO_SCAN_INTERVAL_SECONDS,
    )

    return app


def main() -> None:
    """Entry point — run the bot in long-polling mode."""
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    app = build_application()
    logger.info("360 Crypto Eye Scalping bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
