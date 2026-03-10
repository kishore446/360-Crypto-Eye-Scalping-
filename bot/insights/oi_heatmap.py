"""
CH5 Enhanced — Open Interest Heatmap
Shows top coins by OI change in the last 4 hours with emoji indicators.
"""
from __future__ import annotations

try:
    from config import OI_HEATMAP_INTERVAL_HOURS, TELEGRAM_CHANNEL_ID_INSIGHTS
except Exception:  # pragma: no cover
    OI_HEATMAP_INTERVAL_HOURS = 4
    TELEGRAM_CHANNEL_ID_INSIGHTS = 0

_TOP_N = 10


def _oi_emoji(change_pct: float) -> str:
    """Return an emoji based on OI change magnitude."""
    abs_change = abs(change_pct)
    if abs_change >= 10:
        return "🔥"
    if abs_change >= 5:
        return "⚡"
    if abs_change >= 2:
        return "📊"
    return "➡️"


def format_oi_heatmap(oi_changes: dict[str, float]) -> str:
    """
    Return a Telegram-formatted OI heatmap message.

    *oi_changes* maps symbol → OI change percentage over the last 4 hours.
    Shows the top *_TOP_N* coins by absolute OI change.
    Emoji indicators:
      🔥  >= 10% change
      ⚡  >= 5%
      📊  >= 2%
      ➡️  < 2%
    """
    if not oi_changes:
        return (
            "📈 OI HEATMAP (4H)\n"
            "──────────────────────────\n"
            "No OI data available."
        )

    ranked = sorted(oi_changes.items(), key=lambda x: abs(x[1]), reverse=True)[:_TOP_N]

    lines = [
        "📈 OI HEATMAP (4H)",
        "──────────────────────────",
    ]
    for symbol, change in ranked:
        emoji = _oi_emoji(change)
        direction = "+" if change >= 0 else ""
        base = symbol.replace("USDT", "").replace("/USDT", "")
        lines.append(f"{emoji} {base:8s} {direction}{change:.1f}%")

    lines.append("──────────────────────────")
    if ranked:
        top_sym = ranked[0][0].replace("USDT", "")
        top_val = ranked[0][1]
        direction = "+" if top_val >= 0 else ""
        lines.append(f"📌 Highest OI Change: {top_sym} {direction}{top_val:.1f}%")
    return "\n".join(lines)


def get_target_channel_id() -> int:
    """Return the CH5 insights channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_INSIGHTS
