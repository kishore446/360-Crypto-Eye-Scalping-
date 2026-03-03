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

import logging
from typing import Optional

import ccxt

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from bot.dashboard import Dashboard, TradeResult
from bot.news_filter import NewsCalendar
from bot.risk_manager import RiskManager, calculate_position_size
from bot.signal_engine import (
    CandleData,
    Side,
    run_confluence_check,
)
from config import (
    ADMIN_CHAT_ID,
    LEVERAGE_MAX,
    LEVERAGE_MIN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)

logger = logging.getLogger(__name__)

# ── Shared state (singleton per process) ─────────────────────────────────────

risk_manager = RiskManager()
news_calendar = NewsCalendar()
dashboard = Dashboard()

# When True, /news_caution has frozen new-signal generation
_news_freeze: bool = False

# When True, auto-trailing is active for open signals
_trail_active: bool = False


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

    global _news_freeze
    if _news_freeze:
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

    active = risk_manager.add_signal(result)
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

    global _trail_active
    _trail_active = not _trail_active
    state = "ACTIVATED ✅" if _trail_active else "DEACTIVATED ❌"
    msg = f"📈 Auto-Trailing SL is now *{state}*."
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

    global _news_freeze
    _news_freeze = not _news_freeze

    if _news_freeze:
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

    if _news_freeze or news_calendar.is_high_impact_imminent():
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


def _fetch_binance_candles(symbol: str, side: Side) -> dict:
    """
    Fetch live OHLCV data from Binance Futures via CCXT for the given
    *symbol* (CCXT format, e.g. ``BTC/USDT:USDT``).

    Returns a dict with the same keys as :func:`_make_demo_candles`:
    ``price``, ``range_low``, ``range_high``, ``key_level``, ``stop_loss``,
    ``5m``, ``1D``, ``4H``.
    """
    exchange = ccxt.binance({"options": {"defaultType": "future"}})

    # Fetch OHLCV for each required timeframe
    # CCXT returns [[timestamp, open, high, low, close, volume], ...]
    raw_1d = exchange.fetch_ohlcv(symbol, "1d", limit=30)
    raw_4h = exchange.fetch_ohlcv(symbol, "4h", limit=10)
    raw_5m = exchange.fetch_ohlcv(symbol, "5m", limit=50)

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
    ticker = exchange.fetch_ticker(symbol)
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


# ── Demo candle factory (replace with live Binance API in production) ─────────

def _make_demo_candles(
    side: Side,
    price: float = 100.0,
) -> dict:
    """
    Build minimal synthetic OHLCV data that satisfies all confluence gates,
    used when no real market data is available (e.g. during testing or demo).
    """
    direction = 1 if side == Side.LONG else -1
    base = price

    # Synthetic 1D candles: bullish / bearish trend
    daily_candles = [
        CandleData(
            open=base - direction * i * 2,
            high=base - direction * i * 2 + 1,
            low=base - direction * i * 2 - 1,
            close=base - direction * i * 2 + direction * 0.5,
            volume=1000 + i * 10,
        )
        for i in range(20, 0, -1)
    ]

    # Synthetic 4H candles: same directional bias
    four_h_candles = [
        CandleData(
            open=base - direction * i * 0.5,
            high=base - direction * i * 0.5 + 0.3,
            low=base - direction * i * 0.5 - 0.3,
            close=base - direction * i * 0.5 + direction * 0.2,
            volume=500 + i * 5,
        )
        for i in range(5, 0, -1)
    ]

    # Synthetic 5m candles with a liquidity sweep and MSS
    avg_vol = 200.0
    key_level = base - direction * 1.0  # level to be swept
    five_m_candles = [
        # Regular candles
        CandleData(open=base, high=base + 0.2, low=base - 0.2, close=base + 0.1, volume=avg_vol * 0.9),
        CandleData(open=base + 0.1, high=base + 0.3, low=base - 0.3, close=base + 0.2, volume=avg_vol * 0.8),
        # Sweep candle: wick pierces key_level, body closes back
        CandleData(
            open=base,
            high=base + 0.5 if side == Side.SHORT else base + 0.2,
            low=key_level - 0.1 if side == Side.LONG else base - 0.2,
            close=base + 0.3 if side == Side.LONG else base - 0.3,
            volume=avg_vol * 1.1,
        ),
        # MSS candle: closes beyond prior swing high/low with high volume
        CandleData(
            open=base,
            high=base + 0.8 if side == Side.LONG else base + 0.1,
            low=base - 0.1 if side == Side.LONG else base - 0.8,
            close=base + 0.6 if side == Side.LONG else base - 0.6,
            volume=avg_vol * 1.5,
        ),
    ]

    range_spread = abs(base) * 0.05 or 5.0
    stop_loss = (
        key_level - 0.5 if side == Side.LONG else key_level + 0.5
    )
    current_price = (
        base - range_spread * 0.3 if side == Side.LONG else base + range_spread * 0.3
    )

    return {
        "price": current_price,
        "range_low": base - range_spread,
        "range_high": base + range_spread,
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
    app.add_handler(CommandHandler("news_caution", cmd_news_caution))
    app.add_handler(CommandHandler("risk_calc", cmd_risk_calc))
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
