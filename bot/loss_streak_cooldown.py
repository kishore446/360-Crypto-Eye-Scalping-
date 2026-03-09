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

import threading
import time

try:
    from config import (
        COOLDOWN_HOURS,
        COOLDOWN_SIGNALS,
        HOT_STREAK_BONUS_CONFLUENCE,
        HOT_STREAK_THRESHOLD,
        LOSS_STREAK_THRESHOLD,
    )
except ImportError:
    LOSS_STREAK_THRESHOLD: int = 3
    COOLDOWN_SIGNALS: int = 3
    COOLDOWN_HOURS: int = 24
    HOT_STREAK_THRESHOLD: int = 5
    HOT_STREAK_BONUS_CONFLUENCE: int = 5


class CooldownManager:
    """
    Tracks consecutive losses and manages a protective cooldown period.

    Thread-safe: all public methods and internal helpers are protected by a
    ``threading.RLock`` to support concurrent access from asyncio tasks,
    background scheduler threads, and Telegram command handlers.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_losses: int = 0
        self._consecutive_wins: int = 0
        self._cooldown_active: bool = False
        self._cooldown_signals_remaining: int = 0
        self._cooldown_started_at: float = 0.0
        self._hot_streak_active: bool = False

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

    def _check_hot_streak(self) -> None:
        """After HOT_STREAK_THRESHOLD consecutive wins, enable hot streak mode."""
        if self._consecutive_wins >= HOT_STREAK_THRESHOLD and not self._hot_streak_active:
            self._hot_streak_active = True

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
        with self._lock:
            self._check_time_reset()

            if outcome == "LOSS":
                self._consecutive_losses += 1
                self._consecutive_wins = 0
                self._hot_streak_active = False   # reset hot streak on first loss
                if (
                    not self._cooldown_active
                    and self._consecutive_losses >= LOSS_STREAK_THRESHOLD
                ):
                    self._cooldown_active = True
                    self._cooldown_signals_remaining = COOLDOWN_SIGNALS
                    self._cooldown_started_at = time.time()
                    return True
            else:
                # WIN or BE — count toward recovery and hot streak
                if self._cooldown_active:
                    self._cooldown_signals_remaining -= 1
                    if self._cooldown_signals_remaining <= 0:
                        self._reset_cooldown()
                else:
                    self._consecutive_losses = 0

                if outcome == "WIN":
                    self._consecutive_wins += 1
                    self._check_hot_streak()
                else:
                    # BE does not break hot streak but also does not advance it
                    pass

            return False

    def is_hot_streak_active(self) -> bool:
        """Return True if hot streak mode is currently active."""
        with self._lock:
            return self._hot_streak_active

    def get_hot_streak_bonus(self) -> int:
        """Return extra confluence score bonus during hot streak."""
        with self._lock:
            return HOT_STREAK_BONUS_CONFLUENCE if self._hot_streak_active else 0

    def is_cooldown_active(self) -> bool:
        """Return True if cooldown mode is currently active."""
        with self._lock:
            self._check_time_reset()
            return self._cooldown_active

    def get_risk_modifier(self) -> float:
        """Return position size multiplier (0.5 during cooldown, 1.0 normal)."""
        with self._lock:
            self._check_time_reset()
            return 0.5 if self._cooldown_active else 1.0

    def should_suppress_low_confidence(self) -> bool:
        """Return True if LOW confidence signals should be suppressed during cooldown."""
        with self._lock:
            self._check_time_reset()
            return self._cooldown_active
