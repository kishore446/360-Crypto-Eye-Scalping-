"""
Tests for bot/signal_router.py — deduplication and routing logic.
"""
from __future__ import annotations

import time

from bot.signal_router import ChannelTier, SignalRouter


def _make_router(dedup_minutes: int = 15) -> SignalRouter:
    return SignalRouter(
        channel_hard=-100111,
        channel_medium=-100222,
        channel_easy=-100333,
        channel_spot=-100444,
        channel_insights=-100555,
        dedup_window_minutes=dedup_minutes,
    )


class TestSignalRouterChannelConfig:
    def test_get_channel_id(self):
        router = _make_router()
        assert router.get_channel_id(ChannelTier.HARD) == -100111
        assert router.get_channel_id(ChannelTier.MEDIUM) == -100222
        assert router.get_channel_id(ChannelTier.EASY) == -100333

    def test_channel_enabled_when_nonzero(self):
        router = _make_router()
        assert router.is_channel_enabled(ChannelTier.HARD) is True

    def test_channel_disabled_when_zero(self):
        router = SignalRouter(
            channel_hard=0,
            channel_medium=0,
            channel_easy=0,
            channel_spot=0,
            channel_insights=0,
        )
        assert router.is_channel_enabled(ChannelTier.HARD) is False
        assert router.is_channel_enabled(ChannelTier.MEDIUM) is False


class TestSignalRouterDeduplication:
    def test_no_suppression_before_any_signal(self):
        router = _make_router()
        assert router.should_suppress_duplicate("BTC", ChannelTier.MEDIUM) is False

    def test_medium_suppressed_after_hard_signal(self):
        router = _make_router(dedup_minutes=15)
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.MEDIUM) is True

    def test_easy_suppressed_after_hard_signal(self):
        router = _make_router(dedup_minutes=15)
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.EASY) is True

    def test_hard_never_suppressed(self):
        """HARD is a strict tier and should never be suppressed."""
        router = _make_router()
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.HARD) is False

    def test_spot_never_suppressed(self):
        router = _make_router()
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.SPOT) is False

    def test_insights_never_suppressed(self):
        router = _make_router()
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.INSIGHTS) is False

    def test_different_symbol_not_suppressed(self):
        router = _make_router()
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("ETH", ChannelTier.MEDIUM) is False

    def test_suppression_expires_after_window(self):
        router = SignalRouter(
            channel_hard=-100111,
            channel_medium=-100222,
            channel_easy=0,
            channel_spot=0,
            channel_insights=0,
            dedup_window_minutes=0,  # 0-minute window expires immediately
        )
        router.record_signal("BTC", ChannelTier.HARD)
        # With 0-minute window, signal should already be expired
        # (monotonic time won't go backward, so rely on window=0 → 0 seconds)
        # Wait a tiny bit to ensure time advances past the 0-second window
        time.sleep(0.01)
        assert router.should_suppress_duplicate("BTC", ChannelTier.MEDIUM) is False

    def test_medium_signal_suppresses_easy(self):
        """MEDIUM tier now triggers suppression of EASY (CH2 suppresses CH3)."""
        router = _make_router()
        router.record_signal("BTC", ChannelTier.MEDIUM)
        assert router.should_suppress_duplicate("BTC", ChannelTier.EASY) is True

    def test_easy_suppressed_after_medium_signal(self):
        """EASY is suppressed when MEDIUM has fired for the same symbol."""
        router = _make_router(dedup_minutes=15)
        router.record_signal("BTC", ChannelTier.MEDIUM)
        assert router.should_suppress_duplicate("BTC", ChannelTier.EASY) is True

    def test_medium_suppressed_by_same_channel_cooldown(self):
        """MEDIUM channel should not re-fire the same symbol within the dedup window."""
        router = _make_router(dedup_minutes=15)
        router.record_signal("BTC", ChannelTier.MEDIUM)
        assert router.should_suppress_duplicate("BTC", ChannelTier.MEDIUM) is True

    def test_easy_suppressed_by_same_channel_cooldown(self):
        """EASY channel should not re-fire the same symbol within the dedup window."""
        router = _make_router(dedup_minutes=15)
        router.record_signal("BTC", ChannelTier.EASY)
        assert router.should_suppress_duplicate("BTC", ChannelTier.EASY) is True

    def test_hard_not_suppressed_by_same_channel_cooldown(self):
        """HARD (strict) tier is never suppressed, even if it fired recently."""
        router = _make_router()
        router.record_signal("BTC", ChannelTier.HARD)
        assert router.should_suppress_duplicate("BTC", ChannelTier.HARD) is False

    def test_prune_removes_expired_records(self):
        """After expiry, the internal tracking dict should be cleaned up."""
        router = SignalRouter(
            channel_hard=-100111,
            channel_medium=-100222,
            channel_easy=0,
            channel_spot=0,
            channel_insights=0,
            dedup_window_minutes=0,
        )
        router.record_signal("BTC", ChannelTier.HARD)
        time.sleep(0.01)
        # Recording another signal triggers _prune_expired
        router.record_signal("ETH", ChannelTier.HARD)
        # BTC entry should have been pruned
        assert "BTC" not in router._recent_signals
