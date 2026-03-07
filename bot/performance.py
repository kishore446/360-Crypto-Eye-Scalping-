"""
Performance Metrics
===================
Public performance summary API for the 360 Crypto Eye Scalping bot.

Computes and formats rolling performance statistics including:
  - Rolling win rate (7-day and 30-day windows)
  - Profit factor
  - Sharpe ratio estimate
  - Maximum drawdown
  - Comparison against BTC buy-and-hold

All functions accept a list of :class:`~bot.dashboard.TradeResult` objects
and are stateless — they hold no persistent state of their own.
"""
from __future__ import annotations

import math
import time
from typing import Optional

__all__ = [
    "rolling_win_rate",
    "rolling_profit_factor",
    "sharpe_ratio",
    "max_drawdown",
    "compare_vs_btc",
    "format_performance_summary",
]


def rolling_win_rate(trades: list, days: int = 7) -> float:
    """
    Return the win rate (%) for trades closed within the last *days* calendar days.

    Parameters
    ----------
    trades:
        List of :class:`~bot.dashboard.TradeResult` objects.
    days:
        Look-back window in days (default 7).

    Returns
    -------
    Win rate as a percentage (0–100).  Returns ``0.0`` when no qualifying
    trades exist.
    """
    cutoff = time.time() - days * 86400
    closed = [
        t for t in trades
        if t.outcome in ("WIN", "LOSS", "BE")
        and t.closed_at is not None
        and t.closed_at >= cutoff
    ]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t.outcome == "WIN")
    return round(wins / len(closed) * 100, 2)


def rolling_profit_factor(trades: list, days: int = 30) -> float:
    """
    Return the profit factor (gross profit / gross loss) for trades closed
    within the last *days* calendar days.

    Returns ``0.0`` when there are no losing trades in the window (undefined).
    """
    cutoff = time.time() - days * 86400
    closed = [
        t for t in trades
        if t.outcome in ("WIN", "LOSS")
        and t.closed_at is not None
        and t.closed_at >= cutoff
    ]
    gross_profit = sum(t.pnl_pct for t in closed if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in closed if t.pnl_pct < 0))
    if gross_loss == 0:
        return 0.0
    return round(gross_profit / gross_loss, 4)


def sharpe_ratio(trades: list, risk_free_rate: float = 0.0) -> float:
    """
    Return the annualised Sharpe Ratio estimate from all closed trades.

    Uses Bessel's correction (n-1) for sample standard deviation.
    Returns ``0.0`` when fewer than 3 closed trades exist or std is zero.
    """
    closed = [t for t in trades if t.outcome in ("WIN", "LOSS", "BE")]
    if len(closed) < 3:
        return 0.0
    returns = [t.pnl_pct for t in closed]
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0
    return round((mean_r - risk_free_rate) / std_r, 4)


def max_drawdown(trades: list) -> float:
    """
    Return the maximum peak-to-trough drawdown as a positive percentage
    across the cumulative equity curve of all closed trades.

    Returns ``0.0`` when there are no closed trades.
    """
    closed = [t for t in trades if t.outcome in ("WIN", "LOSS", "BE")]
    if not closed:
        return 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in closed:
        equity += t.pnl_pct
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


def compare_vs_btc(
    trades: list,
    btc_return_pct: Optional[float] = None,
    days: int = 30,
) -> dict:
    """
    Compare the bot's rolling 30-day return against BTC buy-and-hold.

    Parameters
    ----------
    trades:
        List of :class:`~bot.dashboard.TradeResult` objects.
    btc_return_pct:
        BTC price change % over *days* (positive = BTC went up).
        When ``None``, the comparison is skipped and the BTC field is ``None``.
    days:
        Look-back window in days (default 30).

    Returns
    -------
    dict with keys:

    - ``bot_return_pct``: sum of PnL % for closed trades in the window.
    - ``btc_return_pct``: the supplied BTC benchmark (may be ``None``).
    - ``alpha_pct``: bot return minus BTC return (may be ``None``).
    - ``trade_count``: number of trades closed in the window.
    """
    cutoff = time.time() - days * 86400
    closed = [
        t for t in trades
        if t.outcome in ("WIN", "LOSS", "BE")
        and t.closed_at is not None
        and t.closed_at >= cutoff
    ]
    bot_return = round(sum(t.pnl_pct for t in closed), 4)
    alpha: Optional[float] = None
    if btc_return_pct is not None:
        alpha = round(bot_return - btc_return_pct, 4)
    return {
        "bot_return_pct": bot_return,
        "btc_return_pct": btc_return_pct,
        "alpha_pct": alpha,
        "trade_count": len(closed),
    }


def format_performance_summary(
    trades: list,
    btc_return_pct: Optional[float] = None,
) -> str:
    """
    Format a human-readable performance summary string.

    Parameters
    ----------
    trades:
        List of :class:`~bot.dashboard.TradeResult` objects.
    btc_return_pct:
        Optional BTC benchmark return % for comparison.

    Returns
    -------
    Multi-line string suitable for Telegram broadcast.
    """
    wr7 = rolling_win_rate(trades, days=7)
    wr30 = rolling_win_rate(trades, days=30)
    pf = rolling_profit_factor(trades, days=30)
    sharpe = sharpe_ratio(trades)
    mdd = max_drawdown(trades)
    btc_cmp = compare_vs_btc(trades, btc_return_pct=btc_return_pct)

    lines = [
        "📊 360 Eye Performance Summary",
        f"Win Rate (7d):   {wr7:.1f}%",
        f"Win Rate (30d):  {wr30:.1f}%",
        f"Profit Factor:   {pf:.2f}",
        f"Sharpe Ratio:    {sharpe:.2f}",
        f"Max Drawdown:    {mdd:.2f}%",
    ]
    if btc_cmp["btc_return_pct"] is not None:
        lines += [
            f"Bot 30d Return:  {btc_cmp['bot_return_pct']:+.2f}%",
            f"BTC 30d Return:  {btc_cmp['btc_return_pct']:+.2f}%",
            f"Alpha vs BTC:    {btc_cmp['alpha_pct']:+.2f}%",
        ]
    lines.append(f"Trades (30d):    {btc_cmp['trade_count']}")
    return "\n".join(lines)
