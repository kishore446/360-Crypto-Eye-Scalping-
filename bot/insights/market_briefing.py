"""
Daily Market Briefing
=====================
Generates an automated daily briefing message posted to CH5 (Insights channel)
every day at 08:00 UTC.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.dashboard import Dashboard
    from bot.risk_manager import RiskManager
    from bot.state import BotState

logger = logging.getLogger(__name__)

__all__ = ["generate_daily_briefing"]


def _fetch_fear_greed() -> str:
    """Fetch Fear & Greed Index from alternative.me API. Returns 'N/A' on failure."""
    try:
        import json
        import urllib.request

        try:
            from config import BTC_FEAR_GREED_URL
        except Exception:
            BTC_FEAR_GREED_URL = "https://api.alternative.me/fng/"

        req = urllib.request.Request(BTC_FEAR_GREED_URL, headers={"User-Agent": "360CryptoEye/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        entry = data["data"][0]
        value = entry["value"]
        classification = entry["value_classification"]
        return f"{value} ({classification})"
    except Exception as exc:
        logger.debug("Fear & Greed fetch failed: %s", exc)
        return "N/A"


def generate_daily_briefing(
    dashboard: "Dashboard",
    risk_manager: "RiskManager",
    bot_state: "BotState",
    market_data: Optional[object] = None,
) -> str:
    """
    Assemble a daily briefing message for the Insights channel.

    Parameters
    ----------
    dashboard:
        Dashboard instance for win-rate and performance stats.
    risk_manager:
        RiskManager instance for active signal counts.
    bot_state:
        BotState singleton for market regime.
    market_data:
        MarketDataStore (optional, reserved for future funding rate summary).

    Returns
    -------
    str
        Formatted Telegram message.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    regime = bot_state.market_regime

    fear_greed = _fetch_fear_greed()

    active_signals = risk_manager.active_signals
    total_active = len(active_signals)
    longs = sum(1 for s in active_signals if s.result.side.value == "LONG")
    shorts = total_active - longs

    # Win rates
    wr_7d = _rolling_win_rate(dashboard, days=7)
    wr_30d = _rolling_win_rate(dashboard, days=30)
    count_7d = _rolling_trade_count(dashboard, days=7)
    count_30d = _rolling_trade_count(dashboard, days=30)
    pf_30d = _rolling_profit_factor(dashboard, days=30)

    # Top / worst pairs (7 days)
    top_pair, top_pnl, worst_pair, worst_pnl = _top_worst_pairs(dashboard, days=7)

    lines = [
        f"📰 DAILY BRIEFING — {today}",
        "",
        f"🏛️ Market Regime: {regime}",
        f"😱 Fear & Greed: {fear_greed}",
        "",
        f"📊 Active Signals: {total_active} ({longs} LONG, {shorts} SHORT)",
        "",
        "📈 Performance:",
        f"- 7d Win Rate: {wr_7d:.1f}% ({count_7d} signals)",
        f"- 30d Win Rate: {wr_30d:.1f}% ({count_30d} signals)",
        f"- 30d Profit Factor: {pf_30d:.2f}",
    ]

    if top_pair:
        sign = "+" if top_pnl >= 0 else ""
        lines.append(f"\n🏆 Top Pair (7d): {top_pair} ({sign}{top_pnl:.1f}%)")
    if worst_pair:
        sign = "+" if worst_pnl >= 0 else ""
        lines.append(f"💀 Worst Pair (7d): {worst_pair} ({sign}{worst_pnl:.1f}%)")

    lines.append("\n⏰ Next briefing: Tomorrow 08:00 UTC")

    return "\n".join(lines)


def _rolling_win_rate(dashboard: "Dashboard", days: int) -> float:
    """Compute win rate % for closed trades within the last *days* days."""
    import time
    cutoff = time.time() - days * 86400
    trades = [
        t for t in dashboard.get_closed_trades()
        if t.closed_at is not None and t.closed_at >= cutoff
        and t.outcome in ("WIN", "LOSS")
    ]
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.outcome == "WIN")
    return wins / len(trades) * 100.0


def _rolling_trade_count(dashboard: "Dashboard", days: int) -> int:
    """Count closed (WIN/LOSS) trades within the last *days* days."""
    import time
    cutoff = time.time() - days * 86400
    return sum(
        1 for t in dashboard.get_closed_trades()
        if t.closed_at is not None and t.closed_at >= cutoff
        and t.outcome in ("WIN", "LOSS")
    )


def _rolling_profit_factor(dashboard: "Dashboard", days: int) -> float:
    """Compute profit factor for closed trades within the last *days* days."""
    import time
    cutoff = time.time() - days * 86400
    trades = [
        t for t in dashboard.get_closed_trades()
        if t.closed_at is not None and t.closed_at >= cutoff
        and t.outcome in ("WIN", "LOSS")
    ]
    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = sum(abs(t.pnl_pct) for t in trades if t.pnl_pct < 0)
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 2)


def _top_worst_pairs(
    dashboard: "Dashboard", days: int
) -> tuple[str, float, str, float]:
    """
    Find the top and worst performing pairs in the last *days* days.

    Returns (top_symbol, top_avg_pnl, worst_symbol, worst_avg_pnl).
    Returns ('', 0.0, '', 0.0) when there is no data.
    """
    import time
    cutoff = time.time() - days * 86400
    trades = [
        t for t in dashboard.get_closed_trades()
        if t.closed_at is not None and t.closed_at >= cutoff
        and t.outcome in ("WIN", "LOSS")
    ]
    if not trades:
        return "", 0.0, "", 0.0

    symbol_pnl: dict[str, list[float]] = {}
    for t in trades:
        symbol_pnl.setdefault(t.symbol, []).append(t.pnl_pct)

    avg_pnl = {sym: sum(vals) / len(vals) for sym, vals in symbol_pnl.items()}
    sorted_syms = sorted(avg_pnl, key=avg_pnl.__getitem__, reverse=True)

    top_sym = sorted_syms[0]
    worst_sym = sorted_syms[-1]
    return top_sym, round(avg_pnl[top_sym], 1), worst_sym, round(avg_pnl[worst_sym], 1)
