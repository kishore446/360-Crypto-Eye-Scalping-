"""
Partial Position Tracker
========================
Tracks multi-level partial exits for a single signal position.

The standard signal format closes 50% at TP1, 25% at TP2, and 25% at TP3.
This module records each partial fill and computes the weighted composite PnL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

__all__ = ["PartialPosition"]

# Default partial close percentages per TP level
_TP1_PCT = 0.50
_TP2_PCT = 0.25
_TP3_PCT = 0.25


@dataclass
class _PartialExit:
    """A single partial exit record."""
    level: str          # "TP1" | "TP2" | "TP3" | "SL" | "BE" | "TRAIL"
    exit_price: float
    entry_price: float
    pct: float          # fraction of original position closed (0.0–1.0)
    pnl_pct: float      # % PnL for this exit relative to entry


@dataclass
class PartialPosition:
    """
    Tracks partial closes for a single signal.

    Usage
    -----
    >>> pp = PartialPosition(entry_price=97000.0, signal_id="sig-001", side="LONG")
    >>> pp.add_exit("TP1", exit_price=98455.0)
    >>> pp.add_exit("TRAIL", exit_price=99100.0)
    >>> print(pp.composite_pnl())
    """

    signal_id: str
    entry_price: float
    side: str = "LONG"              # "LONG" or "SHORT" — used for PnL sign
    tp1_closed_pct: float = _TP1_PCT
    tp2_closed_pct: float = _TP2_PCT
    tp3_closed_pct: float = _TP3_PCT
    _exits: list[_PartialExit] = field(default_factory=list, repr=False)

    # Track which TP levels have been closed to determine the correct pct
    _tp1_done: bool = field(default=False, repr=False)
    _tp2_done: bool = field(default=False, repr=False)

    def add_exit(self, level: str, exit_price: float, entry_price: float | None = None) -> None:
        """
        Record a partial exit.

        Parameters
        ----------
        level:
            One of ``"TP1"``, ``"TP2"``, ``"TP3"``, ``"SL"``, ``"BE"``, ``"TRAIL"``,
            ``"STALE"``.
        exit_price:
            Price at which this portion was exited.
        entry_price:
            Original entry price for PnL calculation. Falls back to ``self.entry_price``
            when not provided.
        """
        ep = entry_price if entry_price is not None else self.entry_price
        pct = self._pct_for_level(level)
        if ep > 0:
            if self.side.upper() == "SHORT":
                pnl_pct = (ep - exit_price) / ep * 100
            else:
                pnl_pct = (exit_price - ep) / ep * 100
        else:
            pnl_pct = 0.0

        self._exits.append(_PartialExit(
            level=level,
            exit_price=exit_price,
            entry_price=ep,
            pct=pct,
            pnl_pct=round(pnl_pct, 4),
        ))

        if level == "TP1":
            self._tp1_done = True
        elif level == "TP2":
            self._tp2_done = True

    def _pct_for_level(self, level: str) -> float:
        """Return the position fraction to close at *level*."""
        if level == "TP1":
            return self.tp1_closed_pct
        if level == "TP2":
            return self.tp2_closed_pct
        if level in ("TP3", "SL", "BE", "TRAIL", "STALE"):
            return self.remaining_pct()
        return self.remaining_pct()

    def remaining_pct(self) -> float:
        """Return the fraction of the original position still open."""
        closed = sum(e.pct for e in self._exits)
        return max(round(1.0 - closed, 6), 0.0)

    def composite_pnl(self) -> float:
        """
        Compute the weighted-average composite PnL across all partial exits.

        Returns 0.0 when no exits have been recorded.
        """
        if not self._exits:
            return 0.0
        total_weight = sum(e.pct for e in self._exits)
        if total_weight <= 0:
            return 0.0
        weighted_sum = sum(e.pnl_pct * e.pct for e in self._exits)
        return round(weighted_sum / total_weight, 4)

    def to_json(self) -> str:
        """Serialize exits to a JSON string for storage in TradeResult.partial_exits."""
        return json.dumps([
            {
                "level": e.level,
                "pct": round(e.pct * 100, 1),
                "pnl": e.pnl_pct,
                "exit_price": e.exit_price,
            }
            for e in self._exits
        ])

    def has_exits(self) -> bool:
        """Return True if at least one partial exit has been recorded."""
        return len(self._exits) > 0

    def exit_count(self) -> int:
        """Return the number of partial exits recorded."""
        return len(self._exits)

    def format_exit_breakdown(self, side: str = "LONG") -> str:
        """
        Format a multi-line breakdown of all exits for use in close messages.

        Parameters
        ----------
        side:
            ``"LONG"`` or ``"SHORT"`` — used to label direction in the output.
        """
        lines = []
        for i, e in enumerate(self._exits, 1):
            sign = "+" if e.pnl_pct >= 0 else ""
            lines.append(
                f"Exit {i}: {e.level} @ {e.exit_price:,.4f} ({e.pct * 100:.0f}%) "
                f"→ {sign}{e.pnl_pct:.2f}%"
            )
        return "\n".join(lines)
