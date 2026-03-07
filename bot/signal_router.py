"""
Signal Router — routes generated signals to the correct Telegram channel(s).

Channel tiers:
  HARD     → CH1 — full confluence, HIGH confidence only
  MEDIUM   → CH2 — relaxed gates, HIGH+MEDIUM confidence
  EASY     → CH3 — breakout only, all confidence
  SPOT     → CH4 — spot momentum, all confidence
  INSIGHTS → CH5 — informational posts only (not signals)

Deduplication:
  If the same symbol fires on a stricter channel (HARD) within the
  ``dedup_window_minutes`` window, the MEDIUM and EASY channels are
  suppressed to avoid duplicate alerts for the same setup.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional

try:
    from config import DEDUP_WINDOW_MINUTES as _DEDUP_WINDOW_MINUTES
except Exception:  # pragma: no cover
    _DEDUP_WINDOW_MINUTES = 15


class ChannelTier(str, Enum):
    HARD = "hard"
    MEDIUM = "medium"
    EASY = "easy"
    SPOT = "spot"
    INSIGHTS = "insights"


# Tiers that can suppress lower-priority channels via dedup.
# CH1 (HARD) and CH2 (MEDIUM) both suppress lower tiers.
_STRICT_TIERS = (ChannelTier.HARD, ChannelTier.MEDIUM)
# Tiers that can be suppressed by a stricter tier, and also have a
# same-channel cooldown applied (prevents the same channel from
# broadcasting the same symbol repeatedly within the dedup window).
_SUPPRESSIBLE_TIERS = (ChannelTier.MEDIUM, ChannelTier.EASY)


class SignalRouter:
    """Routes a signal result to the correct Telegram channel ID(s)."""

    def __init__(
        self,
        channel_hard: int,
        channel_medium: int,
        channel_easy: int,
        channel_spot: int,
        channel_insights: int,
        dedup_window_minutes: int = _DEDUP_WINDOW_MINUTES,
    ) -> None:
        self._channels: dict[ChannelTier, int] = {
            ChannelTier.HARD: channel_hard,
            ChannelTier.MEDIUM: channel_medium,
            ChannelTier.EASY: channel_easy,
            ChannelTier.SPOT: channel_spot,
            ChannelTier.INSIGHTS: channel_insights,
        }
        self._dedup_window_seconds: float = dedup_window_minutes * 60.0
        # {symbol: {tier: timestamp}}
        self._recent_signals: dict[str, dict[ChannelTier, float]] = {}

    def get_channel_id(self, tier: ChannelTier) -> int:
        """Return the Telegram channel ID for *tier*."""
        return self._channels[tier]

    def is_channel_enabled(self, tier: ChannelTier) -> bool:
        """Return True if the channel ID for *tier* is non-zero (configured)."""
        return self._channels[tier] != 0

    def should_suppress_duplicate(self, symbol: str, tier: ChannelTier) -> bool:
        """
        Return True if *symbol* should be suppressed for *tier*.

        Suppression applies when *tier* is a suppressible tier and either:
          1. The **same** channel already broadcast this symbol within the
             dedup window (same-channel cooldown — prevents repeated fires).
          2. A **stricter** channel already broadcast this symbol within the
             dedup window (cross-tier suppression).

        CH4 (SPOT) and CH5 (INSIGHTS) are never suppressed.
        """
        if tier not in _SUPPRESSIBLE_TIERS:
            return False

        now = time.monotonic()
        symbol_signals = self._recent_signals.get(symbol, {})

        # Same-channel cooldown — don't re-fire on the same channel within the window
        own_sent_at = symbol_signals.get(tier)
        if own_sent_at is not None and (now - own_sent_at) < self._dedup_window_seconds:
            return True

        # Cross-tier suppression — suppress if a stricter tier fired recently
        for strict_tier in _STRICT_TIERS:
            sent_at = symbol_signals.get(strict_tier)
            if sent_at is not None and (now - sent_at) < self._dedup_window_seconds:
                return True
        return False

    def record_signal(self, symbol: str, tier: ChannelTier) -> None:
        """Record that a signal was sent for deduplication tracking."""
        if symbol not in self._recent_signals:
            self._recent_signals[symbol] = {}
        self._recent_signals[symbol][tier] = time.monotonic()
        self._prune_expired()

    def _prune_expired(self) -> None:
        """Remove expired deduplication records to prevent unbounded growth."""
        now = time.monotonic()
        cutoff = now - self._dedup_window_seconds
        to_delete: list[str] = []
        for symbol, tier_map in self._recent_signals.items():
            expired = [t for t, ts in tier_map.items() if ts < cutoff]
            for t in expired:
                del tier_map[t]
            if not tier_map:
                to_delete.append(symbol)
        for symbol in to_delete:
            del self._recent_signals[symbol]
