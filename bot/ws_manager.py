"""
WebSocket Market Data Manager
==============================
Connects to Binance combined-stream endpoints and maintains
in-memory ring buffers of OHLCV candles and real-time prices.

Key design points:
- Supports both Futures (fstream.binance.com) and Spot (stream.binance.com) markets
  via the ``market_type`` parameter ("futures" | "spot").
- Subscribes to ``@kline_5m``, ``@kline_15m``, ``@kline_4h``, ``@kline_1d``, and
  ``@miniTicker`` for futures pairs; ``@kline_1h``, ``@kline_4h``, ``@kline_1d`` and
  ``@miniTicker`` for spot pairs.
- Splits pairs across multiple WS connections (≤200 streams per connection,
  ≈50 symbols per connection because each symbol uses 4 streams).
- Fires an async ``on_candle_close(base_symbol, timeframe)`` callback on
  every **closed** 5m kline event (futures) or 1h kline event (spot).
- Auto-reconnects with exponential back-off + jitter (1 s base, 60 s cap).
- Tracks ``last_message_at`` timestamp and ``is_connected`` flag for health
  monitoring; consumers can call ``is_healthy()`` to determine whether the
  fallback polling job should activate.
- Provides ``has_sufficient_data(symbol)`` for the signal engine gate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from collections import deque
from typing import Any, Callable, Coroutine, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

_WS_FUTURES_URL = "wss://fstream.binance.com/stream"
_WS_SPOT_URL = "wss://stream.binance.com:9443/stream"
# Keep legacy alias for backward compatibility.
_WS_BASE_URL = _WS_FUTURES_URL
_MAX_STREAMS_PER_CONN = 200        # Binance hard limit
_STREAMS_PER_SYMBOL = 5            # kline_5m + kline_15m + kline_4h + kline_1d + miniTicker
_MAX_SYMBOLS_PER_CONN = _MAX_STREAMS_PER_CONN // _STREAMS_PER_SYMBOL  # 50

_BACKOFF_BASE = 1.0   # seconds
_BACKOFF_MAX = 60.0   # seconds
_STALE_THRESHOLD = 60.0  # seconds without any message → stream considered unhealthy

# Candle buffer sizes
_BUF_5M = 50
_BUF_4H = 30
_BUF_1D = 210  # 210 candles required for the 200-day SMA in the regime detector
_BUF_15M = 50
_BUF_1H = 50  # for spot market 1h candles

# Minimum candle counts required for signal engine
_MIN_5M = 3
_MIN_4H = 2
_MIN_1D = 20
_MIN_15M = 3

OnCandleClose = Callable[[str, str], Coroutine[Any, Any, None]]


class CandleBuffer:
    """Thread-safe ring buffer of OHLCV rows for a single symbol+timeframe."""

    def __init__(self, maxlen: int) -> None:
        self._buf: deque[list[float]] = deque(maxlen=maxlen)

    def append(self, ohlcv: list[float]) -> None:
        self._buf.append(ohlcv)

    def replace_last(self, ohlcv: list[float]) -> None:
        """Overwrite the last entry in-place (for in-progress candle updates)."""
        if self._buf:
            self._buf[-1] = ohlcv

    def last_open_time(self) -> float | None:
        """Return the open-time of the last entry, or None if the buffer is empty."""
        if self._buf:
            return self._buf[-1][0]
        return None

    def to_list(self) -> list[list[float]]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


class MarketDataStore:
    """Central in-memory store for all symbols' candles and live prices."""

    def __init__(self, market_type: str = "futures") -> None:
        self.market_type = market_type
        # {symbol: {timeframe: CandleBuffer}}
        self._candles: dict[str, dict[str, CandleBuffer]] = {}
        # {symbol: float}
        self._prices: dict[str, float] = {}
        self._lock = threading.Lock()

    def _ensure_buffers(self, symbol: str) -> None:
        if symbol not in self._candles:
            if self.market_type == "spot":
                self._candles[symbol] = {
                    "1h": CandleBuffer(_BUF_1H),
                    "4h": CandleBuffer(_BUF_4H),
                    "1d": CandleBuffer(_BUF_1D),
                }
            else:
                self._candles[symbol] = {
                    "5m": CandleBuffer(_BUF_5M),
                    "4h": CandleBuffer(_BUF_4H),
                    "1d": CandleBuffer(_BUF_1D),
                    "15m": CandleBuffer(_BUF_15M),
                }

    def update_candle(self, symbol: str, timeframe: str, ohlcv: list[float]) -> None:
        """Append (or overwrite) the latest OHLCV row for *symbol*/*timeframe*.

        If the incoming candle has the same open-time as the last entry in the
        buffer, the last entry is replaced in-place (in-progress candle update).
        Otherwise the row is appended as a new, closed candle.
        """
        with self._lock:
            self._ensure_buffers(symbol)
            tf = timeframe.lower()
            buf = self._candles[symbol].get(tf)
            if buf is None:
                return
            if buf.last_open_time() == ohlcv[0]:
                buf.replace_last(ohlcv)
            else:
                buf.append(ohlcv)

    def set_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self._prices[symbol] = price

    def get_price(self, symbol: str) -> Optional[float]:
        with self._lock:
            return self._prices.get(symbol)

    def get_candles(self, symbol: str, timeframe: str) -> list[list[float]]:
        """Return a snapshot of the candle buffer as a plain list."""
        with self._lock:
            sym = self._candles.get(symbol)
            if sym is None:
                return []
            buf = sym.get(timeframe.lower())
            if buf is None:
                return []
            return buf.to_list()

    def has_sufficient_data(self, symbol: str) -> bool:
        """Return True when all required timeframes have enough candles and a price."""
        with self._lock:
            if self._prices.get(symbol) is None:
                return False
            sym = self._candles.get(symbol)
            if sym is None:
                return False
            if self.market_type == "spot":
                return (
                    len(sym.get("1h", CandleBuffer(0))) >= 3
                    and len(sym.get("4h", CandleBuffer(0))) >= _MIN_4H
                    and len(sym.get("1d", CandleBuffer(0))) >= _MIN_1D
                )
            base_ok = (
                len(sym.get("5m", CandleBuffer(0))) >= _MIN_5M
                and len(sym.get("4h", CandleBuffer(0))) >= _MIN_4H
                and len(sym.get("1d", CandleBuffer(0))) >= _MIN_1D
            )
            # 15m: only check if buffer has been populated (backward compatible)
            buf_15m = sym.get("15m", CandleBuffer(0))
            fifteen_m_ok = len(buf_15m) == 0 or len(buf_15m) >= _MIN_15M
            return base_ok and fifteen_m_ok


