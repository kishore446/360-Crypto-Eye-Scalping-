"""
Signal Router — routes generated signals to the correct Telegram channel(s).

Channel tiers:
  SCALPING      → CH1 — Scalping / Quick Trades (1–5 min)
  INTRADAY      → CH2 — Intraday / Swing (15–60 min)
  TREND         → CH3 — Trend / Positional (4H–1D)
  SPOT          → CH4 — spot momentum, all confidence
  INSIGHTS      → CH5 — informational posts only (not signals)
  ALTGEMS       → CH6 — altcoin gems (low-cap DCA/swing)
  WHALE_TRACKER → CH7 — whale movement + liquidation alerts
  EDUCATION     → CH8 — post-trade reviews, pattern education
  VIP_DISCUSSION→ CH9 — member analysis & discussion

Deduplication:
  If the same symbol fires on a stricter channel (SCALPING) within the
  ``dedup_window_minutes`` window, the INTRADAY and TREND channels are
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
    SCALPING = "scalping"       # CH1 — Scalping / Quick Trades (1–5 min)
    INTRADAY = "intraday"       # CH2 — Intraday / Swing (15–60 min)
    TREND = "trend"             # CH3 — Trend / Positional (4H–1D)
    SPOT = "spot"
    INSIGHTS = "insights"
    ALTGEMS = "altgems"         # CH6
    WHALE_TRACKER = "whale"     # CH7
    EDUCATION = "education"     # CH8
    VIP_DISCUSSION = "vip"      # CH9


# Tiers that can suppress lower-priority channels via dedup.
# CH1 (SCALPING) and CH2 (INTRADAY) both suppress lower tiers.
_STRICT_TIERS = (ChannelTier.SCALPING, ChannelTier.INTRADAY)
# Tiers that can be suppressed by a stricter tier, and also have a
# same-channel cooldown applied (prevents the same channel from
# broadcasting the same symbol repeatedly within the dedup window).
_SUPPRESSIBLE_TIERS = (ChannelTier.INTRADAY, ChannelTier.TREND)


class SignalRouter:
    """Routes a signal result to the correct Telegram channel ID(s)."""

    def __init__(
        self,
        channel_scalping: int,
        channel_intraday: int,
        channel_trend: int,
        channel_spot: int,
        channel_insights: int,
        channel_altgems: int = 0,
        channel_whale: int = 0,
        channel_education: int = 0,
        channel_vip: int = 0,
        dedup_window_minutes: int = _DEDUP_WINDOW_MINUTES,
    ) -> None:
        self._channels: dict[ChannelTier, int] = {
            ChannelTier.SCALPING: channel_scalping,
            ChannelTier.INTRADAY: channel_intraday,
            ChannelTier.TREND: channel_trend,
            ChannelTier.SPOT: channel_spot,
            ChannelTier.INSIGHTS: channel_insights,
            ChannelTier.ALTGEMS: channel_altgems,
            ChannelTier.WHALE_TRACKER: channel_whale,
            ChannelTier.EDUCATION: channel_education,
            ChannelTier.VIP_DISCUSSION: channel_vip,
        }
        self._dedup_window_seconds: float = dedup_window_minutes * 60.0
        # {symbol: {tier: timestamp}}
        self._recent_signals: dict[str, dict[ChannelTier, float]] = {}

    def get_channel_id(self, tier: ChannelTier) -> int:
        """Return the Telegram channel ID for *tier*."""
        return self._channels[tier]

    def get_tier_for_channel_id(self, channel_id: int) -> Optional["ChannelTier"]:
        """Reverse-lookup: return the ChannelTier for a given channel ID, or None."""
        if channel_id == 0:
            return None
        for tier, cid in self._channels.items():
            if cid == channel_id:
                return tier
        return None

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
