"""
Tests for full-market futures scanning with dynamic pair discovery.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestDynamicPairDiscovery:
    """Test _refresh_dynamic_pairs() with different AUTO_SCAN_PAIRS configurations."""

    def test_refresh_uses_all_pairs_when_auto_scan_empty(self, monkeypatch):
        """When AUTO_SCAN_PAIRS is empty, _dynamic_pairs should get ALL fetched pairs."""
        import bot.bot as _bot

        mock_pairs = ["BTC", "ETH", "SOL", "XRP", "ADA"]
        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", [])
        monkeypatch.setattr(_bot, "fetch_binance_futures_pairs", lambda: mock_pairs)

        _bot._refresh_dynamic_pairs()

        assert _bot._dynamic_pairs == mock_pairs

    def test_refresh_filters_to_whitelist_when_set(self, monkeypatch):
        """When AUTO_SCAN_PAIRS is set, acts as a whitelist filter."""
        import bot.bot as _bot

        mock_pairs = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"]
        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", ["BTC", "ETH"])
        monkeypatch.setattr(_bot, "fetch_binance_futures_pairs", lambda: mock_pairs)

        _bot._refresh_dynamic_pairs()

        assert set(_bot._dynamic_pairs) == {"BTC", "ETH"}

    def test_refresh_falls_back_to_fetched_when_whitelist_empty_after_filter(self, monkeypatch):
        """When whitelist contains no valid pairs, fall back to all fetched."""
        import bot.bot as _bot

        mock_pairs = ["BTC", "ETH"]
        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", ["DOESNOTEXIST"])
        monkeypatch.setattr(_bot, "fetch_binance_futures_pairs", lambda: mock_pairs)

        _bot._refresh_dynamic_pairs()

        # Falls back to all fetched pairs
        assert _bot._dynamic_pairs == mock_pairs

    def test_refresh_uses_fetched_pairs_not_empty_list(self, monkeypatch):
        """Empty AUTO_SCAN_PAIRS means scan all, not zero pairs."""
        import bot.bot as _bot

        mock_pairs = ["BTC", "ETH", "SOL", "PEPE", "WIF", "BONK"]
        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", [])
        monkeypatch.setattr(_bot, "fetch_binance_futures_pairs", lambda: mock_pairs)

        _bot._refresh_dynamic_pairs()

        assert len(_bot._dynamic_pairs) == 6
        assert "PEPE" in _bot._dynamic_pairs


class TestFetchBinanceFuturesPairs:
    """Test fetch_binance_futures_pairs() with mocked exchange."""

    def test_fallback_on_exception(self, monkeypatch):
        """Falls back to AUTO_SCAN_PAIRS when exchange fails."""
        import bot.bot as _bot

        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", ["BTC", "ETH"])
        monkeypatch.setattr(
            _bot._resilient_exchange,
            "load_markets",
            MagicMock(side_effect=Exception("network error")),
        )

        result = _bot.fetch_binance_futures_pairs()
        assert result == ["BTC", "ETH"]

    def test_fallback_returns_empty_when_auto_scan_pairs_empty(self, monkeypatch):
        """Falls back to empty list when AUTO_SCAN_PAIRS is empty and exchange fails."""
        import bot.bot as _bot

        monkeypatch.setattr(_bot, "AUTO_SCAN_PAIRS", [])
        monkeypatch.setattr(
            _bot._resilient_exchange,
            "load_markets",
            MagicMock(side_effect=Exception("network error")),
        )

        result = _bot.fetch_binance_futures_pairs()
        assert result == []


class TestBatchProcessingConfig:
    """Test that batch processing config values are accessible."""

    def test_futures_scan_batch_size_exists(self):
        import config
        assert hasattr(config, "FUTURES_SCAN_BATCH_SIZE")
        assert isinstance(config.FUTURES_SCAN_BATCH_SIZE, int)
        assert config.FUTURES_SCAN_BATCH_SIZE > 0

    def test_futures_scan_batch_delay_exists(self):
        import config
        assert hasattr(config, "FUTURES_SCAN_BATCH_DELAY")
        assert isinstance(config.FUTURES_SCAN_BATCH_DELAY, float)
        assert config.FUTURES_SCAN_BATCH_DELAY >= 0

    def test_futures_min_24h_volume_exists(self):
        import config
        assert hasattr(config, "FUTURES_MIN_24H_VOLUME_USDT")
        assert isinstance(config.FUTURES_MIN_24H_VOLUME_USDT, int)
        assert config.FUTURES_MIN_24H_VOLUME_USDT >= 0

    def test_auto_scan_pairs_default_is_empty(self):
        """New default: empty means scan ALL pairs."""
        import config
        assert config.AUTO_SCAN_PAIRS == []


class TestFallbackScanBatching:
    """Test that fallback scan job uses batch processing."""

    def test_scan_job_is_no_op_when_ws_healthy(self, monkeypatch):
        """The fallback scan job skips when WS is healthy."""
        import bot.bot as _bot

        _bot._bot_state.auto_scan_active = True
        healthy = MagicMock()
        healthy.is_healthy.return_value = True
        monkeypatch.setattr(_bot, "ws_manager", healthy)

        # Should not raise and should return quickly
        _bot._run_fallback_scan_job()

    def test_scan_job_is_no_op_when_inactive(self, monkeypatch):
        """The fallback scan job is a no-op when auto_scan is inactive."""
        import bot.bot as _bot

        _bot._bot_state.auto_scan_active = False
        healthy = MagicMock()
        healthy.is_healthy.return_value = False
        monkeypatch.setattr(_bot, "ws_manager", healthy)

        _bot._run_fallback_scan_job()
        # No pairs should have been scanned
