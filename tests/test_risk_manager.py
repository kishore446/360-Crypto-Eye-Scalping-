"""
Tests for bot/risk_manager.py
"""

from __future__ import annotations

import time

import pytest

import bot.database as db_module
from bot.risk_manager import ActiveSignal, RiskManager, calculate_position_size
from bot.signal_engine import Confidence, Side, SignalResult
from config import MAX_SAME_SIDE_SIGNALS, STALE_SIGNAL_HOURS


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own isolated SQLite DB to avoid cross-test contamination."""
    db_file = str(tmp_path / "test_risk.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    yield db_file

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(symbol: str = "BTC", side: Side = Side.LONG) -> SignalResult:
    entry = 100.0
    sl = 95.0 if side == Side.LONG else 105.0
    direction = 1 if side == Side.LONG else -1
    return SignalResult(
        symbol=symbol,
        side=side,
        confidence=Confidence.HIGH,
        entry_low=entry - 0.5,
        entry_high=entry + 0.5,
        tp1=entry + direction * 7.5,
        tp2=entry + direction * 12.5,
        tp3=entry + direction * 20.0,
        stop_loss=sl,
        structure_note="Test",
        context_note="Test context",
        leverage_min=10,
        leverage_max=20,
    )


# ── ActiveSignal tests ────────────────────────────────────────────────────────

class TestActiveSignal:
    def test_entry_mid(self):
        sig = ActiveSignal(result=_make_signal())
        assert sig.entry_mid == pytest.approx(100.0)

    def test_not_stale_when_fresh(self):
        sig = ActiveSignal(result=_make_signal())
        assert sig.is_stale() is False

    def test_stale_after_threshold(self):
        sig = ActiveSignal(result=_make_signal())
        # Simulate opening > STALE_SIGNAL_HOURS hours ago
        sig.opened_at = time.time() - (STALE_SIGNAL_HOURS + 1) * 3600
        assert sig.is_stale() is True

    def test_be_trigger_long(self):
        sig = ActiveSignal(result=_make_signal(side=Side.LONG))
        # entry_mid=100, tp1=107.5 → BE triggers at 70% = 105.25
        assert sig.should_trigger_be(105.0) is False
        assert sig.should_trigger_be(105.5) is True

    def test_be_trigger_short(self):
        sig = ActiveSignal(result=_make_signal(side=Side.SHORT))
        # entry_mid=100, tp1=92.5 → BE triggers at 100 - 5.25 = 94.75
        assert sig.should_trigger_be(95.0) is False
        assert sig.should_trigger_be(94.5) is True

    def test_be_not_triggered_twice(self):
        sig = ActiveSignal(result=_make_signal(side=Side.LONG))
        sig.trigger_be()
        assert sig.should_trigger_be(110.0) is False  # already triggered

    def test_close(self):
        sig = ActiveSignal(result=_make_signal())
        sig.close("tp1")
        assert sig.closed is True
        assert sig.close_reason == "tp1"

    def test_origin_channel_default(self):
        sig = ActiveSignal(result=_make_signal())
        assert sig.origin_channel == 0

    def test_origin_channel_set(self):
        sig = ActiveSignal(result=_make_signal(), origin_channel=-100111)
        assert sig.origin_channel == -100111


# ── RiskManager tests ─────────────────────────────────────────────────────────

class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager()

    def test_add_signal(self):
        sig = _make_signal()
        active = self.rm.add_signal(sig)
        assert len(self.rm.active_signals) == 1
        assert active.result.symbol == "BTC"

    def test_add_signal_with_origin_channel(self):
        sig = _make_signal()
        active = self.rm.add_signal(sig, origin_channel=-100111)
        assert active.origin_channel == -100111

    def test_add_signal_default_origin_channel(self):
        sig = _make_signal()
        active = self.rm.add_signal(sig)
        assert active.origin_channel == 0

    def test_three_pair_cap(self):
        for i in range(MAX_SAME_SIDE_SIGNALS):
            self.rm.add_signal(_make_signal(symbol=f"COIN{i}", side=Side.LONG))

        assert self.rm.can_open_signal(Side.LONG) is False

        with pytest.raises(RuntimeError, match="3-Pair Cap reached"):
            self.rm.add_signal(_make_signal(symbol="EXTRA", side=Side.LONG))

    def test_cap_per_side(self):
        for i in range(MAX_SAME_SIDE_SIGNALS):
            self.rm.add_signal(_make_signal(symbol=f"LONG{i}", side=Side.LONG))

        # Shorts should still be allowed
        assert self.rm.can_open_signal(Side.SHORT) is True

    def test_cap_relaxes_when_signal_closed(self):
        signals = []
        for i in range(MAX_SAME_SIDE_SIGNALS):
            signals.append(self.rm.add_signal(_make_signal(symbol=f"COIN{i}", side=Side.LONG)))

        signals[0].close("tp1")
        assert self.rm.can_open_signal(Side.LONG) is True

    def test_close_signal(self):
        self.rm.add_signal(_make_signal(symbol="BTC"))
        closed = self.rm.close_signal("BTC", "manual")
        assert closed is True
        assert len(self.rm.active_signals) == 0

    def test_close_nonexistent_signal(self):
        assert self.rm.close_signal("NONEXISTENT") is False

    def test_update_prices_triggers_be(self):
        self.rm.add_signal(_make_signal(symbol="BTC", side=Side.LONG))
        # Price well above BE trigger (entry=100, tp1=107.5, BE at 70% = 105.25)
        msgs = self.rm.update_prices({"BTC": 106.0})
        assert any("Risk-Free Mode ON" in m for m in msgs)

    def test_update_prices_triggers_stale_close(self):
        active = self.rm.add_signal(_make_signal(symbol="ETH", side=Side.LONG))
        active.opened_at = time.time() - (STALE_SIGNAL_HOURS + 1) * 3600
        msgs = self.rm.update_prices({"ETH": 100.0})
        assert any("stale" in m.lower() for m in msgs)
        assert active.closed is True

    def test_update_prices_no_price_available(self):
        self.rm.add_signal(_make_signal(symbol="RARE"))
        # No price provided — no messages but no error
        msgs = self.rm.update_prices({})
        assert msgs == []


# ── Position size calculator tests ───────────────────────────────────────────

class TestCalculatePositionSize:
    def test_basic_calculation(self):
        result = calculate_position_size(
            account_balance=1000.0,
            entry_price=100.0,
            stop_loss_price=98.0,
        )
        # SL distance = 2 %, risk = $10 → position = $500
        assert result["risk_amount"] == pytest.approx(10.0, rel=1e-4)
        assert result["sl_distance_pct"] == pytest.approx(2.0, rel=1e-2)
        assert result["position_size_usdt"] == pytest.approx(500.0, rel=1e-4)
        assert result["position_size_units"] == pytest.approx(5.0, rel=1e-4)

    def test_custom_risk_fraction(self):
        result = calculate_position_size(
            account_balance=1000.0,
            entry_price=100.0,
            stop_loss_price=95.0,
            risk_fraction=0.02,
        )
        assert result["risk_amount"] == pytest.approx(20.0, rel=1e-4)

    def test_invalid_equal_prices(self):
        with pytest.raises(ValueError, match="must differ"):
            calculate_position_size(1000.0, 100.0, 100.0)

    def test_invalid_zero_price(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_position_size(1000.0, 0.0, 99.0)

    def test_short_trade_uses_absolute_distance(self):
        result = calculate_position_size(
            account_balance=1000.0,
            entry_price=100.0,
            stop_loss_price=102.0,  # SL above entry for short
        )
        assert result["sl_distance_pct"] == pytest.approx(2.0, rel=1e-2)
