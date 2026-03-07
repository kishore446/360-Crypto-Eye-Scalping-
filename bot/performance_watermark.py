"""
Performance Watermark
=====================
Generates a single-line live win-rate badge for each channel tier based on
rolling 30-day statistics from the Dashboard.

The badge is embedded into outgoing signal messages to provide subscribers
with transparent, real-time performance context.

Example output::

    📈 CH1 30d: 78.4% WR (51 signals) | Sharpe 2.14
"""
from __future__ import annotations

import math
import time
from typing import Optional

from bot.dashboard import Dashboard


_CHANNEL_LABELS: dict[str, str] = {
    "CH1_HARD": "CH1",
    "CH2_MEDIUM": "CH2",
    "CH3_EASY": "CH3",
    "CH4_SPOT": "CH4",
    "AGGREGATE": "ALL",
}


def _compute_sharpe(pnl_values: list[float], risk_free_rate: float = 0.0) -> float:
    """
    Compute the Sharpe ratio for a list of PnL percentages.

    Returns 0.0 when fewer than 3 data points exist or standard deviation is zero.
    Uses Bessel's correction (n-1) for an unbiased sample variance.
    """
    n = len(pnl_values)
    if n < 3:
        return 0.0
    mean_r = sum(pnl_values) / n
    variance = sum((r - mean_r) ** 2 for r in pnl_values) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0.0:
        return 0.0
    return round((mean_r - risk_free_rate) / std_r, 2)


def get_channel_watermark(
    dashboard: Dashboard,
    channel_tier: str,
    days: int = 30,
) -> Optional[str]:
    """
    Return a single-line performance badge for *channel_tier* over the last
    *days* days, or ``None`` when there is insufficient data (fewer than 3
    closed trades in the window).

    Parameters
    ----------
    dashboard:
        The live :class:`~bot.dashboard.Dashboard` instance.
    channel_tier:
        One of ``"CH1_HARD"``, ``"CH2_MEDIUM"``, ``"CH3_EASY"``,
        ``"CH4_SPOT"``, or ``"AGGREGATE"``.
    days:
        Rolling window length in days. Defaults to 30.

    Returns
    -------
    str or None
        Formatted badge string, e.g.
        ``"📈 CH1 30d: 78.4% WR (51 signals) | Sharpe 2.14"``,
        or ``None`` when there is not enough history.
    """
    cutoff = time.time() - days * 86_400
    closed = [
        r
        for r in dashboard._results  # noqa: SLF001  # accessing internal list intentionally
        if r.outcome in ("WIN", "LOSS", "BE")
        and r.channel_tier == channel_tier
        and r.opened_at >= cutoff
    ]

    total = len(closed)
    if total < 3:
        return None

    wins = sum(1 for r in closed if r.outcome == "WIN")
    win_rate = round(wins / total * 100, 1)
    pnl_values = [r.pnl_pct for r in closed]
    sharpe = _compute_sharpe(pnl_values)

    label = _CHANNEL_LABELS.get(channel_tier, channel_tier)
    return f"📈 {label} {days}d: {win_rate}% WR ({total} signals) | Sharpe {sharpe:.2f}"


def get_watermark_line(
    dashboard: Dashboard,
    channel_tier: str,
    days: int = 30,
) -> str:
    """
    Convenience wrapper that always returns a string.

    Returns the badge from :func:`get_channel_watermark` when data is
    available, otherwise an empty string so callers can safely embed the
    result in messages without ``None`` checks.

    Parameters
    ----------
    dashboard:
        The live :class:`~bot.dashboard.Dashboard` instance.
    channel_tier:
        Channel tier identifier.
    days:
        Rolling window length in days.
    """
    result = get_channel_watermark(dashboard, channel_tier, days)
    return result if result is not None else ""
