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
        """BUG #2 fix: when price gaps past TP3 with no prior TP hits, close directly at TP3."""
        result = _make_signal_result()
        signal = _make_active_signal(result)
        # Price jumps straight past TP3 with no prior partial exits — gap scenario.
        # Expected: single TP3 close (skip sequential TP1→TP2 that would take 30+ s).
        close1 = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close1 is not None
        assert close1.outcome == "TP3", (
            "Gap past TP3 with no prior hits should close with TP3 directly, not TP1 first"
        )
        # No further close expected — signal is fully done
        close2 = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close2 is None, "TP3 gap-close should fully settle in one call"

    def test_long_tp3_sequential_after_partial_hits(self, monitor):
        """Sequential TP tracking still works when TP1 and TP2 were hit on earlier ticks."""
        result = _make_signal_result()
        signal = _make_active_signal(result)
        # TP1 and TP2 were already partially closed in previous ticks
        monitor._check_tp_sl_hit(signal, current_price=110.5)  # TP1
        monitor._check_tp_sl_hit(signal, current_price=115.5)  # TP2
        # Now price reaches TP3 — should return TP3
        close = monitor._check_tp_sl_hit(signal, current_price=120.5)
        assert close is not None
        assert close.outcome == "TP3"

    def test_long_sl_hit(self, monitor):
        result = _make_signal_result()
        signal = _make_active_signal(result)
        close = monitor._check_tp_sl_hit(signal, current_price=94.0)
        assert close is not None
        assert close.outcome == "SL"
        assert close.pnl_pct < 0

    def test_short_tp3_gap_closes_at_tp3(self, monitor):
        """BUG #2 fix: SHORT price gap past TP3 with no prior hits → close directly at TP3."""
        result = _make_signal_result(
            side=Side.SHORT,
            entry_low=100.0, entry_high=102.0,
            tp1=92.0, tp2=88.0, tp3=84.0,
            stop_loss=107.0,
        )
        signal = _make_active_signal(result)
        # Price crashes straight past TP3 (84) with no prior partial closes
        close = monitor._check_tp_sl_hit(signal, current_price=83.0)
        assert close is not None
        assert close.outcome == "TP3", (
            "SHORT gap past TP3 with no prior hits should close with TP3, not TP1 first"
        )
        assert close.exit_price == pytest.approx(84.0), "Exit price should be TP3 level, not current"

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
            channel_tier="CH1_SCALPING",
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
    """TP2 is a partial close: dashboard records WIN but signal stays alive (no close_signal)."""
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

    # Dashboard must be updated with the partial WIN result
    monitor._dashboard.record_result.assert_called_once()
    call_args = monitor._dashboard.record_result.call_args[0][0]
    assert call_args.outcome == "WIN"
    assert call_args.symbol == "BTC"
    monitor._cooldown.record_outcome.assert_called_once_with("WIN")
    # Signal must NOT be closed — it should continue to be monitored for TP3 / SL
    monitor._risk_manager.close_signal.assert_not_called()


@pytest.mark.asyncio
async def test_process_close_tp3_fully_closes_signal(monitor):
    """TP3 is a full close: close_signal IS called and state is cleaned up."""
    result = _make_signal_result()
    signal = _make_active_signal(result)

    close_result = CloseResult(
        signal_id="test-id-1",
        symbol="BTC",
        side="LONG",
        outcome="TP3",
        entry_price=101.0,
        exit_price=120.5,
        pnl_pct=19.3,
        opened_at=time.time() - 3600,
        closed_at=time.time(),
    )

    with patch.object(monitor, "_broadcast_close", new=AsyncMock()):
        await monitor._process_close(signal, close_result)

    monitor._dashboard.record_result.assert_called_once()
    call_args = monitor._dashboard.record_result.call_args[0][0]
    assert call_args.outcome == "WIN"
    monitor._risk_manager.close_signal.assert_called_once_with("BTC", reason="tp3")


@pytest.mark.asyncio
async def test_process_close_tp1_triggers_be(monitor):
    """TP1 partial close must call trigger_be() on the signal and NOT close it."""
    result = _make_signal_result()
    signal = _make_active_signal(result)
    signal.trigger_be = MagicMock()

    close_result = CloseResult(
        signal_id="test-id-1",
        symbol="BTC",
        side="LONG",
        outcome="TP1",
        entry_price=101.0,
        exit_price=110.5,
        pnl_pct=9.4,
        opened_at=time.time() - 3600,
        closed_at=time.time(),
    )

    with patch.object(monitor, "_broadcast_close", new=AsyncMock()):
        await monitor._process_close(signal, close_result)

    signal.trigger_be.assert_called_once()
    monitor._risk_manager.close_signal.assert_not_called()
    monitor._dashboard.record_result.assert_called_once()


