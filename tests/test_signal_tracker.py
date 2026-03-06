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
