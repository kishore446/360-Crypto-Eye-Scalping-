"""
Tests for websocket-first scanning, health tracking, and fallback polling.

Covers:
- WebSocketManager.is_healthy() logic (connected flag + stale threshold)
- on_candle_close() gate: auto_scan_active disabled → no signal
- on_candle_close() gate: news_freeze → no signal
- on_candle_close() gate: risk cap → no signal
- on_candle_close() gate: symbol already active → no signal
- on_candle_close() gate: insufficient data → no signal
- on_candle_close() produces signal when all gates pass (mocked)
- _run_fallback_scan_job is no-op when WS healthy
- _run_fallback_scan_job is no-op when auto_scan_active False
- _run_fallback_scan_job runs when WS unhealthy and auto_scan active
"""
from __future__ import annotations

import time
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from bot.ws_manager import _STALE_THRESHOLD, MarketDataStore, WebSocketManager

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ws_manager(*, connected: bool = True, last_msg_offset: float = 0.0) -> WebSocketManager:
    """Return a WebSocketManager with synthetic health state."""
    store = MarketDataStore()
    mgr = WebSocketManager(store=store)
    mgr.is_connected = connected
    mgr.last_message_at = time.monotonic() - last_msg_offset if connected else 0.0
    return mgr


def _make_sufficient_store(base: str = "BTC") -> MarketDataStore:
    """Return a MarketDataStore pre-filled with enough candle data for *base*."""
    store = MarketDataStore()
    for i in range(50):
        store.update_candle(base, "5m", [float(i * 300_000), 1.0, 2.0, 0.5, 1.5, 100.0])
    for i in range(30):
        store.update_candle(base, "4h", [float(i * 14_400_000), 1.0, 2.0, 0.5, 1.5, 100.0])
    for i in range(30):
        store.update_candle(base, "1d", [float(i * 86_400_000), 1.0, 2.0, 0.5, 1.5, 100.0])
    store.set_price(base, 1.5)
    return store


# ── WebSocketManager.is_healthy() ────────────────────────────────────────────

class TestWebSocketManagerHealth:
    def test_healthy_when_connected_and_recent_message(self):
        mgr = _make_ws_manager(connected=True, last_msg_offset=5.0)
        assert mgr.is_healthy() is True

    def test_unhealthy_when_not_connected(self):
        mgr = _make_ws_manager(connected=False)
        assert mgr.is_healthy() is False

    def test_unhealthy_when_no_message_ever(self):
        mgr = _make_ws_manager(connected=True, last_msg_offset=0.0)
        mgr.last_message_at = 0.0  # never received anything
        assert mgr.is_healthy() is False

    def test_unhealthy_when_message_too_old(self):
        mgr = _make_ws_manager(connected=True, last_msg_offset=_STALE_THRESHOLD + 1)
        assert mgr.is_healthy() is False

    def test_boundary_just_within_threshold(self):
        mgr = _make_ws_manager(connected=True, last_msg_offset=_STALE_THRESHOLD - 1)
        assert mgr.is_healthy() is True

    def test_is_connected_set_false_on_stop(self):
        """stop() marks the manager as disconnected."""
        import asyncio
        store = MarketDataStore()
        mgr = WebSocketManager(store=store)
        mgr.is_connected = True
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(mgr.stop())
        finally:
            loop.close()
        assert mgr.is_connected is False

    def test_last_message_at_updated_on_receive(self):
        """last_message_at advances after _handle_message is called."""
        import asyncio
        store = MarketDataStore()
        mgr = WebSocketManager(store=store)
        before = mgr.last_message_at

        msg = {
            "data": {
                "e": "24hrMiniTicker",
                "s": "BTCUSDT",
                "c": "50000.0",
            }
        }
        # Simulate the receive_loop updating last_message_at
        original_handle = mgr._handle_message

        async def _fake_receive() -> None:
            mgr.last_message_at = time.monotonic()
            await original_handle(msg)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_fake_receive())
        finally:
            loop.close()
        assert mgr.last_message_at > before


# ── on_candle_close gates ─────────────────────────────────────────────────────

