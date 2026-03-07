"""
Resilient Exchange Client
=========================
Wraps CCXT with:
  - Exponential backoff with jitter (3 retries, base 2s)
  - Circuit breaker (5 consecutive failures → 120s cooldown)
  - Candle caching (1D: 4h TTL, 4H: 30min TTL, 5m: no cache)
  - Request weight tracking
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Optional

import ccxt

logger = logging.getLogger(__name__)

_RETRY_COUNT = 3
_RETRY_BASE_SECONDS = 2.0
_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_COOLDOWN = 120.0

# Cache TTLs in seconds
_CACHE_TTL: dict[str, float] = {
    "1d": 4 * 3600,
    "4h": 30 * 60,
    "15m": 5 * 60,
    "5m": 0,  # no cache — always fresh
}


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and requests are halted."""


class ResilientExchange:
    """CCXT exchange wrapper with retry, circuit breaker, and caching."""

    def __init__(self, exchange_id: str = "binanceusdm") -> None:
        self._exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self._lock = threading.Lock()
        self._failure_count = 0
        self._circuit_open_until: float = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}  # key → (expires_at, data)

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _check_circuit(self) -> None:
        if time.time() < self._circuit_open_until:
            remaining = self._circuit_open_until - time.time()
            raise CircuitBreakerOpen(
                f"Circuit breaker open — retry in {remaining:.0f}s"
            )

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0

    def _record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= _CIRCUIT_BREAKER_THRESHOLD:
                self._circuit_open_until = time.time() + _CIRCUIT_BREAKER_COOLDOWN
                logger.critical(
                    "Circuit breaker OPENED after %d consecutive failures. "
                    "Halting API calls for %ds.",
                    self._failure_count,
                    _CIRCUIT_BREAKER_COOLDOWN,
                )
                self._failure_count = 0

    # ── Caching ───────────────────────────────────────────────────────────────

    def _cache_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}:{timeframe}"

    def _get_cached(self, symbol: str, timeframe: str) -> Optional[Any]:
        key = self._cache_key(symbol, timeframe)
        if key in self._cache:
            expires_at, data = self._cache[key]
            if time.time() < expires_at:
                return data
        return None

    def _set_cached(self, symbol: str, timeframe: str, data: Any) -> None:
        ttl = _CACHE_TTL.get(timeframe.lower(), 0)
        if ttl > 0:
            key = self._cache_key(symbol, timeframe)
            self._cache[key] = (time.time() + ttl, data)

    # ── Retry helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Return exponential backoff delay with jitter for the given attempt (1-based)."""
        return _RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1)

    def _fetch_with_retry(self, symbol: str, timeframe: str, limit: int = 50) -> list:
        self._check_circuit()

        for attempt in range(1, _RETRY_COUNT + 1):
            try:
                data = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                self._record_success()
                return data
            except CircuitBreakerOpen:
                raise
            except Exception as exc:
                self._record_failure()
                if attempt < _RETRY_COUNT:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "Binance fetch failed (%s/%s, attempt %d/%d): %s — retrying in %.1fs",
                        symbol, timeframe, attempt, _RETRY_COUNT, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Binance fetch failed (%s/%s) after %d attempts: %s",
                        symbol, timeframe, _RETRY_COUNT, exc,
                    )
                    raise

        return []  # unreachable but satisfies type checker

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 50) -> list:
        """Fetch OHLCV candles with caching and retry."""
        cached = self._get_cached(symbol, timeframe)
        if cached is not None:
            logger.debug("Cache hit: %s %s", symbol, timeframe)
            return cached

        data = self._fetch_with_retry(symbol, timeframe, limit)
        self._set_cached(symbol, timeframe, data)
        return data

    def load_markets(self):
        """Load exchange markets with retry."""
        self._check_circuit()
        for attempt in range(1, _RETRY_COUNT + 1):
            try:
                self._exchange.load_markets()
                self._record_success()
                return self._exchange.markets
            except CircuitBreakerOpen:
                raise
            except Exception:
                self._record_failure()
                if attempt < _RETRY_COUNT:
                    delay = self._backoff_delay(attempt)
                    time.sleep(delay)
                else:
                    raise
        return {}

    @property
    def markets(self):
        return self._exchange.markets

    def fetch_ticker(self, symbol: str) -> dict:
        """Fetch current ticker (no caching)."""
        self._check_circuit()
        for attempt in range(1, _RETRY_COUNT + 1):
            try:
                ticker = self._exchange.fetch_ticker(symbol)
                self._record_success()
                return ticker
            except CircuitBreakerOpen:
                raise
            except Exception:
                self._record_failure()
                if attempt < _RETRY_COUNT:
                    delay = self._backoff_delay(attempt)
                    time.sleep(delay)
                else:
                    raise

        return {}



# Module-level singleton — import this in bot.py
_resilient_exchange = ResilientExchange()

# Spot exchange singleton — uses regular Binance (not binanceusdm)
_spot_resilient_exchange = ResilientExchange(exchange_id="binance")


def fetch_spot_ohlcv(symbol: str, timeframe: str, limit: int = 50) -> list:
    """Fetch OHLCV candles for a Binance Spot pair (e.g. 'BTC/USDT')."""
    return _spot_resilient_exchange.fetch_ohlcv(symbol, timeframe, limit)


def fetch_spot_ticker(symbol: str) -> dict:
    """Fetch current 24h ticker data for a Binance Spot pair (e.g. 'BTC/USDT')."""
    return _spot_resilient_exchange.fetch_ticker(symbol)