def _build_stream_names(symbols: list[str], market_type: str = "futures") -> list[str]:
    """Return the list of Binance stream name strings for all *symbols*."""
    streams: list[str] = []
    for sym in symbols:
        lower = sym.lower() + "usdt"
        if market_type == "spot":
            streams.append(f"{lower}@kline_1h")
            streams.append(f"{lower}@kline_4h")
            streams.append(f"{lower}@kline_1d")
            streams.append(f"{lower}@miniTicker")
        else:
            streams.append(f"{lower}@kline_5m")
            streams.append(f"{lower}@kline_15m")
            streams.append(f"{lower}@kline_4h")
            streams.append(f"{lower}@kline_1d")
            streams.append(f"{lower}@miniTicker")
    return streams


def _chunk_streams(streams: list[str], chunk_size: int) -> list[list[str]]:
    """Split *streams* into chunks of at most *chunk_size* items."""
    return [streams[i : i + chunk_size] for i in range(0, len(streams), chunk_size)]


def _parse_kline(data: dict) -> tuple[str, str, list[float], bool]:
    """
    Parse a kline event dict into (base_symbol, timeframe, ohlcv, closed).

    ``data`` is the inner ``data`` object from the combined stream message.
    """
    k = data["k"]
    raw_sym: str = data["s"]  # e.g. "BTCUSDT"
    base = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
    timeframe: str = k["i"]  # "5m" or "4h"
    ohlcv = [
        float(k["t"]),   # open time (ms)
        float(k["o"]),   # open
        float(k["h"]),   # high
        float(k["l"]),   # low
        float(k["c"]),   # close
        float(k["v"]),   # volume
    ]
    closed: bool = bool(k["x"])
    return base, timeframe, ohlcv, closed


def _parse_mini_ticker(data: dict) -> tuple[str, float]:
    """Parse a miniTicker event into (base_symbol, price)."""
    raw_sym: str = data["s"]
    base = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
    price = float(data["c"])
    return base, price


