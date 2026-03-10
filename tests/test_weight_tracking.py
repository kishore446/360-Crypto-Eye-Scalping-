"""
Tests for request weight tracking in bot/exchange.py
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from bot.exchange import _WEIGHT_BUFFER, _WEIGHT_LIMIT, ResilientExchange


def _make_exchange() -> ResilientExchange:
    """Create a ResilientExchange with a mocked CCXT backend."""
    ex = ResilientExchange.__new__(ResilientExchange)
    ex._exchange = MagicMock()
    ex._lock = threading.Lock()
    ex._failure_count = 0
    ex._circuit_open_until = 0.0
    ex._cache = {}
    ex._weight_used = 0
    ex._weight_reset_at = time.time() + 60
    return ex


class TestWeightTracking:
    def test_weight_increments_on_each_call(self):
        ex = _make_exchange()
        initial = ex._weight_used
        ex._check_weight(cost=10)
        assert ex._weight_used == initial + 10

    def test_weight_reset_after_window_expires(self):
        ex = _make_exchange()
        ex._weight_used = 500
        # Wind the reset time back so the window has expired
        ex._weight_reset_at = time.time() - 1
        ex._check_weight(cost=10)
        # Should have reset and then added only 10
        assert ex._weight_used == 10

    def test_weight_does_not_exceed_limit_minus_buffer(self):
        """_check_weight should sleep when approaching the limit."""
        ex = _make_exchange()
        ex._weight_used = _WEIGHT_LIMIT - _WEIGHT_BUFFER - 5

        sleep_calls = []

        def fake_sleep(secs):
            sleep_calls.append(secs)
            # Advance time so the window resets immediately
            ex._weight_reset_at = time.time() - 1

        import bot.exchange as exchange_mod
        original = exchange_mod.time.sleep
        exchange_mod.time.sleep = fake_sleep
        try:
            ex._check_weight(cost=10)  # This should trigger the sleep
        finally:
            exchange_mod.time.sleep = original

        assert len(sleep_calls) == 1

    def test_weight_tracked_in_fetch_with_retry(self):
        """fetch_ohlcv must increment weight counter."""
        ex = _make_exchange()
        ex._exchange.fetch_ohlcv.return_value = [[1, 2, 3, 4, 5, 6]]

        initial_weight = ex._weight_used
        ex._fetch_with_retry("BTC/USDT", "5m", limit=10)
        assert ex._weight_used > initial_weight

    def test_weight_tracked_in_load_markets(self):
        """load_markets must increment weight counter."""
        ex = _make_exchange()
        ex._exchange.load_markets.return_value = {}

        initial_weight = ex._weight_used
        ex.load_markets()
        assert ex._weight_used > initial_weight

    def test_weight_tracked_in_fetch_ticker(self):
        """fetch_ticker must increment weight counter."""
        ex = _make_exchange()
        ex._exchange.fetch_ticker.return_value = {"last": 50000.0}

        initial_weight = ex._weight_used
        ex.fetch_ticker("BTC/USDT")
        assert ex._weight_used > initial_weight

    def test_lazy_init_on_new_instance(self):
        """_check_weight must work even when __init__ was not called (test compat)."""
        ex = ResilientExchange.__new__(ResilientExchange)
        ex._exchange = MagicMock()
        ex._lock = threading.Lock()
        ex._failure_count = 0
        ex._circuit_open_until = 0.0
        ex._cache = {}
        # Deliberately NOT setting _weight_used or _weight_reset_at

        # Should not raise
        ex._check_weight(cost=5)
        assert ex._weight_used == 5
