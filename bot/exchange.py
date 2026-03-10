"""
Resilient Exchange Client
=========================
Wraps CCXT with:
  - Exponential backoff with jitter (3 retries, base 2s)
  - Circuit breaker (5 consecutive failures → 120s cooldown)
  - Candle caching (1D: 4h TTL, 4H: 30min TTL, 5m: no cache)
  - Request weight tracking (prevents hitting Binance's 1200 weight/min limit)
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

# Rate-limit guard: stop at LIMIT - BUFFER to leave headroom for other callers
_WEIGHT_LIMIT = 1200
_WEIGHT_BUFFER = 100

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
    """CCXT exchange wrapper with retry, circuit breaker, caching, and rate-limit tracking."""

    def __init__(self, exchange_id: str = "binanceusdm") -> None:
        self._exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self._lock = threading.Lock()
        self._failure_count = 0
        self._circuit_open_until: float = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}  # key → (expires_at, data)
        # Request weight tracking
        self._weight_used: int = 0
        self._weight_reset_at: float = time.time() + 60

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _check_circuit(self) -> None:
        with self._lock:
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

    # ── Request weight tracking ────────────────────────────────────────────────

    def _check_weight(self, cost: int = 10) -> None:
        """Ensure the rolling weight budget has room for a *cost*-weight request.

        Reserves *cost* weight upfront under the lock.  If the reservation
        pushes the counter past the safe threshold the method sleeps until
        the current 60-second window resets, then adjusts the counter.

        Parameters
        ----------
        cost:
            Estimated request weight (default 10, suitable for most OHLCV
            and ticker endpoints).
        """
        sleep_time = 0.0
        with self._lock:
            now = time.time()
            # Lazily initialise weight-tracking attributes (supports __new__-based tests)
            if not hasattr(self, "_weight_reset_at"):
                self._weight_reset_at = now + 60
            if not hasattr(self, "_weight_used"):
                self._weight_used = 0
            if now >= self._weight_reset_at:
                self._weight_used = 0
                self._weight_reset_at = now + 60

            # Check threshold BEFORE incrementing so the logged counter is
            # accurate and we don't over-count weight when sleeping.
            if self._weight_used + cost >= _WEIGHT_LIMIT - _WEIGHT_BUFFER:
                sleep_time = max(0.1, self._weight_reset_at - now)
                logger.warning(
                    "Rate limit approaching (%d/%d), sleeping %.1fs",
                    self._weight_used + cost,
                    _WEIGHT_LIMIT,
                    sleep_time,
                )

            # Reserve weight upfront to prevent concurrent threads
            # from all passing the check before any increments
            self._weight_used += cost

        # Sleep outside the lock so other threads are not blocked
        if sleep_time > 0.0:
            time.sleep(sleep_time)
            with self._lock:
                # After sleeping, reset the window if it expired
                now = time.time()
                if now >= self._weight_reset_at:
                    self._weight_used = cost  # start fresh with just our cost
                    self._weight_reset_at = now + 60

    # ── Caching ───────────────────────────────────────────────────────────────

    def _cache_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}:{timeframe}"

    def _evict_expired_cache(self) -> None:
        """Remove all expired entries from the cache to prevent unbounded memory growth."""
        now = time.time()
        expired = [k for k, (exp, _) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]

    def _get_cached(self, symbol: str, timeframe: str) -> Optional[Any]:
        with self._lock:
            key = self._cache_key(symbol, timeframe)
            if key in self._cache:
                expires_at, data = self._cache[key]
                if time.time() < expires_at:
                    return data
            self._evict_expired_cache()
            return None

    def _set_cached(self, symbol: str, timeframe: str, data: Any) -> None:
        ttl = _CACHE_TTL.get(timeframe.lower(), 0)
        if ttl > 0:
            with self._lock:
                key = self._cache_key(symbol, timeframe)
                self._cache[key] = (time.time() + ttl, data)

    # ── Retry helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Return exponential backoff delay with jitter for the given attempt (1-based)."""
        return _RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1)

    def _fetch_with_retry(self, symbol: str, timeframe: str, limit: int = 50) -> list:
        """
        Fetch OHLCV candles with exponential-backoff retries.

        .. note::
            This method uses blocking ``time.sleep()`` for retry delays.  It
            **must not** be called directly from an async event-loop coroutine.
            Always invoke it from a thread-pool worker (e.g. via
            ``asyncio.get_event_loop().run_in_executor(None, ...)``) when used
            in an async context.
        """
        self._check_circuit()
        self._check_weight(cost=10)

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
        self._check_weight(cost=10)
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
        self._check_weight(cost=2)
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
