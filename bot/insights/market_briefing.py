"""
Daily Market Briefing
=====================
Generates and posts an automated daily briefing to CH5 (Insights channel).

Assembles:
  - Market regime
  - Fear & Greed Index
  - Active signal count by side
  - Rolling 7d and 30d win rate + profit factor
  - Top and worst performing pairs (7d)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.dashboard import Dashboard
    from bot.risk_manager import RiskManager
    from bot.state import BotState
    from bot.ws_manager import MarketDataStore

logger = logging.getLogger(__name__)

__all__ = ["generate_daily_briefing"]


def _fetch_fear_greed() -> tuple[str, str]:
    """
    Fetch the Fear & Greed index from the alternative.me API.

    Returns (value_str, label) on success, or ("N/A", "N/A") on failure.
    """
    try:
        import httpx  # type: ignore[import-untyped]

        with httpx.Client(timeout=5.0) as client:
            resp = client.get("https://api.alternative.me/fng/")
            resp.raise_for_status()
            data = resp.json()
            entry = data["data"][0]
            return str(entry["value"]), str(entry["value_classification"])
    except Exception as exc:
        logger.warning("Fear & Greed fetch failed: %s", exc)
        return "N/A", "N/A"


def _rolling_win_rate(dashboard: "Dashboard", days: int) -> tuple[float, int]:
    """Return (win_rate_pct, n_signals) for the rolling *days* window."""
    import time

    cutoff = time.time() - days * 86400
    closed = [
        r
        for r in dashboard.get_closed_trades()
        if r.opened_at >= cutoff
    ]
    if not closed:
        return 0.0, 0
    wins = sum(1 for r in closed if r.outcome == "WIN")
    return round(wins / len(closed) * 100, 1), len(closed)


def _rolling_profit_factor(dashboard: "Dashboard", days: int) -> float:
    """Return profit factor for the rolling *days* window."""
    import time

    cutoff = time.time() - days * 86400
    closed = [
        r
        for r in dashboard.get_closed_trades()
        if r.opened_at >= cutoff and r.outcome in ("WIN", "LOSS")
    ]
    gross_profit = sum(r.pnl_pct for r in closed if r.pnl_pct > 0)
    gross_loss = abs(sum(r.pnl_pct for r in closed if r.pnl_pct < 0))
    if gross_loss == 0:
        return 0.0
    return round(gross_profit / gross_loss, 2)


def _top_worst_pairs(dashboard: "Dashboard", days: int) -> tuple[str, str, float, float]:
    """
    Return (top_pair, worst_pair, top_pnl, worst_pnl) for the rolling *days* window.
    Returns ("N/A", "N/A", 0.0, 0.0) when no data is available.
    """
    import time

    cutoff = time.time() - days * 86400
    closed = [
        r
        for r in dashboard.get_closed_trades()
        if r.opened_at >= cutoff
    ]
    if not closed:
        return "N/A", "N/A", 0.0, 0.0

    per_sym: dict[str, float] = {}
    for r in closed:
        per_sym[r.symbol] = per_sym.get(r.symbol, 0.0) + r.pnl_pct

    sorted_syms = sorted(per_sym.items(), key=lambda x: x[1], reverse=True)
    top_sym, top_pnl = sorted_syms[0]
    worst_sym, worst_pnl = sorted_syms[-1]
    return top_sym, worst_sym, round(top_pnl, 2), round(worst_pnl, 2)


def generate_daily_briefing(
    dashboard: "Dashboard",
    risk_manager: "RiskManager",
    bot_state: "BotState",
    market_data: "MarketDataStore | None" = None,
) -> str:
    """
    Assemble and return a formatted daily briefing Telegram message.

    Parameters
    ----------
    dashboard:
        The bot's Dashboard instance for performance stats.
    risk_manager:
        The bot's RiskManager instance for active signal counts.
    bot_state:
        The bot's BotState singleton for market regime.
    market_data:
        Optional MarketDataStore (unused currently, reserved for future use).
    """
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    regime = getattr(bot_state, "market_regime", "UNKNOWN")

    fg_value, fg_label = _fetch_fear_greed()

    active = risk_manager.active_signals
    longs = sum(1 for s in active if s.result.side.value == "LONG")
    shorts = sum(1 for s in active if s.result.side.value == "SHORT")
    total_active = len(active)

    wr7, n7 = _rolling_win_rate(dashboard, 7)
    wr30, n30 = _rolling_win_rate(dashboard, 30)
    pf30 = _rolling_profit_factor(dashboard, 30)

    top, worst, top_pnl, worst_pnl = _top_worst_pairs(dashboard, 7)
    top_pnl_str = f"{top_pnl:+.2f}%" if top != "N/A" else "N/A"
    worst_pnl_str = f"{worst_pnl:+.2f}%" if worst != "N/A" else "N/A"

    return (
        f"📰 DAILY BRIEFING — {date_str}\n"
        "\n"
        f"🏛️ Market Regime: {regime}\n"
        f"😱 Fear & Greed: {fg_value} ({fg_label})\n"
        "\n"
        f"📊 Active Signals: {total_active} ({longs} LONG, {shorts} SHORT)\n"
        "\n"
        "📈 Performance:\n"
        f"- 7d Win Rate: {wr7}% ({n7} signals)\n"
        f"- 30d Win Rate: {wr30}% ({n30} signals)\n"
        f"- 30d Profit Factor: {pf30}\n"
        "\n"
        f"🏆 Top Pair (7d): {top} ({top_pnl_str})\n"
        f"💀 Worst Pair (7d): {worst} ({worst_pnl_str})\n"
        "\n"
        "⏰ Next briefing: Tomorrow 08:00 UTC"
    )
