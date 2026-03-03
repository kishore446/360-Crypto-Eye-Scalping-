"""
Dashboard
=========
Live transparency log (Section VI of the master blueprint).

Tracks every closed signal result and exposes real-time statistics:
  • Win-rate % (by timeframe bucket: 5m, 15m, 1h)
  • Profit Factor = Gross Profit / Gross Loss
  • Current PnL — live floating profit/loss of all open 360 Eye signals

Results are persisted to a JSON file so they survive process restarts.
"""

from __future__ import annotations

import json
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

    def summary(self) -> str:
        """Return a formatted Telegram-ready dashboard summary."""
        lines = [
            "📊 360 EYE SCALP — LIVE DASHBOARD",
            "─────────────────────────────────",
            f"Total Closed Trades : {self.total_trades()}",
            f"Win Rate (All)       : {self.win_rate():.2f}%",
            f"  → 5m entries       : {self.win_rate('5m'):.2f}%",
            f"  → 15m entries      : {self.win_rate('15m'):.2f}%",
            f"  → 1h entries       : {self.win_rate('1h'):.2f}%",
            f"Profit Factor        : {self.profit_factor():.2f}",
            f"Open PnL (floating)  : {self.current_open_pnl():+.2f}%",
        ]
        return "\n".join(lines)
