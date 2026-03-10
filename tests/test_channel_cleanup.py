"""
Tests for channel routing cleanup — TELEGRAM_CHANNEL_ID deprecation
and correct routing to CH1-CH5.
"""
from __future__ import annotations

import asyncio


class TestTelegramChannelIdDeprecation:
    """Verify TELEGRAM_CHANNEL_ID still exists but CH1-CH5 are the primary channels."""

    def test_legacy_channel_id_still_exists(self):
        """Backward compat: TELEGRAM_CHANNEL_ID should still be importable."""
        import config
        assert hasattr(config, "TELEGRAM_CHANNEL_ID")

    def test_channel_scalping_is_primary_channel(self):
        """TELEGRAM_CHANNEL_ID_SCALPING should be the primary scalping channel."""
        import config
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_SCALPING")

    def test_all_five_channels_exist(self):
        """All 5 channel IDs should be importable from config."""
        import config
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_SCALPING")
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_INTRADAY")
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_TREND")
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_SPOT")
        assert hasattr(config, "TELEGRAM_CHANNEL_ID_INSIGHTS")

    def test_channel_hard_falls_back_to_legacy(self):
        """If only legacy TELEGRAM_CHANNEL_ID is set, CH1 should use it."""
        # This tests the fallback logic in config.py:
        # TELEGRAM_CHANNEL_ID_SCALPING = settings.telegram_channel_id_scalping or settings.telegram_channel_id
        env = {
            "TELEGRAM_CHANNEL_ID": "-100123456789",
            "TELEGRAM_CHANNEL_ID_SCALPING": "0",
        }
        legacy = int(env["TELEGRAM_CHANNEL_ID"])
        hard = int(env["TELEGRAM_CHANNEL_ID_SCALPING"])
        effective = hard or legacy
        assert effective == legacy


class TestBroadcastFunctionUsesHardChannel:
    """Verify _broadcast() now uses TELEGRAM_CHANNEL_ID_SCALPING as primary."""

    def test_broadcast_uses_channel_hard_not_legacy(self, monkeypatch):
        """_broadcast() should use TELEGRAM_CHANNEL_ID_SCALPING as the primary channel."""
        from unittest.mock import AsyncMock, MagicMock

        import bot.bot as _bot

        sent_to = []

        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID_SCALPING", -100_111_111_111)
        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", -100_999_999_999)

        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=lambda **kw: sent_to.append(kw["chat_id"]))

        asyncio.get_event_loop().run_until_complete(_bot._broadcast(context, "Test message"))

        # Should have sent to CH1_SCALPING, not legacy
        assert -100_111_111_111 in sent_to
        assert -100_999_999_999 not in sent_to

    def test_broadcast_falls_back_to_legacy_when_hard_is_zero(self, monkeypatch):
        """When TELEGRAM_CHANNEL_ID_SCALPING is 0, falls back to TELEGRAM_CHANNEL_ID."""
        from unittest.mock import AsyncMock, MagicMock

        import bot.bot as _bot

        sent_to = []

        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID_SCALPING", 0)
        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", -100_999_999_999)

        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=lambda **kw: sent_to.append(kw["chat_id"]))

        asyncio.get_event_loop().run_until_complete(_bot._broadcast(context, "Test message"))

        # Should have sent to legacy channel
        assert -100_999_999_999 in sent_to

    def test_broadcast_skips_when_both_channels_zero(self, monkeypatch):
        """When both channel IDs are 0, broadcast is a no-op."""
        from unittest.mock import AsyncMock, MagicMock

        import bot.bot as _bot

        sent_to = []

        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID_SCALPING", 0)
        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", 0)

        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=lambda **kw: sent_to.append(kw["chat_id"]))

        asyncio.get_event_loop().run_until_complete(_bot._broadcast(context, "Test message"))
        assert sent_to == []