class TestOnCandleCloseGates:
    """Unit tests for the on_candle_close callback gate conditions."""

    def _run(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @pytest.fixture(autouse=True)
    def _patch_bot_globals(self, monkeypatch):
        """Patch module-level globals in bot.bot for isolation."""
        import bot.bot as _bot
        import bot.state as _state_mod

        # Reset BotState singleton so we get a fresh one per test
        _state_mod.BotState._instance = None
        self._bot_state = _state_mod.BotState()
        self._bot_state.auto_scan_active = True
        self._bot_state.news_freeze = False

        monkeypatch.setattr(_bot, "_bot_state", self._bot_state)

        self._store = _make_sufficient_store("BTC")
        monkeypatch.setattr(_bot, "market_data", self._store)

        self._risk = MagicMock()
        self._risk.active_signals = []
        self._risk.can_open_signal.return_value = True
        monkeypatch.setattr(_bot, "risk_manager", self._risk)

        self._news_cal = MagicMock()
        self._news_cal.is_high_impact_imminent.return_value = False
        monkeypatch.setattr(_bot, "news_calendar", self._news_cal)

        # Mock signal_tracker so check_signal doesn't fail on MagicMock signals
        self._signal_tracker = MagicMock()
        self._signal_tracker.check_signal.return_value = []
        monkeypatch.setattr(_bot, "signal_tracker", self._signal_tracker)

        monkeypatch.setattr(_bot, "TELEGRAM_BOT_TOKEN", "fake_token")
        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", -1)

        # Mock signal_router so dedup/channel checks don't interfere
        self._signal_router = MagicMock()
        self._signal_router.should_suppress_duplicate.return_value = False
        self._signal_router.is_channel_enabled.return_value = False  # disable CH2/CH3/CH4/CH5
        self._signal_router.get_channel_id.return_value = -1
        monkeypatch.setattr(_bot, "signal_router", self._signal_router)

        yield

        # Restore singleton
        _state_mod.BotState._instance = None

    def test_gate_auto_scan_inactive(self):
        """on_candle_close is a no-op when auto_scan_active is False."""
        import bot.bot as _bot
        self._bot_state.auto_scan_active = False

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_gate_news_freeze(self):
        """on_candle_close is a no-op when news_freeze is active."""
        import bot.bot as _bot
        self._bot_state.news_freeze = True

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_gate_high_impact_news_imminent(self):
        """on_candle_close is a no-op when a high-impact news event is imminent."""
        import bot.bot as _bot
        self._news_cal.is_high_impact_imminent.return_value = True

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_gate_symbol_already_active(self):
        """on_candle_close skips when the symbol already has an active signal."""
        import bot.bot as _bot

        active_sig = MagicMock()
        active_sig.result.symbol = "BTC"
        self._risk.active_signals = [active_sig]

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_gate_insufficient_data(self, monkeypatch):
        """on_candle_close skips when market data store lacks sufficient candles."""
        import bot.bot as _bot

        empty_store = MarketDataStore()  # no candles
        monkeypatch.setattr(_bot, "market_data", empty_store)

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_gate_risk_cap_stops_all_sides(self):
        """on_candle_close generates no signal when risk cap blocks all sides."""
        import bot.bot as _bot
        self._risk.can_open_signal.return_value = False

        with patch("bot.bot.run_confluence_check") as mock_conf:
            self._run(_bot.on_candle_close("BTC", "5m"))
            mock_conf.assert_not_called()

    def test_signal_generated_when_all_gates_pass(self, monkeypatch):
        """on_candle_close broadcasts a signal when all gates pass and confluence succeeds."""
        import bot.bot as _bot
        from bot.signal_engine import Side as _Side
        from bot.signal_engine import SignalResult

        fake_result = MagicMock(spec=SignalResult)
        fake_result.confidence = MagicMock()
        fake_result.confidence.value = "High"
        fake_result.format_message.return_value = "signal text"
        fake_result.side = _Side.LONG

        # Patch scalping.run to return our fake result (CH1 path)
        with patch("bot.channels.scalping.run", return_value=fake_result):
            self._run(_bot.on_candle_close("BTC", "5m"))

        self._risk.add_signal.assert_called_once_with(fake_result, origin_channel=ANY, created_regime=ANY)

    def test_one_signal_per_candle_close(self):
        """on_candle_close stops after the first successful CH1 signal (break after first hit)."""
        import bot.bot as _bot
        from bot.signal_engine import Side as _Side
        from bot.signal_engine import SignalResult

        fake_result = MagicMock(spec=SignalResult)
        fake_result.confidence = MagicMock()
        fake_result.confidence.value = "High"
        fake_result.format_message.return_value = "signal text"
        fake_result.side = _Side.LONG

        call_count = 0

        def _scalping_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return fake_result  # always succeeds

        with patch("bot.channels.scalping.run", side_effect=_scalping_run):
            self._run(_bot.on_candle_close("BTC", "5m"))

        # Should stop after the first side (LONG) succeeds
        assert call_count == 1


# ── Fallback polling ──────────────────────────────────────────────────────────

class TestFallbackScanJob:
    """Tests for _run_fallback_scan_job no-op / active conditions."""

    @pytest.fixture(autouse=True)
    def _patch_bot_globals(self, monkeypatch):
        import bot.bot as _bot
        import bot.state as _state_mod

        _state_mod.BotState._instance = None
        self._bot_state = _state_mod.BotState()
        self._bot_state.auto_scan_active = True
        self._bot_state.news_freeze = False

        monkeypatch.setattr(_bot, "_bot_state", self._bot_state)
        monkeypatch.setattr(_bot, "_dynamic_pairs", ["BTC"])

        self._store = _make_sufficient_store("BTC")
        monkeypatch.setattr(_bot, "market_data", self._store)

        self._risk = MagicMock()
        self._risk.active_signals = []
        self._risk.can_open_signal.return_value = True
        monkeypatch.setattr(_bot, "risk_manager", self._risk)

        self._news_cal = MagicMock()
        self._news_cal.is_high_impact_imminent.return_value = False
        monkeypatch.setattr(_bot, "news_calendar", self._news_cal)

        monkeypatch.setattr(_bot, "TELEGRAM_BOT_TOKEN", "fake_token")
        monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", -1)

        # Mock signal_router so dedup/channel checks don't interfere
        self._signal_router = MagicMock()
        self._signal_router.should_suppress_duplicate.return_value = False
        self._signal_router.is_channel_enabled.return_value = False  # disable CH2/CH3/CH4/CH5
        self._signal_router.get_channel_id.return_value = -1
        monkeypatch.setattr(_bot, "signal_router", self._signal_router)

        # Mock the resilient exchange to avoid real REST calls in tests
        self._mock_exchange = MagicMock()
        self._mock_exchange.fetch_ohlcv.return_value = []
        self._mock_exchange.fetch_ticker.return_value = {"last": "1.5"}
        monkeypatch.setattr(_bot, "_resilient_exchange", self._mock_exchange)

        yield

        _state_mod.BotState._instance = None

    def test_no_op_when_ws_healthy(self, monkeypatch):
        """Fallback job does nothing while WebSocket is healthy."""
        import bot.bot as _bot

        healthy_mgr = _make_ws_manager(connected=True, last_msg_offset=5.0)
        monkeypatch.setattr(_bot, "ws_manager", healthy_mgr)

        with patch("bot.bot.run_confluence_check") as mock_conf:
            _bot._run_fallback_scan_job()
            mock_conf.assert_not_called()

    def test_no_op_when_auto_scan_inactive(self, monkeypatch):
        """Fallback job does nothing when auto_scan_active is False."""
        import bot.bot as _bot

        unhealthy_mgr = _make_ws_manager(connected=False)
        monkeypatch.setattr(_bot, "ws_manager", unhealthy_mgr)
        self._bot_state.auto_scan_active = False

        with patch("bot.bot.run_confluence_check") as mock_conf:
            _bot._run_fallback_scan_job()
            mock_conf.assert_not_called()

    def test_activates_when_ws_unhealthy(self, monkeypatch):
        """Fallback job runs scalping.run when WebSocket is unhealthy."""
        import bot.bot as _bot

        unhealthy_mgr = _make_ws_manager(connected=False)
        monkeypatch.setattr(_bot, "ws_manager", unhealthy_mgr)

        with patch("bot.channels.scalping.run", return_value=None) as mock_hard:
            _bot._run_fallback_scan_job()
            assert mock_hard.called

    def test_activates_when_ws_stale(self, monkeypatch):
        """Fallback job runs when stream is connected but messages are stale."""
        import bot.bot as _bot

        stale_mgr = _make_ws_manager(connected=True, last_msg_offset=_STALE_THRESHOLD + 10)
        monkeypatch.setattr(_bot, "ws_manager", stale_mgr)

        with patch("bot.channels.scalping.run", return_value=None) as mock_hard:
            _bot._run_fallback_scan_job()
            assert mock_hard.called

    def test_no_duplicate_signal_skips_active_symbol(self, monkeypatch):
        """Fallback scan skips symbols that already have active signals."""
        import bot.bot as _bot

        unhealthy_mgr = _make_ws_manager(connected=False)
        monkeypatch.setattr(_bot, "ws_manager", unhealthy_mgr)

        active_sig = MagicMock()
        active_sig.result.symbol = "BTC"
        self._risk.active_signals = [active_sig]

        with patch("bot.bot.run_confluence_check") as mock_conf:
            _bot._run_fallback_scan_job()
            mock_conf.assert_not_called()

    def test_fallback_signal_broadcast(self, monkeypatch):
        """Fallback scan broadcasts signal when scalping gate passes."""
        import bot.bot as _bot
        from bot.signal_engine import Side as _Side
        from bot.signal_engine import SignalResult

        unhealthy_mgr = _make_ws_manager(connected=False)
        monkeypatch.setattr(_bot, "ws_manager", unhealthy_mgr)

        fake_result = MagicMock(spec=SignalResult)
        fake_result.confidence = MagicMock()
        fake_result.confidence.value = "High"
        fake_result.format_message.return_value = "fallback signal"
        fake_result.side = _Side.LONG

        with patch("bot.channels.scalping.run", return_value=fake_result):
            with patch("bot.bot._broadcast_to_channel", new_callable=AsyncMock):
                _bot._run_fallback_scan_job()

        self._risk.add_signal.assert_called_once_with(fake_result, origin_channel=ANY, created_regime=ANY)


# ── MarketDataStore thread-safety ────────────────────────────────────────────

class TestMarketDataStoreThreadSafety:
    """Regression tests for the Lock→RLock and _ensure_buffers race-condition fixes."""

    def test_uses_rlock(self):
        """Regression: _lock must be a RLock (reentrant) to prevent deadlock on re-entry."""
        import threading
        store = MarketDataStore()
        assert isinstance(store._lock, type(threading.RLock())), (
            "MarketDataStore._lock must be threading.RLock(), not Lock()"
        )

    def test_ensure_buffers_is_idempotent(self):
        """Regression: calling _ensure_buffers twice must not overwrite existing buffer data."""
        store = MarketDataStore()
        store.update_candle("BTC", "5m", [1.0, 2.0, 3.0, 0.5, 2.5, 100.0])
        buf_before = store._candles["BTC"]["5m"]
        # Calling _ensure_buffers again with the lock held (simulates re-entry)
        with store._lock:
            store._ensure_buffers("BTC")
        assert store._candles["BTC"]["5m"] is buf_before, (
            "_ensure_buffers must not overwrite existing buffers (setdefault semantics)"
        )

    def test_concurrent_update_candle_no_exception(self):
        """Regression: concurrent update_candle calls from multiple threads must not raise."""
        import threading
        store = MarketDataStore()
        errors: list[Exception] = []

        def worker(symbol: str) -> None:
            try:
                for i in range(50):
                    store.update_candle(symbol, "5m", [float(i), 1.0, 2.0, 0.5, 1.5, 100.0])
            except Exception as exc:
                errors.append(exc)

        symbols = [f"SYM{i}" for i in range(10)]
        threads = [threading.Thread(target=worker, args=(s,)) for s in symbols]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent updates raised exceptions: {errors}"
