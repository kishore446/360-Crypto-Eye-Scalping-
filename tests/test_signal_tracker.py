"""
Tests for bot/signal_tracker.py — focusing on Bug Fix 3:
After TP1 hits and BE is triggered, the SL check must use entry_mid
(the break-even level) rather than the original structural stop_loss.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.signal_engine import Side
from bot.signal_tracker import SignalTracker


def _make_signal(
    symbol: str = "BTC",
    side: Side = Side.LONG,
    entry_mid: float = 100.0,
    stop_loss: float = 95.0,
    tp1: float = 107.5,
    tp2: float = 112.5,
    tp3: float = 120.0,
    signal_id: str = "sig-001",
) -> SimpleNamespace:
    """Build a minimal signal-like object for SignalTracker tests."""
    result = SimpleNamespace(
        signal_id=signal_id,
        symbol=symbol,
        side=side,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
    )
    return SimpleNamespace(
        result=result,
        entry_mid=entry_mid,
    )


class TestSignalTrackerTP:
    def setup_method(self):
        self.tracker = SignalTracker()

    def test_tp1_hit_long(self):
        signal = _make_signal(side=Side.LONG)
        msgs = self.tracker.check_signal(signal, current_price=107.5)
        assert any("TP1" in m for m in msgs)

    def test_tp2_hit_long_requires_tp1_first(self):
        signal = _make_signal(side=Side.LONG)
        # TP2 price without TP1 first — should not trigger TP2
        msgs = self.tracker.check_signal(signal, current_price=112.5)
        assert not any("TP2" in m for m in msgs)

    def test_tp1_then_tp2_long(self):
        signal = _make_signal(side=Side.LONG)
        self.tracker.check_signal(signal, current_price=107.5)  # TP1
        msgs = self.tracker.check_signal(signal, current_price=112.5)  # TP2
        assert any("TP2" in m for m in msgs)

    def test_tp1_hit_short(self):
        signal = _make_signal(
            side=Side.SHORT,
            entry_mid=100.0,
            stop_loss=105.0,
            tp1=92.5,
            tp2=87.5,
            tp3=80.0,
        )
        msgs = self.tracker.check_signal(signal, current_price=92.5)
        assert any("TP1" in m for m in msgs)


class TestSignalTrackerSLBeforeTP1:
    """SL hit before TP1 — should use original stop_loss."""

    def setup_method(self):
        self.tracker = SignalTracker()

    def test_sl_hit_long_before_tp1(self):
        signal = _make_signal(side=Side.LONG, entry_mid=100.0, stop_loss=95.0)
        msgs = self.tracker.check_signal(signal, current_price=95.0)
        assert any("SL" in m for m in msgs)
        assert "95.0000" in msgs[0]

    def test_sl_hit_short_before_tp1(self):
        signal = _make_signal(
            side=Side.SHORT,
            entry_mid=100.0,
            stop_loss=105.0,
            tp1=92.5,
            tp2=87.5,
            tp3=80.0,
        )
        msgs = self.tracker.check_signal(signal, current_price=105.0)
        assert any("SL" in m for m in msgs)
        assert "105.0000" in msgs[0]


class TestSignalTrackerBEAfterTP1:
    """Bug Fix 3: SL check must use entry_mid after TP1 is hit."""

    def setup_method(self):
        self.tracker = SignalTracker()

    def test_sl_uses_entry_mid_after_tp1_long(self):
        """
        After TP1 hit on a LONG, the effective SL is entry_mid (100.0).
        Price ABOVE entry_mid (e.g., 101.0) should NOT fire SL.
        This verifies the effective SL is not the original stop_loss (95.0).
        """
        signal = _make_signal(
            side=Side.LONG,
            entry_mid=100.0,
            stop_loss=95.0,
            tp1=107.5,
        )
        # Hit TP1
        self.tracker.check_signal(signal, current_price=107.5)
        # Price still above entry_mid — SL should NOT fire
        msgs = self.tracker.check_signal(signal, current_price=101.0)
        assert not any("SL" in m for m in msgs), (
            "SL should not fire above entry_mid=100.0 after BE trigger"
        )

    def test_sl_fires_at_entry_mid_after_tp1_long(self):
        """After TP1 on LONG, SL fires when price drops to entry_mid."""
        signal = _make_signal(
            side=Side.LONG,
            entry_mid=100.0,
            stop_loss=95.0,
            tp1=107.5,
        )
        self.tracker.check_signal(signal, current_price=107.5)  # TP1
        msgs = self.tracker.check_signal(signal, current_price=100.0)  # BE level
        assert any("SL" in m for m in msgs)

    def test_sl_uses_entry_mid_after_tp1_short(self):
        """
        After TP1 hit on a SHORT, the effective SL is entry_mid (100.0).
        Price BELOW entry_mid (e.g., 99.0) should NOT fire SL.
        This verifies the effective SL is not the original stop_loss (105.0).
        """
        signal = _make_signal(
            side=Side.SHORT,
            entry_mid=100.0,
            stop_loss=105.0,
            tp1=92.5,
            tp2=87.5,
            tp3=80.0,
        )
        # Hit TP1
        self.tracker.check_signal(signal, current_price=92.5)
        # Price still below entry_mid — SL should NOT fire
        msgs = self.tracker.check_signal(signal, current_price=99.0)
        assert not any("SL" in m for m in msgs), (
            "SL should not fire below entry_mid=100.0 after BE trigger"
        )

    def test_sl_fires_at_entry_mid_after_tp1_short(self):
        """After TP1 on SHORT, SL fires when price rallies back to entry_mid."""
        signal = _make_signal(
            side=Side.SHORT,
            entry_mid=100.0,
            stop_loss=105.0,
            tp1=92.5,
            tp2=87.5,
            tp3=80.0,
        )
        self.tracker.check_signal(signal, current_price=92.5)  # TP1
        msgs = self.tracker.check_signal(signal, current_price=100.0)  # BE level
        assert any("SL" in m for m in msgs)

    def test_be_triggered_flag_set_on_tp1(self):
        """Internal be_triggered state should be True after TP1 hits."""
        signal = _make_signal(side=Side.LONG)
        self.tracker.check_signal(signal, current_price=107.5)  # TP1
        state = self.tracker._state["sig-001"]
        assert state["be_triggered"] is True

    def test_no_sl_after_tp3(self):
        """SL should not fire once TP3 has already been reached."""
        signal = _make_signal(
            side=Side.LONG,
            entry_mid=100.0,
            stop_loss=95.0,
            tp1=107.5,
            tp2=112.5,
            tp3=120.0,
        )
        self.tracker.check_signal(signal, current_price=107.5)  # TP1
        self.tracker.check_signal(signal, current_price=112.5)  # TP2
        self.tracker.check_signal(signal, current_price=120.0)  # TP3
        # Even below entry_mid, no SL should fire
        msgs = self.tracker.check_signal(signal, current_price=95.0)
        assert not any("SL" in m for m in msgs)


# ── Bug 3: Adaptive ATR fallback ─────────────────────────────────────────────

class TestAdaptiveAtrFallback:
    """Tests for adaptive ATR fallback in _compute_trail_sl()."""

    def setup_method(self):
        self.tracker = SignalTracker()

    def _make_signal_for_trail(self, price: float, side: Side = Side.LONG) -> SimpleNamespace:
        """Make a signal without ATR attribute to trigger fallback."""
        if side == Side.LONG:
            tp1, tp2, tp3 = price * 1.015, price * 1.025, price * 1.04
            sl = price * 0.98
        else:
            tp1, tp2, tp3 = price * 0.985, price * 0.975, price * 0.96
            sl = price * 1.02
        result = SimpleNamespace(
            signal_id="trail-test",
            symbol="TEST",
            side=side,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
        )
        return SimpleNamespace(result=result, entry_mid=price)

    def test_btc_price_fallback_tighter(self):
        """For BTC-price level (~90k), fallback should be 0.5% = 450."""
        signal = self._make_signal_for_trail(90000.0, Side.LONG)
        trail_sl = SignalTracker._compute_trail_sl(signal, 90000.0)
        # 0.5% of 90000 = 450 → trail SL = 90000 - 450 = 89550
        assert trail_sl is not None
        assert abs(trail_sl - (90000.0 - 90000.0 * 0.005)) < 1.0

    def test_mid_price_fallback(self):
        """For mid-price (~500), fallback should be 0.8% = 4.0."""
        signal = self._make_signal_for_trail(500.0, Side.LONG)
        trail_sl = SignalTracker._compute_trail_sl(signal, 500.0)
        assert trail_sl is not None
        assert abs(trail_sl - (500.0 - 500.0 * 0.008)) < 0.1

    def test_low_price_fallback(self):
        """For low-price (~5), fallback should be 1.2%."""
        signal = self._make_signal_for_trail(5.0, Side.LONG)
        trail_sl = SignalTracker._compute_trail_sl(signal, 5.0)
        assert trail_sl is not None
        assert abs(trail_sl - (5.0 - 5.0 * 0.012)) < 0.01

    def test_micro_price_fallback(self):
        """For micro-price (<1), fallback should be 2%."""
        signal = self._make_signal_for_trail(0.001, Side.LONG)
        trail_sl = SignalTracker._compute_trail_sl(signal, 0.001)
        assert trail_sl is not None
        assert abs(trail_sl - (0.001 - 0.001 * 0.02)) < 0.0001

    def test_short_trail_above_entry(self):
        """For SHORT, trail SL should be above current price."""
        signal = self._make_signal_for_trail(90000.0, Side.SHORT)
        trail_sl = SignalTracker._compute_trail_sl(signal, 90000.0)
        assert trail_sl is not None
        assert trail_sl > 90000.0

    def test_real_atr_takes_precedence(self):
        """When signal has valid atr attribute, it should be used instead of fallback."""
        signal = self._make_signal_for_trail(90000.0, Side.LONG)
        signal.atr = 100.0  # Add real ATR
        trail_sl = SignalTracker._compute_trail_sl(signal, 90000.0)
        # Should use ATR=100, not 0.5% fallback (450)
        assert trail_sl == pytest.approx(90000.0 - 100.0)


# ── BUG #1: auto_close_active flag skips TP/SL detection ─────────────────────

class TestAutoCloseActiveFlag:
    """When auto_close_active=True, SignalTracker must skip TP/SL detection."""

    def setup_method(self):
        self.tracker = SignalTracker()
        self.tracker.auto_close_active = True

    def test_tp1_suppressed_when_auto_close_active(self):
        """TP1 must NOT be emitted when AutoCloseMonitor is the sole TP/SL owner."""
        signal = _make_signal(side=Side.LONG)
        msgs = self.tracker.check_signal(signal, current_price=107.5)
        assert not any("TP1" in m for m in msgs), (
            "TP1 should not fire from SignalTracker when auto_close_active=True"
        )

    def test_sl_suppressed_when_auto_close_active(self):
        """SL must NOT be emitted when AutoCloseMonitor is the sole TP/SL owner."""
        signal = _make_signal(side=Side.LONG)
        msgs = self.tracker.check_signal(signal, current_price=95.0)  # at SL level
        assert not any("SL" in m for m in msgs), (
            "SL should not fire from SignalTracker when auto_close_active=True"
        )

    def test_short_tp_suppressed_when_auto_close_active(self):
        """SHORT TP must NOT be emitted when auto_close_active=True."""
        signal = _make_signal(
            side=Side.SHORT,
            entry_mid=100.0,
            stop_loss=105.0,
            tp1=92.5,
            tp2=87.5,
            tp3=80.0,
        )
        msgs = self.tracker.check_signal(signal, current_price=92.5)
        assert not any("TP1" in m for m in msgs)

    def test_flag_default_false(self):
        """auto_close_active should default to False on a new SignalTracker."""
        tracker = SignalTracker()
        assert tracker.auto_close_active is False

    def test_tp_sl_fires_normally_when_flag_false(self):
        """When auto_close_active is False (default), TP/SL detection is active."""
        tracker = SignalTracker()
        signal = _make_signal(side=Side.LONG)
        msgs = tracker.check_signal(signal, current_price=107.5)
        assert any("TP1" in m for m in msgs)


