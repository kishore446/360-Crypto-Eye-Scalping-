"""
Telegram Bot — 360 Crypto Eye Scalping Signals
================================================
Implements all admin & user commands from Section IV of the master blueprint:

  /signal_gen   — Auto-scans and generates a formatted 360 Eye signal.
  /move_be      — Broadcasts "Move SL to Entry (Risk-Free Mode ON)."
  /trail_sl     — Activates auto-trailing SL behind every 5m HL/LH.
  /news_caution — Freezes new signals; triggers partial-close alert.
  /risk_calc    — Calculates exact position size from balance & SL distance.

The bot also handles incoming TradingView webhook payloads forwarded by
the Flask receiver (webhook.py) via the shared ``process_webhook`` function.

Required environment variable:
  TELEGRAM_BOT_TOKEN — Bot token issued by @BotFather.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import ccxt
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from bot.dashboard import Dashboard, TradeResult
from bot.news_fetcher import fetch_and_reload
from bot.news_filter import NewsCalendar
from bot.risk_manager import RiskManager, calculate_position_size
from bot.signal_engine import (
    CandleData,
    Side,
    run_confluence_check,
)
from bot.state import BotState
from config import (
    ADMIN_CHAT_ID,
    AUTO_SCAN_INTERVAL_SECONDS,
    AUTO_SCAN_PAIRS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)

logger = logging.getLogger(__name__)

# ── Shared state (singleton per process) ─────────────────────────────────────

risk_manager = RiskManager()
news_calendar = NewsCalendar()
dashboard = Dashboard()

# Background scheduler — refreshes the news calendar every 30 minutes
_scheduler = BackgroundScheduler(daemon=True)

# Thread-safe bot state singleton
_bot_state = BotState()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == ADMIN_CHAT_ID


async def _reply(update: Update, text: str, parse_mode: str = "Markdown") -> None:
    if update.message:
        await update.message.reply_text(text, parse_mode=parse_mode)


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send *text* to the public Telegram channel."""
    await context.bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID,
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

    risk_manager.add_signal(result)
    message = result.format_message()
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
    /trail_sl

    Admin-only: toggle auto-trailing SL behind every 5m Higher Low (long) /
    Lower High (short).
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    _bot_state.trail_active = not _bot_state.trail_active
    state = "ACTIVATED ✅" if _bot_state.trail_active else "DEACTIVATED ❌"
    msg = f"📈 Auto-Trailing SL is now *{state}*."
    await _broadcast(context, msg)
    await _reply(update, msg)


async def cmd_auto_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /auto_scan

    Admin-only: toggle the background auto-scanner that periodically checks
    all watchlist pairs and broadcasts signals when confluence is met.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    _bot_state.auto_scan_active = not _bot_state.auto_scan_active

    if _bot_state.auto_scan_active:
        msg = (
            f"🔍 Auto-Scanner ACTIVATED ✅ — scanning {len(AUTO_SCAN_PAIRS)} pairs "
            f"every {AUTO_SCAN_INTERVAL_SECONDS}s."
        )
    else:
        msg = "🔍 Auto-Scanner DEACTIVATED ❌"

    await _broadcast(context, msg)
    await _reply(update, msg)


