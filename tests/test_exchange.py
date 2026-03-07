"""Tests for bot/exchange.py — circuit breaker, retry, caching."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from bot.exchange import (
    _CACHE_TTL,
    _CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreakerOpen,
    ResilientExchange,
)


def _make_exchange() -> ResilientExchange:
    """Create a fresh ResilientExchange with a mocked underlying CCXT exchange."""
    ex = ResilientExchange.__new__(ResilientExchange)
    ex._exchange = MagicMock()
    ex._lock = __import__("threading").Lock()
    ex._failure_count = 0
    ex._circuit_open_until = 0.0
    ex._cache = {}
    return ex


class TestCircuitBreaker:
    def test_circuit_opens_after_threshold_failures(self):
        ex = _make_exchange()
        ex._exchange.fetch_ohlcv.side_effect = RuntimeError("network error")

        with pytest.raises(RuntimeError):
            ex._fetch_with_retry("BTC/USDT:USDT", "5m", limit=5)

        # Trigger enough failures to open the circuit
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD - 1):
            ex._record_failure()

        assert ex._circuit_open_until > 0

    def test_circuit_breaker_raises_when_open(self):
        ex = _make_exchange()
        ex._circuit_open_until = time.time() + 9999

        with pytest.raises(CircuitBreakerOpen):
            ex._check_circuit()

    def test_circuit_breaker_passes_when_expired(self):
        ex = _make_exchange()
        ex._circuit_open_until = time.time() - 1  # already expired

        # Should not raise
        ex._check_circuit()

    def test_success_resets_failure_count(self):
        ex = _make_exchange()
        ex._failure_count = 3
        ex._record_success()
        assert ex._failure_count == 0


class TestCaching:
    def test_cache_hit_returns_cached_data(self):
        ex = _make_exchange()
        fake_data = [[1, 2, 3, 4, 5, 100]]
        ex._exchange.fetch_ohlcv.return_value = fake_data

        # First call — populates cache (1d has TTL)
        result1 = ex.fetch_ohlcv("BTC/USDT:USDT", "1d", limit=5)
        assert result1 == fake_data

        # Change return value — should NOT be returned (cache hit)
        ex._exchange.fetch_ohlcv.return_value = [[99, 99, 99, 99, 99, 99]]
        result2 = ex.fetch_ohlcv("BTC/USDT:USDT", "1d", limit=5)
        assert result2 == fake_data  # cached

    def test_no_cache_for_5m(self):
        ex = _make_exchange()
        fake1 = [[1, 2, 3, 4, 5, 100]]
        fake2 = [[9, 9, 9, 9, 9, 999]]
        ex._exchange.fetch_ohlcv.side_effect = [fake1, fake2]

        result1 = ex.fetch_ohlcv("BTC/USDT:USDT", "5m", limit=5)
        result2 = ex.fetch_ohlcv("BTC/USDT:USDT", "5m", limit=5)

        assert result1 == fake1
        assert result2 == fake2  # no cache, second call fetches fresh

    def test_cache_expires(self):
        ex = _make_exchange()
        fake_data = [[1, 2, 3, 4, 5, 100]]
        ex._exchange.fetch_ohlcv.return_value = fake_data

        # Manually insert expired cache entry
        key = ex._cache_key("BTC/USDT:USDT", "4h")
        ex._cache[key] = (time.time() - 1, fake_data)  # expired

        # Fresh data
        new_data = [[9, 9, 9, 9, 9, 999]]
        ex._exchange.fetch_ohlcv.return_value = new_data
        result = ex.fetch_ohlcv("BTC/USDT:USDT", "4h", limit=5)
        assert result == new_data

    def test_cache_ttl_values(self):
        assert _CACHE_TTL["1d"] == 4 * 3600
        assert _CACHE_TTL["4h"] == 30 * 60
        assert _CACHE_TTL["5m"] == 0


class TestRetryLogic:
    def test_retries_on_transient_failure(self):
        ex = _make_exchange()
        fake_data = [[1, 2, 3, 4, 5, 100]]
        # Fail twice, succeed on third attempt
        ex._exchange.fetch_ohlcv.side_effect = [
            RuntimeError("timeout"),
            RuntimeError("timeout"),
            fake_data,
        ]

        with patch("time.sleep"):  # avoid actual sleeping in tests
            result = ex._fetch_with_retry("BTC/USDT:USDT", "5m", limit=5)

        assert result == fake_data
        assert ex._exchange.fetch_ohlcv.call_count == 3

    def test_raises_after_max_retries(self):
        ex = _make_exchange()
        ex._exchange.fetch_ohlcv.side_effect = RuntimeError("persistent error")

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="persistent error"):
                ex._fetch_with_retry("BTC/USDT:USDT", "5m", limit=5)

    def test_fetch_ticker_with_retry(self):
        ex = _make_exchange()
        fake_ticker = {"last": 50000.0}
        ex._exchange.fetch_ticker.return_value = fake_ticker
        result = ex.fetch_ticker("BTC/USDT:USDT")
        assert result == fake_ticker
