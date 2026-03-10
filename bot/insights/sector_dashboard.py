"""
CH5 Enhanced — Sector Dashboard
Ranks crypto sectors by 7-day weighted return with a visual bar chart.
"""
from __future__ import annotations

try:
    from config import SECTOR_DASHBOARD_HOUR_UTC, TELEGRAM_CHANNEL_ID_INSIGHTS
except Exception:  # pragma: no cover
    SECTOR_DASHBOARD_HOUR_UTC = 12
    TELEGRAM_CHANNEL_ID_INSIGHTS = 0

_BAR_MAX_WIDTH = 10
_BAR_CHAR = "█"
_BAR_EMPTY = "░"


def _make_bar(value: float, max_abs: float, width: int = _BAR_MAX_WIDTH) -> str:
    """Return a Unicode block bar scaled to *max_abs*."""
    if max_abs == 0:
        filled = 0
    else:
        filled = int(abs(value) / max_abs * width)
    bar = _BAR_CHAR * filled + _BAR_EMPTY * (width - filled)
    return bar


def format_sector_dashboard(sector_returns: dict[str, float]) -> str:
    """
    Return a Telegram-formatted sector dashboard.

    *sector_returns* maps sector_name → 7-day return percentage.
    Sectors are ranked from highest to lowest return.
    """
    if not sector_returns:
        return "🔄 SECTOR ROTATION\n──────────────────────────\nNo sector data available."

    ranked = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
    max_abs = max(abs(v) for _, v in ranked) or 1.0

    lines = [
        "🔄 SECTOR ROTATION DASHBOARD",
        "──────────────────────────",
    ]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, (sector, ret) in enumerate(ranked, start=1):
        bar = _make_bar(ret, max_abs)
        direction = "+" if ret >= 0 else ""
        rank_icon = medals.get(i, f"#{i}")
        lines.append(f"{rank_icon} {sector:8s} {bar} {direction}{ret:.1f}%")

    lines.append("──────────────────────────")
    best = ranked[0][0] if ranked else "N/A"
    worst = ranked[-1][0] if ranked else "N/A"
    lines.append(f"🏆 Best: {best}  |  📉 Worst: {worst}")
    return "\n".join(lines)


def get_target_channel_id() -> int:
    """Return the CH5 insights channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_INSIGHTS
