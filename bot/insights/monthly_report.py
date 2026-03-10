"""
Monthly Performance Report — CH5 Insights (CH5K)
=================================================
Generates a comprehensive monthly performance report from the Dashboard,
posted to CH5 Insights at the start of each new month.
"""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.dashboard import Dashboard

__all__ = ["format_monthly_report"]


def format_monthly_report(dashboard: "Dashboard", month: int, year: int) -> str:
    """
    Generate a comprehensive monthly performance report.

    Parameters
    ----------
    dashboard:
        ``Dashboard`` instance containing all trade results.
    month:
        Month number (1–12).
    year:
        Four-digit year (e.g. 2026).

    Returns
    -------
    str
        Telegram-formatted monthly report.
    """
    month_name = calendar.month_name[month]

    # Compute the UTC timestamp range for the given month
    import calendar as _cal
    _, days_in_month = _cal.monthrange(year, month)
    import datetime
    start_dt = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
    end_dt = datetime.datetime(year, month, days_in_month, 23, 59, 59, tzinfo=datetime.timezone.utc)
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()

    closed = [
        r for r in dashboard.get_closed_trades()
        if r.opened_at >= start_ts and r.opened_at <= end_ts
    ]

    total = len(closed)
    wins = sum(1 for r in closed if r.outcome == "WIN")
    win_rate = round(wins / total * 100, 1) if total else 0.0
    total_pnl = round(sum(r.pnl_pct for r in closed), 2)

    # Max drawdown for the month subset
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in closed:
        cumulative += r.pnl_pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Best / worst trade
    best = max(closed, key=lambda r: r.pnl_pct, default=None)
    worst = min(closed, key=lambda r: r.pnl_pct, default=None)

    best_str = (
        f"{best.symbol} {best.side} {best.pnl_pct:+.1f}% ({best.channel_tier})"
        if best else "N/A"
    )
    worst_str = (
        f"{worst.symbol} {worst.side} {worst.pnl_pct:+.1f}% ({worst.channel_tier})"
        if worst else "N/A"
    )

    # Per-channel breakdown
    channel_lines: list[str] = []
    for tier, label in [
        ("CH1_SCALPING", "CH1"), ("CH2_INTRADAY", "CH2"),
        ("CH3_TREND", "CH3"), ("CH4_SPOT", "CH4"),
    ]:
        subset = [r for r in closed if r.channel_tier == tier]
        n = len(subset)
        if n == 0:
            continue
        w = sum(1 for r in subset if r.outcome == "WIN")
        wr = round(w / n * 100, 1)
        channel_lines.append(f"  {label}: {wr:.1f}% WR ({n} signals)")

    channel_block = "\n".join(channel_lines) if channel_lines else "  No signals recorded."

    # Sharpe & profit factor for the month
    pnl_values = [r.pnl_pct for r in closed]
    sharpe = 0.0
    if len(pnl_values) >= 3:
        import math
        mean_r = sum(pnl_values) / len(pnl_values)
        variance = sum((r - mean_r) ** 2 for r in pnl_values) / (len(pnl_values) - 1)
        std_r = math.sqrt(variance)
        if std_r > 0:
            sharpe = round(mean_r / std_r, 2)

    gross_profit = sum(r.pnl_pct for r in closed if r.pnl_pct > 0)
    gross_loss = abs(sum(r.pnl_pct for r in closed if r.pnl_pct < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0

    return (
        f"📅 *MONTHLY PERFORMANCE REPORT — {month_name} {year}*\n\n"
        f"Total Signals: {total} | Win Rate: {win_rate:.1f}%\n"
        f"Total PnL: {total_pnl:+.1f}% | Max Drawdown: -{max_dd:.1f}%\n"
        f"Best Trade: {best_str}\n"
        f"Worst Trade: {worst_str}\n\n"
        f"By Channel:\n{channel_block}\n\n"
        f"Sharpe Ratio: {sharpe:.2f} | Profit Factor: {profit_factor:.2f}"
    )
