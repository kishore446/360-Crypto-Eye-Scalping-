"""
Tests for trailing stop-loss functionality in bot/risk_manager.py
"""
from __future__ import annotations

import pytest

import bot.database as db_module
from bot.risk_manager import (
    ActiveSignal,
    RiskManager,
    TrailingStopConfig,
)
from bot.signal_engine import Confidence, Side, SignalResult


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite DB."""
    db_file = str(tmp_path / "test_trailing.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    yield db_file


def _make_signal(symbol: str = "BTC", side: Side = Side.LONG) -> SignalResult:
    entry = 100.0
    sl = 90.0 if side == Side.LONG else 110.0
    direction = 1 if side == Side.LONG else -1
    return SignalResult(
        symbol=symbol,
        side=side,
        confidence=Confidence.HIGH,
        entry_low=entry - 0.5,
        entry_high=entry + 0.5,
        tp1=entry + direction * 10.0,
        tp2=entry + direction * 20.0,
        tp3=entry + direction * 30.0,
        stop_loss=sl,
        structure_note="Test",
        context_note="Test context",
        leverage_min=10,
        leverage_max=20,
    )


# ── TrailingStopConfig tests ───────────────────────────────────────────────────


class TestTrailingStopConfig:
    def test_defaults(self):
        cfg = TrailingStopConfig()
        assert cfg.enabled is True
        assert cfg.atr_multiplier == pytest.approx(1.5)
        assert cfg.activation_after_be is True
        assert cfg.trail_step_pct == pytest.approx(0.1)

    def test_custom_values(self):
        cfg = TrailingStopConfig(enabled=False, atr_multiplier=2.0)
        assert cfg.enabled is False
        assert cfg.atr_multiplier == pytest.approx(2.0)


# ── Trailing SL on ActiveSignal ────────────────────────────────────────────────


class TestActiveSignalTrailingFields:
    def test_initial_state(self):
        sig = ActiveSignal(result=_make_signal())
        assert sig.trailing_sl_price is None
        assert sig.highest_since_entry is None
        assert sig.lowest_since_entry is None

    def test_trailing_fields_settable(self):
        sig = ActiveSignal(result=_make_signal())
        sig.trailing_sl_price = 99.5
        sig.highest_since_entry = 105.0
        assert sig.trailing_sl_price == pytest.approx(99.5)
        assert sig.highest_since_entry == pytest.approx(105.0)


# ── Trailing SL via RiskManager.update_prices ─────────────────────────────────


class TestTrailingSlActivation:
    def setup_method(self):
        cfg = TrailingStopConfig(
            enabled=True,
            atr_multiplier=2.0,
            activation_after_be=True,
            trail_step_pct=0.01,  # small step to make test easier
        )
        self.rm = RiskManager(trailing_config=cfg)

    def test_no_trail_before_be_when_activation_after_be(self):
        """Trailing SL must NOT activate before break-even when activation_after_be=True."""
        sig = self.rm.add_signal(_make_signal("ETH", Side.LONG))
        assert not sig.be_triggered
        # Price moves up but BE not triggered yet
        self.rm.update_prices({"ETH": 101.0})
        assert sig.trailing_sl_price is None
        assert not sig.closed

    def test_trail_activates_after_be_long(self):
        """After BE, price tracking should begin for LONG."""
        sig = self.rm.add_signal(_make_signal("BTC", Side.LONG))
        # Trigger BE (50% to TP1: entry_mid=100, tp1=110 → trigger at 105)
        sig.trigger_be()
        assert sig.be_triggered

        self.rm.update_prices({"BTC": 108.0})
        # Should have set highest_since_entry
        assert sig.highest_since_entry is not None

    def test_trailing_sl_price_updates_as_price_rises_long(self):
        """Trailing SL price must advance when price makes new highs."""
        cfg = TrailingStopConfig(
            enabled=True,
            atr_multiplier=1.0,
            activation_after_be=False,
            trail_step_pct=0.01,
        )
        rm = RiskManager(trailing_config=cfg)
        sig = rm.add_signal(_make_signal("BTC", Side.LONG))
        sig.trigger_be()

        rm.update_prices({"BTC": 105.0})
        first_trail = sig.trailing_sl_price

        rm.update_prices({"BTC": 108.0})
        second_trail = sig.trailing_sl_price

        # Trailing SL should have moved up
        assert second_trail > first_trail

    def test_trailing_sl_closes_signal_on_breach_long(self):
        """Signal must be closed when price breaches the trailing SL."""
        cfg = TrailingStopConfig(
            enabled=True,
            atr_multiplier=0.5,
            activation_after_be=False,
            trail_step_pct=0.001,
        )
        rm = RiskManager(trailing_config=cfg)
        sig = rm.add_signal(_make_signal("BTC", Side.LONG))
        sig.trigger_be()

        # Drive the price up to set a trailing SL
        rm.update_prices({"BTC": 115.0})
        assert sig.trailing_sl_price is not None
        assert sig.highest_since_entry == pytest.approx(115.0)
        trail = sig.trailing_sl_price

        # Now price drops below the trailing SL
        msgs = rm.update_prices({"BTC": trail - 0.01})
        assert sig.closed
        assert sig.close_reason == "trailing_sl"
        assert any("trailing" in m.lower() for m in msgs)

    def test_trailing_sl_closes_signal_on_breach_short(self):
        """Signal must be closed when price breaches the trailing SL for SHORT."""
        cfg = TrailingStopConfig(
            enabled=True,
            atr_multiplier=0.5,
            activation_after_be=False,
            trail_step_pct=0.001,
        )
        rm = RiskManager(trailing_config=cfg)
        sig = rm.add_signal(_make_signal("ETH", Side.SHORT))
        sig.trigger_be()

        # Drive price down to set a trailing SL
        rm.update_prices({"ETH": 85.0})
        assert sig.trailing_sl_price is not None
        trail = sig.trailing_sl_price

        # Now price rises above the trailing SL
        msgs = rm.update_prices({"ETH": trail + 0.01})
        assert sig.closed
        assert sig.close_reason == "trailing_sl"
        assert any("trailing" in m.lower() for m in msgs)

    def test_disabled_trailing_sl_does_not_close(self):
        """When trailing SL is disabled, signals must not be closed by it."""
        cfg = TrailingStopConfig(enabled=False)
        rm = RiskManager(trailing_config=cfg)
        sig = rm.add_signal(_make_signal("BTC", Side.LONG))
        sig.trigger_be()

        rm.update_prices({"BTC": 50.0})  # massive drop
        assert not sig.closed

    def test_trailing_sl_message_format(self):
        """Trailing SL close message must contain symbol and direction."""
        cfg = TrailingStopConfig(
            enabled=True,
            atr_multiplier=0.5,
            activation_after_be=False,
            trail_step_pct=0.001,
        )
        rm = RiskManager(trailing_config=cfg)
        sig = rm.add_signal(_make_signal("XRP", Side.LONG))
        sig.trigger_be()
        rm.update_prices({"XRP": 115.0})
        trail = sig.trailing_sl_price

        msgs = rm.update_prices({"XRP": trail - 0.01})
        assert any("XRP" in m for m in msgs)
        assert any("trailing_sl" in m.lower() or "trailing" in m.lower() for m in msgs)
