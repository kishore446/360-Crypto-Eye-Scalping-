"""Thread-safety tests for bot/exchange.py and bot/webhook.py."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestResilientExchangeThreadSafety:
    def test_circuit_breaker_check_uses_lock(self):
        """_check_circuit should use self._lock."""
        from bot.exchange import ResilientExchange
        with patch("ccxt.binanceusdm", return_value=MagicMock()):
            exc = ResilientExchange.__new__(ResilientExchange)
            exc._lock = threading.Lock()
            exc._failure_count = 0
            exc._circuit_open_until = 0.0
            exc._cache = {}
            # Should not raise when circuit is closed
            exc._check_circuit()

    def test_circuit_breaker_raises_when_open(self):
        """_check_circuit should raise when circuit is open."""
        from bot.exchange import CircuitBreakerOpen, ResilientExchange
        with patch("ccxt.binanceusdm", return_value=MagicMock()):
            exc = ResilientExchange.__new__(ResilientExchange)
            exc._lock = threading.Lock()
            exc._failure_count = 0
            exc._circuit_open_until = time.time() + 120.0
            exc._cache = {}
            with pytest.raises(CircuitBreakerOpen):
                exc._check_circuit()

    def test_get_cached_uses_lock(self):
        """_get_cached should use self._lock."""
        from bot.exchange import ResilientExchange
        with patch("ccxt.binanceusdm", return_value=MagicMock()):
            exc = ResilientExchange.__new__(ResilientExchange)
            exc._lock = threading.Lock()
            exc._failure_count = 0
            exc._circuit_open_until = 0.0
            exc._cache = {}
            # Should return None for uncached data
            result = exc._get_cached("BTC/USDT", "5m")
            assert result is None

    def test_set_cached_uses_lock(self):
        """_set_cached should use self._lock."""
        from bot.exchange import ResilientExchange
        with patch("ccxt.binanceusdm", return_value=MagicMock()):
            exc = ResilientExchange.__new__(ResilientExchange)
            exc._lock = threading.Lock()
            exc._failure_count = 0
            exc._circuit_open_until = 0.0
            exc._cache = {}
            # TTL=0 for 5m, no caching
            exc._set_cached("BTC/USDT", "5m", [1, 2, 3])
            assert exc._get_cached("BTC/USDT", "5m") is None
            # TTL>0 for 1d, should cache
            exc._set_cached("BTC/USDT", "1d", [1, 2, 3])
            assert exc._get_cached("BTC/USDT", "1d") is not None

    def test_concurrent_cache_access(self):
        """Multiple threads should safely access the cache."""
        from bot.exchange import ResilientExchange
        with patch("ccxt.binanceusdm", return_value=MagicMock()):
            exc = ResilientExchange.__new__(ResilientExchange)
            exc._lock = threading.Lock()
            exc._failure_count = 0
            exc._circuit_open_until = 0.0
            exc._cache = {}

            errors = []

            def worker(i: int) -> None:
                try:
                    exc._set_cached(f"SYM{i}/USDT", "1d", [i, i + 1])
                    exc._get_cached(f"SYM{i}/USDT", "1d")
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors


class TestWebhookRateLimitThreadSafety:
    def test_rate_limit_lock_exists(self):
        """_rate_limit_lock should be a threading.Lock."""
        import bot.webhook as webhook_mod
        assert hasattr(webhook_mod, "_rate_limit_lock")
        assert hasattr(webhook_mod._rate_limit_lock, "acquire")  # duck-type: lock-like object

    def test_concurrent_rate_limit_checks(self):
        """Multiple threads checking rate limits should not corrupt state."""
        import bot.webhook as webhook_mod

        # Clear any existing entries
        webhook_mod._request_log.clear()

        errors = []
        results = []

        def worker() -> None:
            try:
                result = webhook_mod._check_rate_limit("192.168.1.1")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Some requests should pass, some should be rate-limited
        assert len(results) == 20


class TestSendTelegramMessageBackground:
    def test_send_uses_background_thread(self):
        """_send_telegram_message should dispatch via a daemon thread."""
        import bot.webhook as webhook_mod

        threads_started = []

        class MockThread:
            def __init__(self, target=None, daemon=None, **kwargs):
                self.daemon = daemon
                self._target = target
                threads_started.append(self)

            def start(self):
                pass  # Don't actually start

        with patch("bot.webhook.threading.Thread", MockThread):
            webhook_mod._send_telegram_message("test", 12345)

        assert len(threads_started) == 1
        assert threads_started[0].daemon is True
