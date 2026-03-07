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

import dataclasses
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bot.signal_engine import Confidence, Side, SignalResult
from config import (
    BE_TRIGGER_FRACTION,
    DEFAULT_RISK_FRACTION,
    MAX_SAME_SIDE_SIGNALS,
    SIGNALS_FILE,
    STALE_SIGNAL_HOURS,
)

__all__ = [
    "ActiveSignal",
    "RiskManager",
    "calculate_position_size",
]


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
        self._lock = threading.Lock()
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Serialise ``_signals`` to JSON for restart-safe persistence."""
        data = []
        for sig in self._signals:
            d = dataclasses.asdict(sig)
            # str-Enums serialise to their string value via json.dumps; store
            # them explicitly so deserialisation is unambiguous.
            d["result"]["side"] = sig.result.side.value
            d["result"]["confidence"] = sig.result.confidence.value
            data.append(d)
        try:
            Path(SIGNALS_FILE).write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            import logging
            logging.getLogger(__name__).error(
                "Failed to persist signals to %s: %s", SIGNALS_FILE, exc
            )

    def _load(self) -> None:
        """Deserialise ``_signals`` from the JSON persistence file."""
        path = Path(SIGNALS_FILE)
        if not path.exists():
            return
        try:
            raw: list[dict] = json.loads(path.read_text(encoding="utf-8"))
            signals = []
            for d in raw:
                r = d["result"]
                result = SignalResult(
                    symbol=r["symbol"],
                    side=Side(r["side"]),
                    confidence=Confidence(r["confidence"]),
                    entry_low=r["entry_low"],
                    entry_high=r["entry_high"],
                    tp1=r["tp1"],
                    tp2=r["tp2"],
                    tp3=r["tp3"],
                    stop_loss=r["stop_loss"],
                    structure_note=r["structure_note"],
                    context_note=r["context_note"],
                    leverage_min=r["leverage_min"],
                    leverage_max=r["leverage_max"],
                )
                signals.append(
                    ActiveSignal(
                        result=result,
                        opened_at=d["opened_at"],
                        be_triggered=d["be_triggered"],
                        closed=d["closed"],
                        close_reason=d.get("close_reason"),
                    )
                )
            self._signals = signals
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not load signals from %s (%s); starting with empty list.",
                SIGNALS_FILE, exc
            )
            self._signals = []

    def save(self) -> None:
        """Public alias for ``_save`` — persist current signals to disk."""
        self._save()

    # ── public API ────────────────────────────────────────────────────────────

    def dynamic_risk_fraction(self, confidence: str, cooldown_manager: "object") -> float:
        """
        Return the dynamic risk fraction based on signal confidence and cooldown state.

        Risk table
        ----------
        Confidence  Normal Risk   Cooldown Risk (×0.5)
        HIGH        1.5% (0.015)  0.75% (0.0075)
        MEDIUM      1.0% (0.01)   0.50% (0.005)
        LOW         0.5% (0.005)  SUPPRESSED (0.0)

        Parameters
        ----------
        confidence:
            Confidence level string — "High", "MEDIUM", "LOW" (case-insensitive).
        cooldown_manager:
            A ``CooldownManager`` instance exposing ``is_cooldown_active()``.

        Returns
        -------
        float
            Risk fraction (0.0 means the signal is suppressed).
        """
        in_cooldown = cooldown_manager.is_cooldown_active() if cooldown_manager is not None else False
        conf_upper = confidence.upper()
        if conf_upper == "HIGH":
            return 0.0075 if in_cooldown else 0.015
        if conf_upper == "MEDIUM":
            return 0.005 if in_cooldown else 0.01
        # LOW confidence
        if in_cooldown:
            return 0.0  # suppressed
        return 0.005

    def can_open_signal(self, side: Side) -> bool:
        """
        Return True only when the "3-Pair" cap allows a new signal on *side*.
        """
        with self._lock:
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
        with self._lock:
            self._signals.append(active)
            self._save()
        return active

    def update_prices(self, prices: dict[str, float]) -> list[str]:
        """
        Feed the latest prices into the risk manager.

        Returns a list of human-readable broadcast messages for any events
        that were triggered (BE, stale-close, etc.).
        """
        messages: list[str] = []
        now = time.time()
        mutated = False

        with self._lock:
            signals_snapshot = list(self._signals)

        for signal in signals_snapshot:
            if signal.closed:
                continue
            sym = signal.result.symbol
            price = prices.get(sym)

            # ── stale check ──────────────────────────────────────────────────
            if signal.is_stale(now):
                signal.close("stale")
                mutated = True
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
                mutated = True
                messages.append(
                    f"🔒 #{sym}/USDT {signal.result.side.value}: "
                    f"Move SL to Entry {signal.entry_mid:.4f} (Risk-Free Mode ON)."
                )

        if mutated:
            with self._lock:
                self._save()

        return messages

    def close_signal(self, symbol: str, reason: str = "manual") -> bool:
        """Close the first open signal matching *symbol*. Returns True on success."""
        with self._lock:
            for signal in self._signals:
                if not signal.closed and signal.result.symbol == symbol:
                    signal.close(reason)
                    self._save()
                    return True
        return False

    @property
    def active_signals(self) -> list[ActiveSignal]:
        """Return all signals that have not yet been closed."""
        with self._lock:
            return [s for s in self._signals if not s.closed]

    @property
    def all_signals(self) -> list[ActiveSignal]:
        with self._lock:
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