class WebSocketManager:
    """Manages multiple Binance combined-stream WebSocket connections."""

    def __init__(self, store: MarketDataStore, market_type: str = "futures") -> None:
        self._store = store
        self._market_type = market_type
        self._ws_url = _WS_SPOT_URL if market_type == "spot" else _WS_FUTURES_URL
        self._on_candle_close: Optional[OnCandleClose] = None
        self._symbols: list[str] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False
        # Health tracking — updated on every received message
        self.last_message_at: float = 0.0
        self.is_connected: bool = False

    def is_healthy(self) -> bool:
        """Return True when the stream is connected and recently active."""
        if not self.is_connected:
            return False
        if self.last_message_at == 0.0:
            return False
        return (time.monotonic() - self.last_message_at) < _STALE_THRESHOLD

    async def start(
        self,
        symbols: list[str],
        on_candle_close: OnCandleClose,
    ) -> None:
        """Connect to Binance streams and start processing events."""
        self._symbols = list(symbols)
        self._on_candle_close = on_candle_close
        self._running = True

        all_streams = _build_stream_names(self._symbols, self._market_type)
        chunks = _chunk_streams(all_streams, _MAX_STREAMS_PER_CONN)

        logger.info(
            "WebSocketManager(%s): starting %d connection(s) for %d symbols (%d streams total).",
            self._market_type,
            len(chunks),
            len(self._symbols),
            len(all_streams),
        )

        for idx, chunk in enumerate(chunks):
            task = asyncio.create_task(
                self._connection_loop(idx, chunk),
                name=f"ws_{self._market_type}_conn_{idx}",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        """Cancel all WebSocket connection tasks."""
        self._running = False
        self.is_connected = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("WebSocketManager stopped.")

    async def _connection_loop(self, conn_idx: int, streams: list[str]) -> None:
        """Persistent loop for a single WebSocket connection with back-off reconnects."""
        attempt = 0
        while self._running:
            url = f"{self._ws_url}?streams={'/'.join(streams)}"
            try:
                logger.info("WS[%d][%s] connecting (%d streams)…", conn_idx, self._market_type, len(streams))
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=30,
                    close_timeout=10,
                ) as ws:
                    attempt = 0  # reset back-off on successful connection
                    self.is_connected = True
                    logger.info("WS[%d][%s] connected.", conn_idx, self._market_type)
                    await self._receive_loop(conn_idx, ws)
            except asyncio.CancelledError:
                logger.info("WS[%d][%s] cancelled.", conn_idx, self._market_type)
                self.is_connected = False
                return
            except ConnectionClosed as exc:
                logger.warning("WS[%d][%s] connection closed: %s", conn_idx, self._market_type, exc)
                self.is_connected = False
            except Exception as exc:
                logger.error("WS[%d][%s] unexpected error: %s", conn_idx, self._market_type, exc)
                self.is_connected = False

            if not self._running:
                return

            attempt += 1
            # Exponential back-off with full jitter to avoid thundering-herd
            cap = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_MAX)
            delay = random.uniform(0, cap)
            logger.info(
                "WS[%d][%s] reconnecting in %.1fs (attempt %d)…",
                conn_idx,
                self._market_type,
                delay,
                attempt,
            )
            await asyncio.sleep(delay)

    async def _receive_loop(self, conn_idx: int, ws) -> None:
        """Process incoming messages from a WebSocket connection."""
        async for raw in ws:
            if not self._running:
                return
            try:
                msg = json.loads(raw)
                self.last_message_at = time.monotonic()
                await self._handle_message(msg)
            except Exception as exc:
                logger.debug("WS[%d] message parse error: %s", conn_idx, exc)

    async def _handle_message(self, msg: dict) -> None:
        """Dispatch a single combined-stream message to the correct handler."""
        data = msg.get("data", {})
        event_type = data.get("e")

        if event_type == "kline":
            base, timeframe, ohlcv, closed = _parse_kline(data)
            # Always update the buffer with the latest bar
            self._store.update_candle(base, timeframe, ohlcv)
            # Futures: fire callback on 5m close; Spot: fire callback on 1h close
            trigger_tf = "1h" if self._market_type == "spot" else "5m"
            if closed and timeframe == trigger_tf and self._on_candle_close is not None:
                try:
                    await self._on_candle_close(base, timeframe)
                except Exception as exc:
                    logger.error("on_candle_close(%s) error: %s", base, exc)

        elif event_type == "24hrMiniTicker":
            base, price = _parse_mini_ticker(data)
            self._store.set_price(base, price)