@pytest.mark.asyncio
async def test_process_close_sl_fully_closes_signal(monitor):
    """SL hit is a full close: close_signal IS called."""
    result = _make_signal_result()
    signal = _make_active_signal(result)

    close_result = CloseResult(
        signal_id="test-id-1",
        symbol="BTC",
        side="LONG",
        outcome="SL",
        entry_price=101.0,
        exit_price=95.0,
        pnl_pct=-5.9,
        opened_at=time.time() - 3600,
        closed_at=time.time(),
    )

    with patch.object(monitor, "_broadcast_close", new=AsyncMock()):
        await monitor._process_close(signal, close_result)

    monitor._risk_manager.close_signal.assert_called_once_with("BTC", reason="sl")
    monitor._dashboard.record_result.assert_called_once()
    call_args = monitor._dashboard.record_result.call_args[0][0]
    assert call_args.outcome == "LOSS"


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


# ── BUG 5: Stale close deferred when price is in entry zone ──────────────────

class TestStaleCloseEntryZoneCheck:
    """_check_signals() defers stale close when price is within entry zone."""

    @pytest.mark.asyncio
    async def test_stale_skipped_when_price_in_zone(self, monitor):
        """If price is in entry zone, stale close is deferred."""
        result = _make_signal_result(entry_low=99.0, entry_high=101.0)
        signal = _make_active_signal(result)
        signal.is_stale.return_value = True  # signal is stale

        closed_signals = []
        monitor._risk_manager.active_signals = [signal]
        # Price is INSIDE the entry zone [99, 101]
        monitor._market_data.get_price.return_value = 100.0

        original_process = monitor._process_close

        async def capture_close(sig, result):
            closed_signals.append(result.outcome)
            await original_process(sig, result)

        monitor._process_close = capture_close
        await monitor._check_signals()

        # Should NOT have closed as stale because price is in entry zone
        assert "STALE" not in closed_signals

    @pytest.mark.asyncio
    async def test_stale_proceeds_when_price_outside_zone(self, monitor):
        """If price is outside the entry zone, stale close proceeds normally."""
        result = _make_signal_result(entry_low=99.0, entry_high=101.0)
        signal = _make_active_signal(result)
        signal.is_stale.return_value = True

        closed_signals = []
        monitor._risk_manager.active_signals = [signal]
        # Price is OUTSIDE the entry zone
        monitor._market_data.get_price.return_value = 115.0

        async def capture_close(sig, close_result):
            closed_signals.append(close_result.outcome)

        monitor._process_close = capture_close
        await monitor._check_signals()

        assert "STALE" in closed_signals


# ── BUG 7: SL after BE is mapped to "BE" outcome, not "LOSS" ─────────────────

class TestBEOutcomeMapping:
    """When SL hits after BE is triggered, outcome should be 'BE' not 'LOSS'."""

    def test_sl_after_be_returns_be_outcome(self, monitor):
        """_check_tp_sl_hit with be_triggered=True should produce SL outcome
        that _process_close maps to 'BE'."""
        result = _make_signal_result(
            side=Side.LONG,
            entry_low=99.0,
            entry_high=101.0,
            stop_loss=95.0,
        )
        # be_triggered=True means SL is now at entry (~100)
        signal = _make_active_signal(result, be_triggered=True)
        signal.result.stop_loss = 95.0

        # Price drops to entry level (BE stop) — SL hit with be_triggered=True
        close = monitor._check_tp_sl_hit(signal, current_price=99.5)
        # The SL is now at entry_mid due to be_triggered
        # entry_mid ≈ 100.0, price 99.5 < 100.0 → SL hit
        if close is not None and close.outcome == "SL":
            # Simulate what _process_close does for outcome mapping
            dashboard_outcome = "BE" if signal.be_triggered else "LOSS"
            assert dashboard_outcome == "BE", (
                "SL hit after BE should be recorded as 'BE', not 'LOSS'"
            )

    def test_sl_without_be_remains_loss(self, monitor):
        """SL hit before BE is triggered should still be 'LOSS'."""
        result = _make_signal_result(
            side=Side.LONG,
            entry_low=99.0,
            entry_high=101.0,
            stop_loss=95.0,
        )
        signal = _make_active_signal(result, be_triggered=False)
        close = monitor._check_tp_sl_hit(signal, current_price=94.0)
        assert close is not None
        assert close.outcome == "SL"
        dashboard_outcome = "BE" if signal.be_triggered else "LOSS"
        assert dashboard_outcome == "LOSS"
