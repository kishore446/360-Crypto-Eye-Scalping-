"""
User Interaction Commands
Telegram command handlers for /market, /signals, /learn, /risk, /sectors.
Register all commands by calling register_commands(application).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid heavy imports at module level


def _format_market_overview(
    btc_price: float,
    btc_change_24h: float,
    market_regime: str,
    fear_greed_score: int,
    fear_greed_label: str,
    top_movers: list[dict],
) -> str:
    """
    Return a Telegram-formatted market overview string.

    *top_movers* is a list of dicts with keys: symbol, change_24h.
    """
    direction = "+" if btc_change_24h >= 0 else ""
    regime_emoji = {
        "BULL": "🐂",
        "BEAR": "🐻",
        "SIDEWAYS": "↔️",
        "UNKNOWN": "❓",
    }.get(market_regime.upper(), "❓")

    if fear_greed_score >= 75:
        fg_emoji = "🤑"
    elif fear_greed_score >= 55:
        fg_emoji = "😊"
    elif fear_greed_score >= 45:
        fg_emoji = "😐"
    elif fear_greed_score >= 25:
        fg_emoji = "😟"
    else:
        fg_emoji = "😱"

    lines = [
        "📊 MARKET OVERVIEW",
        "──────────────────────────",
        f"₿ BTC: ${btc_price:,.2f} ({direction}{btc_change_24h:.1f}% 24h)",
        f"{regime_emoji} Regime: {market_regime}",
        f"{fg_emoji} Fear & Greed: {fear_greed_score} — {fear_greed_label}",
    ]

    if top_movers:
        lines.append("──────────────────────────")
        lines.append("🏆 Top Movers (24h):")
        for mover in top_movers[:3]:
            sym = mover.get("symbol", "?").replace("USDT", "")
            chg = mover.get("change_24h", 0)
            chg_dir = "+" if chg >= 0 else ""
            lines.append(f"  • {sym}: {chg_dir}{chg:.1f}%")

    return "\n".join(lines)


def format_market_command(
    btc_price: float = 0.0,
    btc_change_24h: float = 0.0,
    market_regime: str = "UNKNOWN",
    fear_greed_score: int = 50,
    fear_greed_label: str = "Neutral",
    top_movers: list[dict] | None = None,
) -> str:
    """Return formatted /market command response."""
    return _format_market_overview(
        btc_price=btc_price,
        btc_change_24h=btc_change_24h,
        market_regime=market_regime,
        fear_greed_score=fear_greed_score,
        fear_greed_label=fear_greed_label,
        top_movers=top_movers or [],
    )


def format_signals_command(
    active_count: int,
    signals: list[dict] | None = None,
) -> str:
    """
    Return formatted /signals command response.

    *signals* is a list of dicts with keys: symbol, side, pnl_pct (optional).
    """
    if active_count == 0:
        return "📡 ACTIVE SIGNALS\n──────────────────────────\nNo active signals right now."

    lines = [
        f"📡 ACTIVE SIGNALS ({active_count})",
        "──────────────────────────",
    ]
    for sig in (signals or [])[:10]:
        symbol = sig.get("symbol", "???").replace("USDT", "")
        side = sig.get("side", "?")
        pnl = sig.get("pnl_pct")
        if pnl is not None:
            direction = "+" if pnl >= 0 else ""
            lines.append(f"• {symbol} [{side}] — {direction}{pnl:.1f}%")
        else:
            lines.append(f"• {symbol} [{side}]")

    return "\n".join(lines)


def format_learn_command(term: str) -> str:
    """
    Return formatted /learn <term> command response.

    Looks up *term* in the education module's GLOSSARY.
    """
    from bot.channels.education import lookup_glossary

    definition = lookup_glossary(term)
    if definition is None:
        available = ", ".join(sorted(["FVG", "OB", "MSS", "BOS", "RSI", "OI", "FR", "ATR", "RR"]))
        return (
            f"❓ Unknown term: '{term}'\n\n"
            f"Try: /learn FVG, /learn OB, /learn RSI, etc.\n"
            f"Common terms: {available}"
        )
    term_upper = term.strip().upper()
    return f"📖 {term_upper}\n──────────────────────────\n{definition}"


def format_risk_command(
    balance: float,
    entry: float,
    stop_loss: float,
    symbol: str = "BTC",
    risk_pct: float = 1.0,
) -> str:
    """
    Return formatted /risk command response.

    Delegates to the VIP module's risk calculator.
    """
    from bot.channels.vip import format_risk_calculator

    try:
        return format_risk_calculator(
            balance=balance,
            entry_price=entry,
            stop_loss=stop_loss,
            risk_pct=risk_pct,
            symbol=symbol,
        )
    except ValueError as exc:
        return f"⚠️ Risk calculation error: {exc}"


def format_sectors_command(sector_returns: dict[str, float] | None = None) -> str:
    """
    Return formatted /sectors command response.

    Delegates to the sector dashboard formatter.
    """
    from bot.insights.sector_dashboard import format_sector_dashboard

    if not sector_returns:
        return "🔄 SECTOR DATA\n──────────────────────────\nNo sector data available yet."
    return format_sector_dashboard(sector_returns)


# ── Telegram application command registration ─────────────────────────────────


def register_commands(application: object) -> None:
    """
    Register all user-facing command handlers with *application*.

    *application* must be a python-telegram-bot Application instance.
    Handlers are added for: /market, /signals, /learn, /risk, /sectors.
    """
    from telegram.ext import CommandHandler

    application.add_handler(CommandHandler("market", _cmd_market))
    application.add_handler(CommandHandler("signals", _cmd_signals))
    application.add_handler(CommandHandler("learn", _cmd_learn))
    application.add_handler(CommandHandler("risk", _cmd_risk))
    application.add_handler(CommandHandler("sectors", _cmd_sectors))


async def _cmd_market(update: object, context: object) -> None:
    """Handle /market command — quick market overview."""
    msg = format_market_command()
    await update.message.reply_text(msg)  # type: ignore[attr-defined]


async def _cmd_signals(update: object, context: object) -> None:
    """Handle /signals command — active signals summary."""
    msg = format_signals_command(active_count=0)
    await update.message.reply_text(msg)  # type: ignore[attr-defined]


async def _cmd_learn(update: object, context: object) -> None:
    """Handle /learn <topic> command — glossary lookup."""
    args = getattr(context, "args", []) or []
    if not args:
        await update.message.reply_text(  # type: ignore[attr-defined]
            "Usage: /learn <term>\nExamples: /learn FVG, /learn OB, /learn RSI"
        )
        return
    term = " ".join(args)
    msg = format_learn_command(term)
    await update.message.reply_text(msg)  # type: ignore[attr-defined]


async def _cmd_risk(update: object, context: object) -> None:
    """Handle /risk <balance> <entry> <sl> command — position size calculator."""
    args = getattr(context, "args", []) or []
    if len(args) < 3:
        await update.message.reply_text(  # type: ignore[attr-defined]
            "Usage: /risk <balance> <entry> <stop_loss>\n"
            "Example: /risk 1000 95000 93000"
        )
        return
    try:
        balance = float(args[0])
        entry = float(args[1])
        sl = float(args[2])
    except ValueError:
        await update.message.reply_text(  # type: ignore[attr-defined]
            "⚠️ All arguments must be numbers.\n"
            "Example: /risk 1000 95000 93000"
        )
        return
    msg = format_risk_command(balance=balance, entry=entry, stop_loss=sl)
    await update.message.reply_text(msg)  # type: ignore[attr-defined]


async def _cmd_sectors(update: object, context: object) -> None:
    """Handle /sectors command — sector rotation dashboard."""
    msg = format_sectors_command()
    await update.message.reply_text(msg)  # type: ignore[attr-defined]
