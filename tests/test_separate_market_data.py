"""
Tests for separate MarketDataStore instances (futures vs spot).
"""
from __future__ import annotations

import pytest

from bot.ws_manager import MarketDataStore, WebSocketManager, _WS_FUTURES_URL, _WS_SPOT_URL


class TestMarketDataStoreIndependence:
    """Verify that two MarketDataStore instances are completely independent."""

    def test_futures_and_spot_stores_are_independent(self):
        futures_store = MarketDataStore(market_type="futures")
        spot_store = MarketDataStore(market_type="spot")

        futures_store.update_candle("BTC", "5m", [1000, 50000, 51000, 49000, 50500, 100])
        futures_store.set_price("BTC", 50500)

        # Spot store should be empty
        assert spot_store.get_price("BTC") is None
        assert spot_store.get_candles("BTC", "5m") == []

    def test_updates_to_one_store_dont_affect_other(self):
        store_a = MarketDataStore(market_type="futures")
        store_b = MarketDataStore(market_type="spot")

        store_a.update_candle("ETH", "5m", [1000, 3000, 3100, 2900, 3050, 200])
        store_a.set_price("ETH", 3050)

        store_b.update_candle("ETH", "1h", [1000, 3000, 3100, 2900, 3050, 200])
        store_b.set_price("ETH", 3060)

        # Prices are independent
        assert store_a.get_price("ETH") == 3050
        assert store_b.get_price("ETH") == 3060

        # Spot store doesn't have 5m candles (spot uses 1h instead)
        assert store_b.get_candles("ETH", "5m") == []
        assert store_b.get_candles("ETH", "1h") != []

    def test_market_type_attribute_stored(self):
        futures_store = MarketDataStore(market_type="futures")
        spot_store = MarketDataStore(market_type="spot")
        assert futures_store.market_type == "futures"
        assert spot_store.market_type == "spot"

    def test_default_market_type_is_futures(self):
        store = MarketDataStore()
        assert store.market_type == "futures"


class TestMarketDataStoreBuffers:
    """Verify that futures and spot stores have the right buffer timeframes."""

    def test_futures_store_supports_5m(self):
        store = MarketDataStore(market_type="futures")
        store.update_candle("BTC", "5m", [1000, 50000, 51000, 49000, 50500, 100])
        assert len(store.get_candles("BTC", "5m")) == 1

    def test_futures_store_supports_15m(self):
        store = MarketDataStore(market_type="futures")
        store.update_candle("BTC", "15m", [1000, 50000, 51000, 49000, 50500, 100])
        assert len(store.get_candles("BTC", "15m")) == 1

    def test_spot_store_supports_1h(self):
        store = MarketDataStore(market_type="spot")
        store.update_candle("BTC", "1h", [1000, 50000, 51000, 49000, 50500, 100])
        assert len(store.get_candles("BTC", "1h")) == 1

    def test_spot_store_does_not_support_5m(self):
        """Spot buffers don't include 5m — returns empty list."""
        store = MarketDataStore(market_type="spot")
        store.update_candle("BTC", "5m", [1000, 50000, 51000, 49000, 50500, 100])
        # 5m is not in spot buffers, so update is ignored
        assert len(store.get_candles("BTC", "5m")) == 0

    def test_spot_has_sufficient_data_checks_1h(self):
        """Spot store uses 1h (not 5m) for has_sufficient_data."""
        store = MarketDataStore(market_type="spot")
        store.set_price("ETH", 3000.0)
        # Only 1h and 4h candles
        for i in range(3):
            store.update_candle("ETH", "1h", [i * 3600000, 3000, 3100, 2900, 3050, 100])
        for i in range(2):
            store.update_candle("ETH", "4h", [i * 14400000, 3000, 3100, 2900, 3050, 100])
        for i in range(20):
            store.update_candle("ETH", "1d", [i * 86400000, 3000, 3100, 2900, 3050, 100])
        # Should have sufficient data for spot
        assert store.has_sufficient_data("ETH") is True

    def test_futures_has_sufficient_data_checks_5m(self):
        """Futures store requires 5m data for has_sufficient_data."""
        store = MarketDataStore(market_type="futures")
        store.set_price("ETH", 3000.0)
        # Without 5m candles, not sufficient
        for i in range(2):
            store.update_candle("ETH", "4h", [i * 14400000, 3000, 3100, 2900, 3050, 100])
        for i in range(20):
            store.update_candle("ETH", "1d", [i * 86400000, 3000, 3100, 2900, 3050, 100])
        assert store.has_sufficient_data("ETH") is False


class TestWebSocketManagerMarketType:
    """Verify that WebSocketManager correctly selects URL based on market_type."""

    def test_futures_ws_uses_futures_url(self):
        store = MarketDataStore(market_type="futures")
        ws = WebSocketManager(store=store, market_type="futures")
        assert ws._ws_url == _WS_FUTURES_URL

    def test_spot_ws_uses_spot_url(self):
        store = MarketDataStore(market_type="spot")
        ws = WebSocketManager(store=store, market_type="spot")
        assert ws._ws_url == _WS_SPOT_URL

    def test_default_market_type_is_futures(self):
        store = MarketDataStore()
        ws = WebSocketManager(store=store)
        assert ws._market_type == "futures"
        assert ws._ws_url == _WS_FUTURES_URL

    def test_market_type_stored_on_manager(self):
        store = MarketDataStore(market_type="spot")
        ws = WebSocketManager(store=store, market_type="spot")
        assert ws._market_type == "spot"


class TestBotDualMarketDataInstances:
    """Verify bot.py creates separate futures and spot market data stores."""

    def test_bot_has_futures_market_data(self):
        import bot.bot as _bot
        assert hasattr(_bot, "futures_market_data")
        assert _bot.futures_market_data.market_type == "futures"

    def test_bot_has_spot_market_data(self):
        import bot.bot as _bot
        assert hasattr(_bot, "spot_market_data")
        assert _bot.spot_market_data.market_type == "spot"

    def test_market_data_alias_is_futures(self):
        """market_data alias should point to futures_market_data for backward compat."""
        import bot.bot as _bot
        assert _bot.market_data is _bot.futures_market_data

    def test_ws_manager_alias_is_futures_ws(self):
        """ws_manager alias should point to futures_ws for backward compat."""
        import bot.bot as _bot
        assert _bot.ws_manager is _bot.futures_ws

    def test_futures_and_spot_stores_are_different_objects(self):
        import bot.bot as _bot
        assert _bot.futures_market_data is not _bot.spot_market_data
