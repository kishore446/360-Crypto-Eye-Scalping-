"""
Loss Streak Cooldown
======================
After 3+ consecutive losses, automatically:
  1. Reduce effective position size recommendation by 50% for next 3 signals
  2. Post a warning to Insights channel
  3. Increase confidence threshold (suppress LOW confidence signals entirely)
  4. Auto-reset after 3 profitable signals or 24 hours

This prevents emotional over-trading after drawdowns — a feature NO other
crypto channel offers.
"""
from __future__ import annotations

import time

try:
    from config import (
        COOLDOWN_HOURS,
        COOLDOWN_SIGNALS,
        LOSS_STREAK_THRESHOLD,
    )
except ImportError:
    LOSS_STREAK_THRESHOLD: int = 3
    COOLDOWN_SIGNALS: int = 3
    COOLDOWN_HOURS: int = 24


class CooldownManager:
    """
    Tracks consecutive losses and manages a protective cooldown period.

    Thread-safety note: this class is intentionally not thread-safe — the
    bot processes signals synchronously so no locking is needed.
    """

    def __init__(self) -> None:
        self._consecutive_losses: int = 0
        self._cooldown_active: bool = False
        self._cooldown_signals_remaining: int = 0
        self._cooldown_started_at: float = 0.0

    # ── internal helpers ──────────────────────────────────────────────────────

    def _check_time_reset(self) -> None:
        """Auto-reset cooldown if the cooldown window has expired."""
        if (
            self._cooldown_active
            and self._cooldown_started_at > 0
            and time.time() - self._cooldown_started_at >= COOLDOWN_HOURS * 3600
        ):
            self._reset_cooldown()

    def _reset_cooldown(self) -> None:
        """Deactivate cooldown and reset all counters."""
        self._cooldown_active = False
        self._cooldown_signals_remaining = 0
        self._cooldown_started_at = 0.0
        self._consecutive_losses = 0

    # ── public API ─────────────────────────────────────────────────────────────

    def record_outcome(self, outcome: str) -> bool:
        """
        Record a trade outcome.

        Parameters
        ----------
        outcome:
            ``"WIN"``, ``"LOSS"``, or ``"BE"`` (break-even).

        Returns
        -------
        bool
            ``True`` if cooldown was *just activated* by this call.
        """
        self._check_time_reset()

        if outcome == "LOSS":
            self._consecutive_losses += 1
            if (
                not self._cooldown_active
                and self._consecutive_losses >= LOSS_STREAK_THRESHOLD
            ):
                self._cooldown_active = True
                self._cooldown_signals_remaining = COOLDOWN_SIGNALS
                self._cooldown_started_at = time.time()
                return True
        else:
            # WIN or BE — count toward recovery
            if self._cooldown_active:
                self._cooldown_signals_remaining -= 1
                if self._cooldown_signals_remaining <= 0:
                    self._reset_cooldown()
            else:
                self._consecutive_losses = 0

        return False

    def is_cooldown_active(self) -> bool:
        """Return True if cooldown mode is currently active."""
        self._check_time_reset()
        return self._cooldown_active

    def get_risk_modifier(self) -> float:
        """Return position size multiplier (0.5 during cooldown, 1.0 normal)."""
        return 0.5 if self.is_cooldown_active() else 1.0

    def should_suppress_low_confidence(self) -> bool:
        """Return True if LOW confidence signals should be suppressed during cooldown."""
        return self.is_cooldown_active()
