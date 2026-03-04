"""
Dashboard
=========
Live transparency log (Section VI of the master blueprint).

Tracks every closed signal result and exposes real-time statistics:
  • Win-rate % (by timeframe bucket: 5m, 15m, 1h)
  • Profit Factor = Gross Profit / Gross Loss
  • Current PnL — live floating profit/loss of all open 360 Eye signals
  • Sharpe Ratio, Max Drawdown, Equity Curve, Per-Symbol Performance

Results are persisted to a JSON file so they survive process restarts.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from config import DASHBOARD_LOG_FILE


@dataclass
class TradeResult:
    """One completed or open trade recorded in the transparency log."""

    symbol: str
    side: str           # "LONG" | "SHORT"
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: float    # Unix timestamp
    closed_at: Optional[float]
    outcome: str        # "WIN" | "LOSS" | "BE" | "OPEN"
    pnl_pct: float      # % PnL relative to entry
    timeframe: str      # "5m" | "15m" | "1h" — identifies which TF triggered entry

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TradeResult":
        return cls(**d)


class Dashboard:
    """
    In-memory + file-persisted transparency dashboard.

    Usage example
    -------------
    >>> db = Dashboard()
    >>> db.record_result(TradeResult(..., outcome="WIN", pnl_pct=1.5, ...))
    >>> print(db.summary())
    """

    def __init__(self, log_file: str = DASHBOARD_LOG_FILE) -> None:
        self._log_file = Path(log_file)
        self._results: list[TradeResult] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._log_file.exists():
            try:
                raw = json.loads(self._log_file.read_text(encoding="utf-8"))
                self._results = [TradeResult.from_dict(r) for r in raw]
            except (json.JSONDecodeError, KeyError, TypeError):
                self._results = []

    def _save(self) -> None:
        self._log_file.write_text(
            json.dumps([r.to_dict() for r in self._results], indent=2),
            encoding="utf-8",
        )

    # ── recording ─────────────────────────────────────────────────────────────

    def record_result(self, result: TradeResult) -> None:
        """Append *result* to the log and persist immediately."""
        self._results.append(result)
        self._save()

    def update_open_pnl(self, symbol: str, current_price: float) -> None:
        """Refresh the floating PnL for an OPEN trade."""
        for r in self._results:
            if r.symbol == symbol and r.outcome == "OPEN":
                direction = 1 if r.side == "LONG" else -1
                r.pnl_pct = direction * (current_price - r.entry_price) / r.entry_price * 100
        self._save()

    # ── statistics ────────────────────────────────────────────────────────────

    def win_rate(self, timeframe: Optional[str] = None) -> float:
        """
        Return the win-rate as a percentage for closed trades.

        Parameters
        ----------
        timeframe:
            Filter by timeframe bucket ("5m", "15m", "1h").
            When None all closed trades are included.
        """
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE")
            and (timeframe is None or r.timeframe == timeframe)
        ]
        if not closed:
            return 0.0
        wins = sum(1 for r in closed if r.outcome == "WIN")
        return round(wins / len(closed) * 100, 2)

    def profit_factor(self) -> float:
        """
        Return the Profit Factor = Gross Profit / Gross Loss.
        Returns 0.0 (undefined) when there are no closed losing trades to divide by.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS")]
        gross_profit = sum(r.pnl_pct for r in closed if r.pnl_pct > 0)
        gross_loss = abs(sum(r.pnl_pct for r in closed if r.pnl_pct < 0))
        if gross_loss == 0:
            return 0.0
        return round(gross_profit / gross_loss, 4)

    def current_open_pnl(self) -> float:
        """Return the aggregate floating PnL % across all OPEN signals."""
        return round(sum(r.pnl_pct for r in self._results if r.outcome == "OPEN"), 4)

    def total_trades(self) -> int:
        return len([r for r in self._results if r.outcome != "OPEN"])

    def sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """
        Return the Sharpe Ratio = (mean_return - risk_free) / std_return.
        Returns 0.0 when there are fewer than 2 closed trades or std is 0.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        if len(closed) < 2:
            return 0.0
        returns = [r.pnl_pct for r in closed]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance)
        if std_r == 0:
            return 0.0
        return round((mean_r - risk_free_rate) / std_r, 4)

    def max_drawdown(self) -> float:
        """
        Return the maximum peak-to-trough drawdown as a positive percentage.
        Returns 0.0 when there are no closed trades.
        """
        curve = self.equity_curve()
        if not curve:
            return 0.0
        peak = curve[0]
        max_dd = 0.0
        for val in curve:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 4)

    def average_holding_time(self) -> float:
        """
        Return the average holding time in hours for closed trades.
        Returns 0.0 when no trades have both opened_at and closed_at.
        """
        durations = [
            (r.closed_at - r.opened_at) / 3600
            for r in self._results
            if r.outcome not in ("OPEN",) and r.closed_at is not None
        ]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 4)

    def win_streak(self) -> int:
        """Return the current consecutive win streak (from most recent trade)."""
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        streak = 0
        for r in reversed(closed):
            if r.outcome == "WIN":
                streak += 1
            else:
                break
        return streak

    def loss_streak(self) -> int:
        """Return the current consecutive loss streak (from most recent trade)."""
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        streak = 0
        for r in reversed(closed):
            if r.outcome == "LOSS":
                streak += 1
            else:
                break
        return streak

    def equity_curve(self) -> list[float]:
        """
        Return a list of cumulative PnL values for all closed trades in order.
        Starting value is 0.0.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        curve: list[float] = []
        cumulative = 0.0
        for r in closed:
            cumulative += r.pnl_pct
            curve.append(round(cumulative, 4))
        return curve

    def per_symbol_performance(self) -> dict[str, dict]:
        """
        Return per-symbol performance stats.

        Returns a dict mapping symbol → {total, wins, losses, win_rate, total_pnl}.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        perf: dict[str, dict] = {}
        for r in closed:
            sym = r.symbol
            if sym not in perf:
                perf[sym] = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0}
            perf[sym]["total"] += 1
            if r.outcome == "WIN":
                perf[sym]["wins"] += 1
            elif r.outcome == "LOSS":
                perf[sym]["losses"] += 1
            perf[sym]["total_pnl"] = round(perf[sym]["total_pnl"] + r.pnl_pct, 4)
        for sym, stats in perf.items():
            if stats["total"] > 0:
                stats["win_rate"] = round(stats["wins"] / stats["total"] * 100, 2)
        return perf

    def summary(self) -> str:
        """Return a formatted Telegram-ready dashboard summary."""
        sharpe = self.sharpe_ratio()
        drawdown = self.max_drawdown()
        hold_time = self.average_holding_time()
        w_streak = self.win_streak()
        l_streak = self.loss_streak()
        lines = [
            "📊 360 EYE SCALP — LIVE DASHBOARD",
            "─────────────────────────────────",
            f"Total Closed Trades : {self.total_trades()}",
            f"Win Rate (All)       : {self.win_rate():.2f}%",
            f"  → 5m entries       : {self.win_rate('5m'):.2f}%",
            f"  → 15m entries      : {self.win_rate('15m'):.2f}%",
            f"  → 1h entries       : {self.win_rate('1h'):.2f}%",
            f"Profit Factor        : {self.profit_factor():.2f}",
            f"Sharpe Ratio         : {sharpe:.4f}",
            f"Max Drawdown         : {drawdown:.2f}%",
            f"Avg Holding Time     : {hold_time:.2f}h",
            f"Win Streak           : {w_streak}",
            f"Loss Streak          : {l_streak}",
            f"Open PnL (floating)  : {self.current_open_pnl():+.2f}%",
        ]
        return "\n".join(lines)
