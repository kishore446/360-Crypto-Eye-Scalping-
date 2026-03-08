"""
Weekly Performance Report
=========================
Generates an automated weekly performance report that summarises signal
quality, win rates, R:R statistics, and per-channel performance.

Wire into APScheduler as a weekly job (every Sunday) in ``bot/bot.py``:

    scheduler.add_job(
        send_weekly_report,
        "cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        args=[application, dashboard],
    )
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.dashboard import Dashboard

logger = logging.getLogger(__name__)


def generate_weekly_report(dashboard: "Dashboard", days: int = 7) -> str:
    """
    Generate a Telegram-formatted weekly performance report.

    Parameters
    ----------
    dashboard:
        The live :class:`~bot.dashboard.Dashboard` instance.
    days:
        Rolling window in days.  Defaults to 7 (one week).

    Returns
    -------
    str
        Telegram-ready formatted report message.
    """
    cutoff = time.time() - days * 86400
    closed = [
        r for r in dashboard._results
        if r.outcome in ("WIN", "LOSS", "BE") and r.opened_at >= cutoff
    ]

    total = len(closed)
    wins = sum(1 for r in closed if r.outcome == "WIN")
    losses = sum(1 for r in closed if r.outcome == "LOSS")
    breakevens = sum(1 for r in closed if r.outcome == "BE")

    win_rate = round(wins / total * 100, 2) if total else 0.0
    protected_wins = wins + breakevens
    protected_win_rate = round(protected_wins / total * 100, 2) if total else 0.0

    gross_profit = sum(r.pnl_pct for r in closed if r.pnl_pct > 0)
    gross_loss = abs(sum(r.pnl_pct for r in closed if r.pnl_pct < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0

    # R:R statistics for the week
    rr_values: list[float] = []
    for r in closed:
        if r.entry_price <= 0 or r.stop_loss <= 0:
            continue
        sl_dist_pct = abs(r.entry_price - r.stop_loss) / r.entry_price * 100
        if sl_dist_pct > 0:
            rr_values.append(abs(r.pnl_pct) / sl_dist_pct)
    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0

    # Best and worst trades
    pnl_values = [r.pnl_pct for r in closed]
    best_pnl = round(max(pnl_values), 2) if pnl_values else 0.0
    worst_pnl = round(min(pnl_values), 2) if pnl_values else 0.0
    best_trade = next((r for r in closed if r.pnl_pct == best_pnl), None) if pnl_values else None
    worst_trade = next((r for r in closed if r.pnl_pct == worst_pnl), None) if pnl_values else None

    best_symbol = f"{best_trade.symbol} ({best_trade.side})" if best_trade else "—"
    worst_symbol = f"{worst_trade.symbol} ({worst_trade.side})" if worst_trade else "—"

    # Per-channel breakdown
    channel_configs = [
        ("CH1_HARD", "🔴 CH1 Hard"),
        ("CH2_MEDIUM", "🟡 CH2 Medium"),
        ("CH3_EASY", "🔵 CH3 Easy"),
        ("CH4_SPOT", "💰 CH4 Spot"),
    ]
    channel_lines: list[str] = []
    for tier_key, label in channel_configs:
        subset = [r for r in closed if r.channel_tier == tier_key]
        if not subset:
            continue
        ch_total = len(subset)
        ch_wins = sum(1 for r in subset if r.outcome == "WIN")
        ch_wr = round(ch_wins / ch_total * 100, 1)
        ch_pnl = round(sum(r.pnl_pct for r in subset), 2)
        channel_lines.append(
            f"  {label}: {ch_wr}% WR ({ch_total} signals, {ch_pnl:+.2f}% net)"
        )

    channel_section = "\n".join(channel_lines) if channel_lines else "  No channel data this week."

    # 30-day rolling equity summary
    cutoff_30d = time.time() - 30 * 86400
    closed_30d = [
        r for r in dashboard._results
        if r.outcome in ("WIN", "LOSS", "BE") and r.opened_at >= cutoff_30d
    ]
    total_30d = len(closed_30d)
    pnl_30d = round(sum(r.pnl_pct for r in closed_30d), 2)
    wr_30d = round(
        sum(1 for r in closed_30d if r.outcome == "WIN") / total_30d * 100, 2
    ) if total_30d else 0.0

    lines = [
        "📅 WEEKLY PERFORMANCE REPORT",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Period: Last {days} days",
        "",
        "📊 THIS WEEK:",
        f"  Total Signals  : {total}",
        f"  Wins / Losses  : {wins}W / {losses}L / {breakevens}BE",
        f"  Win Rate       : {win_rate:.1f}%",
        f"  Protected WR   : {protected_win_rate:.1f}%  (BE = protected win)",
        f"  Profit Factor  : {profit_factor:.2f}",
        f"  Avg R:R        : {avg_rr:.2f}R",
        "",
        "🏆 BEST / WORST:",
        f"  Best  : {best_symbol} → {best_pnl:+.2f}%",
        f"  Worst : {worst_symbol} → {worst_pnl:+.2f}%",
        "",
        "📈 BY CHANNEL:",
        channel_section,
        "",
        "📉 30-DAY ROLLING:",
        f"  Signals  : {total_30d}",
        f"  Win Rate : {wr_30d:.1f}%",
        f"  Net PnL  : {pnl_30d:+.2f}%",
    ]
    return "\n".join(lines)
