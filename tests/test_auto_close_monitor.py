"""Tests for AutoCloseMonitor — TP/SL hit detection, stale close, outcome recording."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.auto_close_monitor import AutoCloseMonitor, CloseResult, _duration_str
from bot.signal_engine import Confidence, Side, SignalResult


def _make_signal_result(
    symbol: str = "BTC",
    side: Side = Side.LONG,
    entry_low: float = 100.0,
    entry_high: float = 102.0,
    tp1: float = 110.0,
    tp2: float = 115.0,
    tp3: float = 120.0,
    stop_loss: float = 95.0,
) -> SignalResult:
    return SignalResult(
        symbol=symbol,
        side=side,
        confidence=Confidence.HIGH,
        entry_low=entry_low,
        entry_high=entry_high,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        stop_loss=stop_loss,
        structure_note="Order Block",
        context_note="4H bullish bias",
        leverage_min=10,
        leverage_max=20,
        signal_id="test-id-1",
    )


def _make_active_signal(result: SignalResult, be_triggered: bool = False, origin_channel: int = 0) -> MagicMock:
    sig = MagicMock()
    sig.result = result
    sig.entry_mid = (result.entry_low + result.entry_high) / 2
    sig.opened_at = time.time() - 3600
    sig.be_triggered = be_triggered
    sig.is_stale.return_value = False
    sig.origin_channel = origin_channel
    return sig


@pytest.fixture()
def monitor(tmp_path) -> AutoCloseMonitor:
    risk_manager = MagicMock()
    dashboard = MagicMock()
    cooldown = MagicMock()
    cooldown.is_cooldown_active.return_value = False
    market_data = MagicMock()
    router = MagicMock()
    router.get_channel_id.return_value = 0
    router.get_tier_for_channel_id.return_value = None
    return AutoCloseMonitor(
        signal_tracker=risk_manager,
        dashboard=dashboard,
        cooldown_manager=cooldown,
        market_data_store=market_data,
        signal_router=router,
    )


# ── TP hit detection ─────────────────────────────────────────────────────────

class TestCheckTpSlHit:
    def test_long_tp1_hit(self, monitor):
        result = _make_signal_result()
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=110.5)
        assert close is not None
        assert close.outcome == "TP1"
        assert close.pnl_pct > 0

    def test_long_tp2_hit(self, monitor):
        """When price hits TP2 directly, TP1 is returned first (sequential tracking)."""
        result = _make_signal_result()
        signal = _make_active_signal(result)
        # First call at TP2-level price: should return TP1 first (BUG #3 fix)
        close1 = monitor._check_tp_sl_hit(signal, current_price=115.5)
        assert close1 is not None
        assert close1.outcome == "TP1"
        # Second call (TP1 already recorded): should now return TP2
        close2 = monitor._check_tp_sl_hit(signal, current_price=115.5)
        assert close2 is not None
        assert close2.outcome == "TP2"

    def test_long_tp3_hit(self, monitor):
        """When price hits TP3 directly, TP1 then TP2 then TP3 are returned sequentially."""
        result = _make_signal_result()
        signal = _make_active_signal(result)
        close1 = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close1 is not None
        assert close1.outcome == "TP1"
        close2 = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close2 is not None
        assert close2.outcome == "TP2"
        close3 = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close3 is not None
        assert close3.outcome == "TP3"

    def test_long_sl_hit(self, monitor):
        result = _make_signal_result()
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=94.0)
        assert close is not None
        assert close.outcome == "SL"
        assert close.pnl_pct < 0

    def test_short_tp1_hit(self, monitor):
        result = _make_signal_result(
            side=Side.SHORT,
            entry_low=100.0, entry_high=102.0,
            tp1=92.0, tp2=88.0, tp3=84.0,
            stop_loss=107.0,
        )
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=91.5)
        assert close is not None
        assert close.outcome == "TP1"

    def test_short_sl_hit(self, monitor):
        result = _make_signal_result(
            side=Side.SHORT,
            entry_low=100.0, entry_high=102.0,
            tp1=92.0, tp2=88.0, tp3=84.0,
            stop_loss=107.0,
        )
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=108.0)
        assert close is not None
        assert close.outcome == "SL"

    def test_no_hit_mid_price(self, monitor):
        result = _make_signal_result()
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=105.0)
        assert close is None

    def test_be_triggered_sl_at_entry(self, monitor):
        """After BE triggered, SL should be at entry (not original stop_loss)."""
        result = _make_signal_result(stop_loss=95.0)
        signal = _make_active_signal(result, be_triggered=True)
        # Price drops just below entry (101) but above original SL (95)
        close = monitor._check_tp_sl_hit(signal, current_price=99.0)
        assert close is not None
        assert close.outcome == "SL"


# ── Stale close ──────────────────────────────────────────────────────────────

class TestStaleClose:
    def test_stale_result_has_zero_pnl(self, monitor):
        result = _make_signal_result()
        signal = _make_active_signal(result)
        signal.opened_at = time.time() - 20 * 3600  # 20h ago
        close = monitor._build_stale_result(signal)
        assert close.outcome == "STALE"
        assert close.pnl_pct == 0.0

    def test_stale_result_symbol(self, monitor):
        result = _make_signal_result(symbol="ETH")
        signal = _make_active_signal(result)
        close = monitor._build_stale_result(signal)
        assert close.symbol == "ETH"


# ── Format close message ─────────────────────────────────────────────────────

class TestFormatCloseMessage:
    def _make_result(self, outcome: str = "TP2", pnl: float = 2.5) -> CloseResult:
        return CloseResult(
            signal_id="x",
            symbol="BTC",
            side="LONG",
            outcome=outcome,
            entry_price=100.0,
            exit_price=102.5,
            pnl_pct=pnl,
            opened_at=time.time() - 3600,
            closed_at=time.time(),
            channel_tier="CH1_HARD",
        )

    def test_tp2_message_contains_outcome(self):
        r = self._make_result("TP2", 2.5)
        msg = AutoCloseMonitor._format_close_message(r)
        assert "TP2 HIT" in msg
        assert "BTC" in msg
        assert "LONG" in msg

    def test_sl_message_shows_loss(self):
        r = self._make_result("SL", -1.0)
        msg = AutoCloseMonitor._format_close_message(r)
        assert "SL HIT" in msg

    def test_stale_message(self):
        r = self._make_result("STALE", 0.0)
        msg = AutoCloseMonitor._format_close_message(r)
        assert "STALE" in msg

    def test_channel_label_shown(self):
        r = self._make_result("TP1", 1.5)
        msg = AutoCloseMonitor._format_close_message(r)
        assert "CH1" in msg


# ── Duration formatting ──────────────────────────────────────────────────────

class TestDurationStr:
    def test_hours_and_minutes(self):
        assert _duration_str(6120) == "1h 42m"

    def test_minutes_only(self):
        assert _duration_str(600) == "10m"

    def test_zero(self):
        assert _duration_str(0) == "0m"


# ── Process close (integration with mocks) ───────────────────────────────────

@pytest.mark.asyncio
async def test_process_close_records_dashboard(monitor):
    result = _make_signal_result()
    signal = _make_active_signal(result)

    close_result = CloseResult(
        signal_id="x",
        symbol="BTC",
        side="LONG",
        outcome="TP2",
        entry_price=101.0,
        exit_price=115.0,
        pnl_pct=13.86,
        opened_at=time.time() - 3600,
        closed_at=time.time(),
    )

    with patch.object(monitor, "_broadcast_close", new=AsyncMock()):
        await monitor._process_close(signal, close_result)

    monitor._dashboard.record_result.assert_called_once()
    call_args = monitor._dashboard.record_result.call_args[0][0]
    assert call_args.outcome == "WIN"
    assert call_args.symbol == "BTC"
    monitor._cooldown.record_outcome.assert_called_once_with("WIN")
    monitor._risk_manager.close_signal.assert_called_once_with("BTC", reason="tp2")


# ── Invalidation deduplication ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalidation_alert_sent_only_once(monitor):
    """Same signal must not receive more than one invalidation alert per open lifecycle."""
    result = _make_signal_result()
    signal = _make_active_signal(result)

    broadcast_calls: list[str] = []

    async def fake_broadcast(msg: str, channel_id: int = 0) -> None:
        broadcast_calls.append(msg)

    monitor._market_data.get_candles.return_value = []

    with patch.object(monitor, "_broadcast_close_raw", side_effect=fake_broadcast):
        with patch("bot.invalidation_detector.InvalidationDetector") as mock_detector_cls:
            instance = MagicMock()
            instance.check_invalidation.return_value = "OB breach"
            instance.format_alert.return_value = "⚠️ INVALIDATION"
            mock_detector_cls.return_value = instance

            with patch("config.INVALIDATION_CHECK_ENABLED", True):
                # Simulate three consecutive poll ticks
                for _ in range(3):
                    await monitor._check_invalidation(signal, current_price=99.0)

    assert len(broadcast_calls) == 1, (
        f"Expected 1 invalidation alert but got {len(broadcast_calls)}"
    )


@pytest.mark.asyncio
async def test_broadcast_close_raw_sends_plain_text(monitor):
    """Regression: _broadcast_close_raw must NOT use parse_mode to avoid Markdown entity errors."""
    sent_kwargs: dict[str, Any] = {}

    async def fake_send_message(**kwargs):
        sent_kwargs.update(kwargs)

    mock_bot_instance = MagicMock()
    mock_bot_instance.send_message = AsyncMock(side_effect=fake_send_message)

    monitor._router.get_channel_id.return_value = 12345

    with (
        patch("telegram.Bot", return_value=mock_bot_instance),
        patch("config.TELEGRAM_BOT_TOKEN", "fake-token"),
    ):
        await monitor._broadcast_close_raw("⚠️ SIGNAL INVALIDATION — BTC/USDT LONG\nReason: OB Breach")

    mock_bot_instance.send_message.assert_called_once()
    assert "parse_mode" not in sent_kwargs, (
        "_broadcast_close_raw must not pass parse_mode (causes Telegram Markdown entity errors)"
    )
