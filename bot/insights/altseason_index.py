"""
CH5 Enhanced — Altseason Index
Calculates and formats the altseason index based on BTC vs altcoin 7-day returns.
"""
from __future__ import annotations

try:
    from config import ALTSEASON_POST_INTERVAL_HOURS, TELEGRAM_CHANNEL_ID_INSIGHTS
except Exception:  # pragma: no cover
    ALTSEASON_POST_INTERVAL_HOURS = 6
    TELEGRAM_CHANNEL_ID_INSIGHTS = 0


def calculate_altseason_score(btc_7d_change: float, alt_avg_7d_change: float) -> float:
    """
    Return altseason score from 0 to 100.

    Score formula: normalise the spread (alt_avg - btc) from [-20, +20] → [0, 100].
    A score of 100 = maximum altseason signal.
    """
    diff = alt_avg_7d_change - btc_7d_change
    return max(0.0, min(100.0, (diff + 20.0) / 40.0 * 100.0))


def format_altseason_index(btc_7d_change: float, alt_avg_7d_change: float) -> str:
    """
    Return a Telegram-formatted altseason index message.

    *btc_7d_change* and *alt_avg_7d_change* are percentage changes (e.g. 5.0 = +5%).
    """
    score = calculate_altseason_score(btc_7d_change, alt_avg_7d_change)
    diff = alt_avg_7d_change - btc_7d_change
    is_altseason = diff > 5.0

    bar_filled = int(score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    if score >= 75:
        status = "🔥 Altseason — Alts Outperforming"
    elif score >= 55:
        status = "📈 Altseason Heating Up"
    elif score >= 45:
        status = "⚖️ Neutral — Mixed Market"
    elif score >= 25:
        status = "📉 BTC Dominance Phase"
    else:
        status = "🏦 Heavy BTC Dominance"

    btc_dir = "+" if btc_7d_change >= 0 else ""
    alt_dir = "+" if alt_avg_7d_change >= 0 else ""
    diff_dir = "+" if diff >= 0 else ""

    lines = [
        "🌙 ALTSEASON INDEX",
        "──────────────────────────",
        f"Score: {score:.0f}/100  [{bar}]",
        f"Status: {status}",
        "──────────────────────────",
        f"BTC 7d: {btc_dir}{btc_7d_change:.1f}%",
        f"Alt avg 7d: {alt_dir}{alt_avg_7d_change:.1f}%",
        f"Spread: {diff_dir}{diff:.1f}%",
    ]
    if is_altseason:
        lines.append("⚡ Alts outperforming BTC by >5% — Altseason Heating Up!")
    return "\n".join(lines)


def get_target_channel_id() -> int:
    """Return the CH5 insights channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_INSIGHTS
