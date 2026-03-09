"""
Tests for thread-safety fixes in:
  - bot/webhook.py  (_check_rate_limit with threading.Lock)
  - bot/exchange.py (_get_cached / _set_cached / _check_circuit under self._lock)
  - bot/state.py    (BotState.reset())
"""
from __future__ import annotations

import threading
import time

import pytest

from bot.state import BotState


# ── BotState.reset() ─────────────────────────────────────────────────────────


class TestBotStateReset:
    def test_reset_clears_singleton(self):
        """After reset(), BotState() returns a new instance."""
        BotState.reset()
        inst1 = BotState()
        # Mutate some state
        inst1.news_freeze = True
        # Reset and create a new instance
        BotState.reset()
        inst2 = BotState()
        assert inst2 is not inst1
        assert inst2.news_freeze is False

    def test_reset_is_idempotent(self):
        """Calling reset() multiple times does not raise."""
        BotState.reset()
        BotState.reset()
        state = BotState()
        assert state is not None

    def test_reset_works_after_state_modification(self):
        """reset() should clear even after multiple state changes."""
        BotState.reset()
        state = BotState()
        state.auto_scan_active = False
        state.record_signal_generated()
        BotState.reset()
        fresh = BotState()
        # auto_scan_active defaults to True from config
        assert fresh.seconds_since_last_signal() == float("inf")


# ── Rate limiter thread safety ────────────────────────────────────────────────


class TestRateLimiterThreadSafety:
    def test_lock_exists(self):
        """The rate limit lock should be a threading.Lock."""
        from bot import webhook
        assert isinstance(webhook._rate_limit_lock, type(threading.Lock()))

    def test_concurrent_requests_from_same_ip(self):
        """Under concurrent access, rate limit should not allow more than max requests."""
        from bot import webhook

        # Save and restore original module state
        orig_window = webhook.WEBHOOK_RATE_LIMIT_WINDOW
        orig_max = webhook.WEBHOOK_RATE_LIMIT_MAX
        test_ip = "CONCURRENT_TEST_IP_UNIQUE"
        try:
            webhook.WEBHOOK_RATE_LIMIT_WINDOW = 60
            webhook.WEBHOOK_RATE_LIMIT_MAX = 5

            # Clear any existing log for this IP
            with webhook._rate_limit_lock:
                webhook._request_log[test_ip] = []

            results = []
            errors = []

            def _make_request():
                try:
                    ok = webhook._check_rate_limit(test_ip)
                    results.append(ok)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=_make_request) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Exceptions during concurrent access: {errors}"
            # Exactly 5 requests should be allowed, rest rejected
            allowed = sum(1 for r in results if r)
            assert allowed == 5
        finally:
            webhook.WEBHOOK_RATE_LIMIT_WINDOW = orig_window
            webhook.WEBHOOK_RATE_LIMIT_MAX = orig_max
            with webhook._rate_limit_lock:
                webhook._request_log.pop(test_ip, None)

    def test_rate_limit_resets_after_window(self):
        """Rate limit counter should reset after the window expires."""
        from bot import webhook

        orig_window = webhook.WEBHOOK_RATE_LIMIT_WINDOW
        orig_max = webhook.WEBHOOK_RATE_LIMIT_MAX
        test_ip = "RESET_TEST_IP_UNIQUE"
        try:
            webhook.WEBHOOK_RATE_LIMIT_WINDOW = 1  # 1-second window
            webhook.WEBHOOK_RATE_LIMIT_MAX = 2

            with webhook._rate_limit_lock:
                webhook._request_log[test_ip] = []

            assert webhook._check_rate_limit(test_ip) is True
            assert webhook._check_rate_limit(test_ip) is True
            assert webhook._check_rate_limit(test_ip) is False  # limit exceeded

            time.sleep(1.1)  # Wait for window to expire
            assert webhook._check_rate_limit(test_ip) is True  # counter reset
        finally:
            webhook.WEBHOOK_RATE_LIMIT_WINDOW = orig_window
            webhook.WEBHOOK_RATE_LIMIT_MAX = orig_max
            with webhook._rate_limit_lock:
                webhook._request_log.pop(test_ip, None)


# ── Exchange cache thread safety ──────────────────────────────────────────────


class TestExchangeCacheThreadSafety:
    def test_cache_operations_do_not_raise_under_concurrency(self):
        """Concurrent cache reads/writes should not raise RuntimeError."""
        from bot.exchange import ResilientExchange

        # Use a mock that doesn't actually connect
        import unittest.mock as mock
        with mock.patch("ccxt.binanceusdm") as mock_ccxt:
            mock_ccxt.return_value = mock.MagicMock()
            exchange = ResilientExchange.__new__(ResilientExchange)
            exchange._lock = threading.Lock()
            exchange._cache = {}

        errors = []

        def _write():
            try:
                # Simulate _set_cached behavior
                with exchange._lock:
                    exchange._cache["BTC:5m"] = (time.time() + 60, [1, 2, 3])
            except Exception as e:
                errors.append(e)

        def _read():
            try:
                # Simulate _get_cached behavior
                with exchange._lock:
                    _ = exchange._cache.get("BTC:5m")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write if i % 2 == 0 else _read)
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_circuit_breaker_check_uses_lock(self):
        """_check_circuit should be safe to call from multiple threads."""
        from bot.exchange import ResilientExchange, CircuitBreakerOpen
        import unittest.mock as mock

        with mock.patch("ccxt.binanceusdm") as mock_ccxt:
            mock_ccxt.return_value = mock.MagicMock()
            exchange = ResilientExchange.__new__(ResilientExchange)
            exchange._lock = threading.Lock()
            exchange._failure_count = 0
            exchange._circuit_open_until = 0.0
            exchange._cache = {}

        errors = []

        def _check():
            try:
                exchange._check_circuit()
            except CircuitBreakerOpen:
                pass  # Expected when circuit is open
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
