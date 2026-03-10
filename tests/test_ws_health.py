"""
Tests for WebSocket multi-connection health tracking in bot/ws_manager.py
"""
from __future__ import annotations

import time

import pytest

from bot.ws_manager import (
    _STALE_THRESHOLD,
    MarketDataStore,
    WebSocketManager,
)


def _make_mgr() -> WebSocketManager:
    return WebSocketManager(store=MarketDataStore())


class TestMultiConnectionHealth:
    def test_empty_health_dict_returns_false(self):
        mgr = _make_mgr()
        assert mgr._connection_health == {}
        # Legacy path: is_connected=False
        assert mgr.is_healthy() is False

    def test_single_healthy_connection(self):
        mgr = _make_mgr()
        mgr._connection_health[0] = time.monotonic() - 10  # 10s ago — still fresh
        assert mgr.is_healthy() is True

    def test_single_stale_connection(self):
        mgr = _make_mgr()
        mgr._connection_health[0] = time.monotonic() - (_STALE_THRESHOLD + 5)
        assert mgr.is_healthy() is False

    def test_mixed_connections_one_healthy(self):
        """If at least one connection is healthy the manager is healthy."""
        mgr = _make_mgr()
        mgr._connection_health[0] = time.monotonic() - (_STALE_THRESHOLD + 5)  # stale
        mgr._connection_health[1] = time.monotonic() - 5  # fresh
        assert mgr.is_healthy() is True

    def test_all_stale_connections_unhealthy(self):
        mgr = _make_mgr()
        for i in range(3):
            mgr._connection_health[i] = time.monotonic() - (_STALE_THRESHOLD + 10)
        assert mgr.is_healthy() is False

    def test_connection_health_cleared_on_stop(self):
        """stop() must clear the per-connection health dict."""
        import asyncio

        mgr = _make_mgr()
        mgr._connection_health[0] = time.monotonic()
        mgr._running = False
        asyncio.run(mgr.stop())
        assert mgr._connection_health == {}

    def test_per_connection_tracking_independent(self):
        """Each connection index tracks its own last message time."""
        mgr = _make_mgr()
        t0 = time.monotonic() - 5
        t1 = time.monotonic() - 30
        mgr._connection_health[0] = t0
        mgr._connection_health[1] = t1
        assert mgr._connection_health[0] == pytest.approx(t0)
        assert mgr._connection_health[1] == pytest.approx(t1)

    def test_legacy_fallback_when_health_dict_empty(self):
        """is_healthy() falls back to last_message_at when dict is empty."""
        mgr = _make_mgr()
        mgr.is_connected = True
        mgr.last_message_at = time.monotonic() - 5
        # With empty dict, should fall through to legacy path
        assert mgr.is_healthy() is True

    def test_legacy_fallback_no_message(self):
        mgr = _make_mgr()
        mgr.is_connected = True
        mgr.last_message_at = 0.0
        assert mgr.is_healthy() is False

    def test_legacy_fallback_not_connected(self):
        mgr = _make_mgr()
        mgr.is_connected = False
        mgr.last_message_at = time.monotonic() - 1
        assert mgr.is_healthy() is False