async def cmd_news_caution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /news_caution

    Admin-only: toggle the news-freeze mode.
    When active:
      • New signals are blocked.
      • A partial-close recommendation is broadcast to the channel.
    """
    if not _is_admin(update):
        await _reply(update, "⛔ Admin only.")
        return

    _bot_state.news_freeze = not _bot_state.news_freeze

    if _bot_state.news_freeze:
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
    else:
        msg = "✅ *News Caution Mode DEACTIVATED.* Signal generation is now active."

    await _broadcast(context, msg)
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

    Broadcasts a Telegram message for each SL update.
    """
    if not _bot_state.trail_active:
        return

    updates: list[str] = []
    for sig in list(risk_manager.active_signals):
        ccxt_symbol = f"{sig.result.symbol}/USDT:USDT"
        try:
            raw_5m = _exchange.fetch_ohlcv(ccxt_symbol, "5m", limit=5)
        except Exception as exc:
            logger.warning("Trailing SL fetch failed for %s: %s", sig.result.symbol, exc)
            continue

        if len(raw_5m) < 3:
            continue

        last_3 = raw_5m[-3:]
        current_sl = sig.result.stop_loss

        if sig.result.side == Side.LONG:
            # Per the spec: "Higher Low" = min low of the last 3 candles.
            # SL only moves up (never down) for LONG.
            new_sl = min(row[3] for row in last_3)
            if new_sl > current_sl:
                sig.result.stop_loss = new_sl
                updates.append(
                    f"📈 #{sig.result.symbol}/USDT LONG: "
                    f"Trailing SL raised {current_sl:.4f} → {new_sl:.4f} "
                    f"(Higher Low trail)"
                )
        else:
            # Per the spec: "Lower High" = max high of the last 3 candles.
            # SL only moves down (never up) for SHORT.
            new_sl = max(row[2] for row in last_3)
            if new_sl < current_sl:
                sig.result.stop_loss = new_sl
                updates.append(
                    f"📉 #{sig.result.symbol}/USDT SHORT: "
                    f"Trailing SL lowered {current_sl:.4f} → {new_sl:.4f} "
                    f"(Lower High trail)"
                )

    if not updates:
        return

    # Persist updated stop-losses via public API
    try:
        risk_manager.save()
    except Exception as exc:
        logger.error("Failed to persist trailing SL update: %s", exc)

    # Broadcast from background thread using a fresh Bot instance
    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            for text in updates:
                try:
                    await bot.send_message(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        text=text,
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.error("Trailing SL broadcast error: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_send())
        else:
            loop.run_until_complete(_send())
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(_send())
        finally:
            new_loop.close()
    except Exception as exc:
        logger.error("Trailing SL job failed to send broadcasts: %s", exc)


# ── Background auto-scan job ──────────────────────────────────────────────────

def _run_auto_scan_job(context_or_bot=None) -> None:
    """
    APScheduler background job — runs every ``AUTO_SCAN_INTERVAL_SECONDS``
    when ``_auto_scan_active`` is True.

    For each symbol in ``AUTO_SCAN_PAIRS``:
      • Checks both LONG and SHORT sides.
      • Fetches live Binance candle data.
      • Runs the full confluence engine.
      • Broadcasts any qualifying signal to the Telegram channel.
    """
    if not _bot_state.auto_scan_active:
        return

    signals_found: int = 0
    pairs_scanned: int = 0
    messages: list[str] = []

    active_symbols = {sig.result.symbol for sig in risk_manager.active_signals}

    logger.info("Auto-scan started — checking %d pairs.", len(AUTO_SCAN_PAIRS))

    for base in AUTO_SCAN_PAIRS:
        ccxt_symbol = _normalise_symbol(base)
        symbol = ccxt_symbol.split("/")[0]

        # Skip if a signal for this symbol is already active
        if symbol in active_symbols:
            logger.debug("Auto-scan skipping %s — signal already active.", symbol)
            continue

        for side in (Side.LONG, Side.SHORT):
            try:
                # Global guards
                if _bot_state.news_freeze or news_calendar.is_high_impact_imminent():
                    logger.info("Auto-scan paused — news freeze/imminent event.")
                    return  # Stop the entire scan cycle until next interval

                if not risk_manager.can_open_signal(side):
                    logger.info(
                        "Auto-scan: 3-pair cap reached for %s — skipping.", side.value
                    )
                    continue

                candles = _fetch_binance_candles(ccxt_symbol, side)
                pairs_scanned += 1

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

                if result is not None:
                    risk_manager.add_signal(result)
                    messages.append(result.format_message())
                    active_symbols.add(symbol)  # prevent duplicate on opposite side
                    signals_found += 1
                    logger.info(
                        "Auto-scan signal: %s %s", symbol, side.value
                    )

                # Small delay to avoid Binance rate-limiting
                time.sleep(1)

            except Exception as exc:
                logger.error(
                    "Auto-scan error for %s %s: %s", symbol, side.value, exc
                )

    logger.info(
        "Auto-scan complete: scanned %d pairs, generated %d signal(s).",
        pairs_scanned,
        signals_found,
    )

    if not messages:
        return

    # Broadcast all new signals from the background thread
    async def _send() -> None:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            for text in messages:
                try:
                    await bot.send_message(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        text=text,
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.error("Auto-scan broadcast error: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_send())
        else:
            loop.run_until_complete(_send())
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(_send())
        finally:
            new_loop.close()
    except Exception as exc:
        logger.error("Auto-scan job failed to send broadcasts: %s", exc)

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


# ── Webhook processor (called by webhook.py) ──────────────────────────────────

def process_webhook(payload: dict) -> Optional[str]:
    """
    Parse an incoming TradingView webhook payload and return a formatted
    signal message if all confluence checks pass, otherwise None.

    Expected payload keys:
        symbol, side

    All market data (price, candles, levels) is fetched live from Binance.
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

    risk_manager.add_signal(result)
    return result.format_message()


# ── Binance live data helpers ─────────────────────────────────────────────────

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


# Module-level singleton — created once, reused for all Binance API calls
_exchange = ccxt.binance({"options": {"defaultType": "future"}})


def _fetch_binance_candles(symbol: str, side: Side) -> dict:
    """
    Fetch live OHLCV data from Binance Futures via CCXT for the given
    *symbol* (CCXT format, e.g. ``BTC/USDT:USDT``).

    Returns a dict with keys ``price``, ``range_low``, ``range_high``,
    ``key_level``, ``stop_loss``, ``5m``, ``1D``, ``4H``.
    """

    # Fetch OHLCV for each required timeframe
    # CCXT returns [[timestamp, open, high, low, close, volume], ...]
    raw_1d = _exchange.fetch_ohlcv(symbol, "1d", limit=30)
    raw_4h = _exchange.fetch_ohlcv(symbol, "4h", limit=10)
    raw_5m = _exchange.fetch_ohlcv(symbol, "5m", limit=50)

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
    ticker = _exchange.fetch_ticker(symbol)
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

# ── Application bootstrap ─────────────────────────────────────────────────────

def build_application() -> Application:
    """Create and configure the Telegram bot application."""
    if not TELEGRAM_BOT_TOKEN:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN environment variable is not set."
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("signal_gen", cmd_signal_gen))
    app.add_handler(CommandHandler("move_be", cmd_move_be))
    app.add_handler(CommandHandler("trail_sl", cmd_trail_sl))
    app.add_handler(CommandHandler("auto_scan", cmd_auto_scan))
    app.add_handler(CommandHandler("news_caution", cmd_news_caution))
    app.add_handler(CommandHandler("risk_calc", cmd_risk_calc))
    app.add_handler(CommandHandler("close_signal", cmd_close_signal))

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

    # Auto-scan job — active only when _auto_scan_active is True
    _scheduler.add_job(
        _run_auto_scan_job,
        "interval",
        seconds=AUTO_SCAN_INTERVAL_SECONDS,
        id="auto_scan",
        replace_existing=True,
    )

    if not _scheduler.running:
        _scheduler.start()
        logger.info("News calendar scheduler started (30-min refresh).")

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
