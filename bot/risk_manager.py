"""
Risk Manager
============
Implements all safety protocols from Section V of the master blueprint:

  1. Break-Even (BE) Trigger — move SL to entry when price hits 50 % of TP1.
  2. The "3-Pair" Cap — max 3 active signals on the same side.
  3. Stale Close — alert/close if entry zone is untouched for > 4 hours.
  4. Position-size calculator (/risk_calc command).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from bot.signal_engine import Side, SignalResult
from config import (
    BE_TRIGGER_FRACTION,
    DEFAULT_RISK_FRACTION,
    MAX_SAME_SIDE_SIGNALS,
    STALE_SIGNAL_HOURS,
)


@dataclass
class ActiveSignal:
    """Tracks a live signal from entry through to close."""

    result: SignalResult
    opened_at: float = field(default_factory=time.time)  # Unix timestamp
    be_triggered: bool = False
    closed: bool = False
    close_reason: Optional[str] = None

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def entry_mid(self) -> float:
        return (self.result.entry_low + self.result.entry_high) / 2

    def is_stale(self, now: Optional[float] = None) -> bool:
        """Return True if the signal has been open longer than the stale threshold."""
        elapsed_hours = ((now or time.time()) - self.opened_at) / 3600
        return elapsed_hours >= STALE_SIGNAL_HOURS

    def should_trigger_be(self, current_price: float) -> bool:
        """Return True when current price has reached the BE trigger level."""
        if self.be_triggered or self.closed:
            return False
        distance_to_tp1 = abs(self.result.tp1 - self.entry_mid)
        trigger_price = (
            self.entry_mid + BE_TRIGGER_FRACTION * distance_to_tp1
            if self.result.side == Side.LONG
            else self.entry_mid - BE_TRIGGER_FRACTION * distance_to_tp1
        )
        if self.result.side == Side.LONG:
            return current_price >= trigger_price
        return current_price <= trigger_price

    def trigger_be(self) -> None:
        """Mark the break-even as triggered; SL is now at entry."""
        self.be_triggered = True

    def close(self, reason: str) -> None:
        self.closed = True
        self.close_reason = reason


class RiskManager:
    """
    Central registry of active signals with built-in safety enforcement.
    """

    def __init__(self) -> None:
        self._signals: list[ActiveSignal] = []

    # ── public API ────────────────────────────────────────────────────────────

    def can_open_signal(self, side: Side) -> bool:
        """
        Return True only when the "3-Pair" cap allows a new signal on *side*.
        """
        count = sum(
            1
            for s in self._signals
            if not s.closed and s.result.side == side
        )
        return count < MAX_SAME_SIDE_SIGNALS

    def add_signal(self, result: SignalResult) -> ActiveSignal:
        """
        Register a new active signal.

        Raises
        ------
        RuntimeError
            If the 3-Pair Cap would be violated.
        """
        if not self.can_open_signal(result.side):
            raise RuntimeError(
                f"3-Pair Cap reached: already {MAX_SAME_SIDE_SIGNALS} active "
                f"{result.side.value} signals."
            )
        active = ActiveSignal(result=result)
        self._signals.append(active)
        return active

    def update_prices(self, prices: dict[str, float]) -> list[str]:
        """
        Feed the latest prices into the risk manager.

        Returns a list of human-readable broadcast messages for any events
        that were triggered (BE, stale-close, etc.).
        """
        messages: list[str] = []
        now = time.time()

        for signal in self._signals:
            if signal.closed:
                continue
            sym = signal.result.symbol
            price = prices.get(sym)

            # ── stale check ──────────────────────────────────────────────────
            if signal.is_stale(now):
                signal.close("stale")
                messages.append(
                    f"⚠️ #{sym}/USDT {signal.result.side.value} signal CLOSED "
                    f"(stale — no activity for >{STALE_SIGNAL_HOURS}h)."
                )
                continue

            if price is None:
                continue

            # ── BE trigger ───────────────────────────────────────────────────
            if signal.should_trigger_be(price):
                signal.trigger_be()
                messages.append(
                    f"🔒 #{sym}/USDT {signal.result.side.value}: "
                    f"Move SL to Entry {signal.entry_mid:.4f} (Risk-Free Mode ON)."
                )

        return messages

    def close_signal(self, symbol: str, reason: str = "manual") -> bool:
        """Close the first open signal matching *symbol*. Returns True on success."""
        for signal in self._signals:
            if not signal.closed and signal.result.symbol == symbol:
                signal.close(reason)
                return True
        return False

    @property
    def active_signals(self) -> list[ActiveSignal]:
        """Return all signals that have not yet been closed."""
        return [s for s in self._signals if not s.closed]

    @property
    def all_signals(self) -> list[ActiveSignal]:
        return list(self._signals)


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    risk_fraction: float = DEFAULT_RISK_FRACTION,
) -> dict[str, float]:
    """
    Calculate the exact position size for a given trade setup.

    Parameters
    ----------
    account_balance:
        Total account balance in USDT.
    entry_price:
        Planned entry price.
    stop_loss_price:
        Structural stop-loss price.
    risk_fraction:
        Fraction of account to risk (default 1 %).

    Returns
    -------
    Dictionary with keys: risk_amount, sl_distance_pct, position_size_usdt,
    position_size_units.
    """
    if entry_price <= 0 or stop_loss_price <= 0:
        raise ValueError("Prices must be positive.")
    if entry_price == stop_loss_price:
        raise ValueError("Entry price and stop-loss price must differ.")

    risk_amount = account_balance * risk_fraction
    sl_distance = abs(entry_price - stop_loss_price)
    sl_distance_pct = sl_distance / entry_price

    # Position size in USDT (margin) such that the SL hit = risk_amount
    position_size_usdt = risk_amount / sl_distance_pct
    position_size_units = position_size_usdt / entry_price

    return {
        "risk_amount": round(risk_amount, 4),
        "sl_distance_pct": round(sl_distance_pct * 100, 4),
        "position_size_usdt": round(position_size_usdt, 4),
        "position_size_units": round(position_size_units, 6),
    }