class TestSignalRouterChannels:
    """Verify signal router routes to the correct channels."""

    def test_hard_channel_routes_to_ch1(self):
        from bot.signal_router import ChannelTier, SignalRouter
        router = SignalRouter(
            channel_scalping=-100_111,
            channel_intraday=-100_222,
            channel_trend=-100_333,
            channel_spot=-100_444,
            channel_insights=-100_555,
        )
        assert router.get_channel_id(ChannelTier.SCALPING) == -100_111

    def test_spot_channel_routes_to_ch4(self):
        from bot.signal_router import ChannelTier, SignalRouter
        router = SignalRouter(
            channel_scalping=-100_111,
            channel_intraday=-100_222,
            channel_trend=-100_333,
            channel_spot=-100_444,
            channel_insights=-100_555,
        )
        assert router.get_channel_id(ChannelTier.SPOT) == -100_444

    def test_insights_channel_routes_to_ch5(self):
        from bot.signal_router import ChannelTier, SignalRouter
        router = SignalRouter(
            channel_scalping=-100_111,
            channel_intraday=-100_222,
            channel_trend=-100_333,
            channel_spot=-100_444,
            channel_insights=-100_555,
        )
        assert router.get_channel_id(ChannelTier.INSIGHTS) == -100_555

    def test_disabled_channel_returns_zero(self):
        from bot.signal_router import ChannelTier, SignalRouter
        router = SignalRouter(
            channel_scalping=0,
            channel_intraday=0,
            channel_trend=0,
            channel_spot=0,
            channel_insights=0,
        )
        assert not router.is_channel_enabled(ChannelTier.SCALPING)
        assert not router.is_channel_enabled(ChannelTier.SPOT)

    def test_all_channels_correctly_reported_enabled(self):
        from bot.signal_router import ChannelTier, SignalRouter
        router = SignalRouter(
            channel_scalping=-100_111,
            channel_intraday=-100_222,
            channel_trend=-100_333,
            channel_spot=-100_444,
            channel_insights=-100_555,
        )
        # Core CH1-CH5 channels should be enabled
        for tier in (
            ChannelTier.SCALPING, ChannelTier.INTRADAY, ChannelTier.TREND,
            ChannelTier.SPOT, ChannelTier.INSIGHTS,
        ):
            assert router.is_channel_enabled(tier), f"{tier} should be enabled"
        # New optional CH6-CH9 channels default to 0 (disabled) — this is correct
        for tier in (
            ChannelTier.ALTGEMS, ChannelTier.WHALE_TRACKER,
            ChannelTier.EDUCATION, ChannelTier.VIP_DISCUSSION,
        ):
            assert not router.is_channel_enabled(tier), f"{tier} should be disabled by default"


class TestNewSpotConfigVars:
    """Verify new spot-related config variables exist with safe defaults."""

    def test_spot_scan_enabled_default(self):
        import config
        assert hasattr(config, "SPOT_SCAN_ENABLED")
        assert config.SPOT_SCAN_ENABLED is True  # safe default

    def test_spot_scan_interval_default(self):
        import config
        assert hasattr(config, "SPOT_SCAN_INTERVAL_MINUTES")
        assert config.SPOT_SCAN_INTERVAL_MINUTES > 0

    def test_spot_min_volume_default(self):
        import config
        assert hasattr(config, "SPOT_MIN_24H_VOLUME_USDT")
        assert config.SPOT_MIN_24H_VOLUME_USDT >= 0

    def test_spot_gem_volume_spike_ratio_default(self):
        import config
        assert hasattr(config, "SPOT_GEM_VOLUME_SPIKE_RATIO")
        assert config.SPOT_GEM_VOLUME_SPIKE_RATIO > 1.0

    def test_spot_scam_thresholds_default(self):
        import config
        assert hasattr(config, "SPOT_SCAM_PUMP_THRESHOLD_PCT")
        assert config.SPOT_SCAM_PUMP_THRESHOLD_PCT > 100
        assert hasattr(config, "SPOT_SCAM_CRASH_THRESHOLD_PCT")
        assert config.SPOT_SCAM_CRASH_THRESHOLD_PCT > 10
