"""
Channel Degradation Manager
============================
Monitors per-channel rolling win rate and automatically adjusts signal quality
thresholds when a channel underperforms.

Rules:
  - If 7-day rolling WR drops below 35%: raise min_confluence_score by +15
  - If 7-day rolling WR drops below 25%: suppress channel entirely
  - Auto-restore when WR recovers above 50%
  - Alert messages are returned for the caller to post to the Insights channel
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["ChannelDegradationManager"]

try:
    from config import (
        CHANNEL_DEGRADATION_EXTRA_CONFLUENCE,
        CHANNEL_DEGRADATION_LOW_WR,
        CHANNEL_DEGRADATION_RECOVERY_WR,
        CHANNEL_DEGRADATION_SUPPRESS_WR,
    )
except ImportError:
    CHANNEL_DEGRADATION_LOW_WR = 35.0          # Raise confluence threshold below this WR
    CHANNEL_DEGRADATION_SUPPRESS_WR = 25.0     # Suppress channel entirely below this WR
    CHANNEL_DEGRADATION_RECOVERY_WR = 50.0     # Auto-restore when WR recovers above this
    CHANNEL_DEGRADATION_EXTRA_CONFLUENCE = 15  # Extra confluence points required when degraded


class ChannelDegradationManager:
    """
    Monitors per-channel rolling win rate and automatically adjusts
    signal quality thresholds when a channel underperforms.

    Parameters
    ----------
    dashboard:
        ``Dashboard`` instance used to query rolling per-channel stats.
    rolling_days:
        Rolling lookback window in days (default 7).
    """

    def __init__(self, dashboard: "object", rolling_days: int = 7) -> None:
        self._dashboard = dashboard
        self._rolling_days = rolling_days
        self._degraded_channels: dict[str, int] = {}   # tier -> extra confluence required
        self._suppressed_channels: set[str] = set()    # fully suppressed channels

    def check_and_update(self) -> list[str]:
        """
        Check all channels and return a list of alert messages for any
        channels that transitioned to/from degraded or suppressed state.
        """
        alerts: list[str] = []

        try:
            rolling = self._dashboard.per_channel_rolling_stats(days=self._rolling_days)
        except Exception as exc:
            logger.warning("ChannelDegradationManager: failed to get rolling stats: %s", exc)
            return alerts

        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT"]
        for tier in tiers:
            stats = rolling.get(tier, {})
            total = stats.get("total_signals", 0)
            if total < 5:
                # Not enough data to make a degradation decision
                continue

            wr = stats.get("win_rate", 0.0)

            if wr < CHANNEL_DEGRADATION_SUPPRESS_WR:
                # Full suppression
                if tier not in self._suppressed_channels:
                    self._suppressed_channels.add(tier)
                    self._degraded_channels[tier] = CHANNEL_DEGRADATION_EXTRA_CONFLUENCE
                    alerts.append(
                        f"⛔ *Channel Suppressed: {tier}*\n"
                        f"7d Win Rate: {wr:.1f}% (< {CHANNEL_DEGRADATION_SUPPRESS_WR:.0f}%)\n"
                        f"No new signals will be generated until WR recovers."
                    )
                    logger.warning(
                        "ChannelDegradationManager: suppressing %s (WR=%.1f%%)", tier, wr
                    )
            elif wr < CHANNEL_DEGRADATION_LOW_WR:
                # Degraded — raise confluence threshold
                if tier not in self._degraded_channels:
                    self._degraded_channels[tier] = CHANNEL_DEGRADATION_EXTRA_CONFLUENCE
                    self._suppressed_channels.discard(tier)
                    alerts.append(
                        f"⚠️ *Channel Degraded: {tier}*\n"
                        f"7d Win Rate: {wr:.1f}% (< {CHANNEL_DEGRADATION_LOW_WR:.0f}%)\n"
                        f"Confluence threshold raised by +{CHANNEL_DEGRADATION_EXTRA_CONFLUENCE} points."
                    )
                    logger.warning(
                        "ChannelDegradationManager: degrading %s (WR=%.1f%%)", tier, wr
                    )
            elif wr >= CHANNEL_DEGRADATION_RECOVERY_WR:
                # Recovery — restore normal thresholds
                was_degraded = tier in self._degraded_channels
                was_suppressed = tier in self._suppressed_channels
                if was_degraded or was_suppressed:
                    self._degraded_channels.pop(tier, None)
                    self._suppressed_channels.discard(tier)
                    alerts.append(
                        f"✅ *Channel Restored: {tier}*\n"
                        f"7d Win Rate: {wr:.1f}% (≥ {CHANNEL_DEGRADATION_RECOVERY_WR:.0f}%)\n"
                        f"Normal signal quality thresholds resumed."
                    )
                    logger.info(
                        "ChannelDegradationManager: restoring %s (WR=%.1f%%)", tier, wr
                    )

        return alerts

    def get_extra_confluence(self, channel_tier: str) -> int:
        """
        Return extra confluence points required for a degraded channel.

        Returns 0 when the channel is operating normally.
        """
        return self._degraded_channels.get(channel_tier, 0)

    def is_channel_suppressed(self, channel_tier: str) -> bool:
        """
        Return True if the channel is fully suppressed due to very poor WR.
        """
        return channel_tier in self._suppressed_channels

    def degraded_tiers(self) -> list[str]:
        """Return a list of currently degraded (but not suppressed) channel tiers."""
        return [t for t in self._degraded_channels if t not in self._suppressed_channels]

    def suppressed_tiers(self) -> list[str]:
        """Return a list of currently suppressed channel tiers."""
        return list(self._suppressed_channels)
