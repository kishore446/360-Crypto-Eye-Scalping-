"""
CH5E — Daily Performance Recap
================================
Posts an auto-generated daily performance summary at 23:00 UTC every day
to the Insights channel. Shows per-channel stats to build trust.

Format:
  📊 360 CRYPTO EYE — DAILY PERFORMANCE RECAP
  ─────────────────────────────────────────────
  📅 2026-03-06

  CH1 Hard Scalp:   3/4 wins (75%) | +4.2R total
  CH2 Medium Scalp: 5/7 wins (71%) | +3.8R total
  CH3 Easy Breakout: 2/3 wins (67%) | +2.1R total
  CH4 Spot:         1/1 active setups

  🏆 Best Signal: #SOL/USDT LONG +2.5R (CH1)
  📉 Worst Signal: #DOGE/USDT SHORT -1.0R (CH2)

  🔥 Streak: 5 consecutive wins
  📈 Weekly: +18.4R cumulative
"""
from __future__ import annotations

import datetime


def format_daily_performance(dashboard, signal_tracker=None) -> str:
    """
    Generate the daily recap message from dashboard stats.

    Parameters
    ----------
    dashboard:
        A :class:`bot.dashboard.Dashboard` instance.
    signal_tracker:
        Optional signal tracker — reserved for future per-channel breakdown.
    """
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    total = dashboard.total_trades()
    win_rate = dashboard.win_rate()
    profit_factor = dashboard.profit_factor()
    sharpe = dashboard.sharpe_ratio()
    drawdown = dashboard.max_drawdown()
    w_streak = dashboard.win_streak()
    l_streak = dashboard.loss_streak()
    open_pnl = dashboard.current_open_pnl()

    # Equity curve — last 7 data points for weekly context
    curve = dashboard.equity_curve()
    weekly_pnl = round(sum(curve[-7:]), 4) if len(curve) >= 7 else round(sum(curve), 4)

    # Best and worst closed trades
    closed = dashboard.get_closed_trades()
    best = max(closed, key=lambda r: r.pnl_pct, default=None)
    worst = min(closed, key=lambda r: r.pnl_pct, default=None)

    streak_line = (
        f"🔥 Win Streak: {w_streak} consecutive wins"
        if w_streak > 0
        else f"📉 Loss Streak: {l_streak} consecutive losses"
    )

    lines = [
        "📊 360 CRYPTO EYE — DAILY PERFORMANCE RECAP",
        "─────────────────────────────────────────────",
        f"📅 {today}",
        "",
        f"Total Closed Trades : {total}",
        f"Win Rate            : {win_rate:.2f}%",
        f"  → 5m entries      : {dashboard.win_rate('5m'):.2f}%",
        f"  → 15m entries     : {dashboard.win_rate('15m'):.2f}%",
        f"  → 1h entries      : {dashboard.win_rate('1h'):.2f}%",
        f"Profit Factor       : {profit_factor:.2f}",
        f"Sharpe Ratio        : {sharpe:.4f}",
        f"Max Drawdown        : {drawdown:.2f}%",
        f"Open PnL (floating) : {open_pnl:+.2f}%",
        "",
    ]

    if best:
        lines.append(
            f"🏆 Best Signal: #{best.symbol}/USDT {best.side} {best.pnl_pct:+.2f}%"
        )
    if worst and worst is not best:
        lines.append(
            f"📉 Worst Signal: #{worst.symbol}/USDT {worst.side} {worst.pnl_pct:+.2f}%"
        )

    lines += [
        "",
        streak_line,
        f"📈 Weekly PnL: {weekly_pnl:+.2f}%",
    ]

    return "\n".join(lines)
