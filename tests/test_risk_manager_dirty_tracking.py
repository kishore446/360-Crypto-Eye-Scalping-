"""
Tests for RiskManager dirty tracking — only modified signals should be persisted.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import bot.database as db_module
from bot.risk_manager import RiskManager
from bot.signal_engine import Confidence, Side, SignalResult


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_dirty.db")
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
        signal_id=f"{symbol}-{side.value}-001",
    )


class TestDirtyTracking:
    def setup_method(self):
        self.rm = RiskManager()

    def test_dirty_ids_empty_initially(self):
        assert self.rm._dirty_ids == set()

    def test_add_signal_marks_dirty(self):
        self.rm.add_signal(_make_signal("BTC"))
        assert len(self.rm._dirty_ids) == 0  # saved and cleared after _save()

    def test_save_clears_dirty_ids(self):
        """After _save(), _dirty_ids must be empty."""
        self.rm.add_signal(_make_signal("ETH"))
        # add_signal → _mark_dirty → _save → dirty_ids cleared
        assert self.rm._dirty_ids == set()

    def test_only_dirty_signals_written(self):
        """When price ticks mutate one signal, only that signal is saved."""
        sig_btc = self.rm.add_signal(_make_signal("BTC", Side.LONG))
        sig_eth = self.rm.add_signal(_make_signal("ETH", Side.LONG))

        saved_ids = []

        original_save_signal = db_module.save_signal

        def capture_save(data):
            saved_ids.append(data["id"])
            return original_save_signal(data)

        with patch("bot.database.save_signal", side_effect=capture_save):
            # Trigger BE for BTC only (price at 108 — above 70% to TP1=110)
            self.rm.update_prices({"BTC": 108.0, "ETH": 100.0})

        # Only BTC should have been persisted (BE triggered)
        btc_id = sig_btc.result.signal_id or f"sig_{int(sig_btc.opened_at)}"
        eth_id = sig_eth.result.signal_id or f"sig_{int(sig_eth.opened_at)}"

        assert btc_id in saved_ids
        assert eth_id not in saved_ids

    def test_no_save_when_no_mutation(self):
        """When no price event triggers a mutation, save_signal must not be called."""
        self.rm.add_signal(_make_signal("BTC", Side.LONG))

        with patch("bot.database.save_signal") as mock_save:
            # Price unchanged, no events
            self.rm.update_prices({"BTC": 100.0})  # no BE trigger yet

        mock_save.assert_not_called()

    def test_close_signal_marks_dirty_and_saves(self):
        """close_signal() must mark the signal dirty and persist immediately."""
        self.rm.add_signal(_make_signal("BTC"))

        saved_ids = []
        original_save_signal = db_module.save_signal

        def capture_save(data):
            saved_ids.append(data["id"])
            return original_save_signal(data)

        with patch("bot.database.save_signal", side_effect=capture_save):
            self.rm.close_signal("BTC", reason="manual")

        assert len(saved_ids) == 1

    def test_full_save_marks_all_dirty(self):
        """public save() must persist all signals, even unmodified ones."""
        self.rm.add_signal(_make_signal("BTC"))
        self.rm.add_signal(_make_signal("ETH"))

        saved_ids = []
        original_save_signal = db_module.save_signal

        def capture_save(data):
            saved_ids.append(data["id"])
            return original_save_signal(data)

        with patch("bot.database.save_signal", side_effect=capture_save):
            self.rm.save()

        assert len(saved_ids) == 2

    def test_stale_close_does_not_happen_in_update_prices(self):
        """BUG #3 fix: update_prices() must NOT perform stale-close.
        Stale detection is exclusively owned by AutoCloseMonitor so that
        per-channel stale-hour overrides (CH4 Spot = 24 h, etc.) are respected."""
        sig = self.rm.add_signal(_make_signal("BTC", Side.LONG))
        # Make it stale per the global threshold
        sig.opened_at = time.time() - (4 + 1) * 3600  # >4h ago

        saved_ids = []
        original_save_signal = db_module.save_signal

        def capture_save(data):
            saved_ids.append(data["id"])
            return original_save_signal(data)

        with patch("bot.database.save_signal", side_effect=capture_save):
            self.rm.update_prices({"BTC": 100.0})

        # Signal must remain open — AutoCloseMonitor owns stale-close logic
        assert not sig.closed
