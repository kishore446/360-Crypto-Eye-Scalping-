"""Tests for bot/correlation_guard.py"""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.correlation_guard import (
    CORRELATION_GROUPS,
    _get_correlation_group,
    check_correlation_risk,
)
from bot.signal_engine import Confidence, Side, SignalResult

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_active_signal(symbol: str, side: Side, closed: bool = False) -> MagicMock:
    result = SignalResult(
        symbol=symbol,
        side=side,
        confidence=Confidence.HIGH,
        entry_low=100.0,
        entry_high=102.0,
        tp1=108.0,
        tp2=115.0,
        tp3=125.0,
        stop_loss=96.0,
        structure_note="",
        context_note="",
        leverage_min=10,
        leverage_max=20,
    )
    sig = MagicMock()
    sig.result = result
    sig.closed = closed
    return sig


# ── CORRELATION_GROUPS sanity checks ──────────────────────────────────────────

class TestCorrelationGroups:
    def test_btc_majors_group_exists(self):
        assert "BTC_MAJORS" in CORRELATION_GROUPS
        assert "BTC" in CORRELATION_GROUPS["BTC_MAJORS"]
        assert "ETH" in CORRELATION_GROUPS["BTC_MAJORS"]
        assert "SOL" in CORRELATION_GROUPS["BTC_MAJORS"]

    def test_meme_group_exists(self):
        assert "MEME" in CORRELATION_GROUPS
        assert "DOGE" in CORRELATION_GROUPS["MEME"]

    def test_l2_group_exists(self):
        assert "L2" in CORRELATION_GROUPS
        assert "MATIC" in CORRELATION_GROUPS["L2"]


# ── _get_correlation_group ─────────────────────────────────────────────────────

class TestGetCorrelationGroup:
    def test_btc_maps_to_btc_majors(self):
        assert _get_correlation_group("BTC") == "BTC_MAJORS"

    def test_eth_maps_to_btc_majors(self):
        assert _get_correlation_group("ETH") == "BTC_MAJORS"

    def test_doge_maps_to_meme(self):
        assert _get_correlation_group("DOGE") == "MEME"

    def test_link_maps_to_defi(self):
        assert _get_correlation_group("LINK") == "DEFI"

    def test_unknown_returns_none(self):
        assert _get_correlation_group("UNKNOWN_TOKEN_XYZ") is None

    def test_usdt_suffix_stripped(self):
        assert _get_correlation_group("BTCUSDT") == "BTC_MAJORS"


# ── check_correlation_risk ────────────────────────────────────────────────────

class TestCheckCorrelationRisk:
    def test_no_warning_when_no_signals(self):
        result = check_correlation_risk([])
        assert result is None

    def test_no_warning_below_threshold(self):
        signals = [
            _make_active_signal("BTC", Side.LONG),
            _make_active_signal("ETH", Side.LONG),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_warning_at_threshold(self):
        signals = [
            _make_active_signal("BTC", Side.LONG),
            _make_active_signal("ETH", Side.LONG),
            _make_active_signal("SOL", Side.LONG),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "CORRELATION RISK" in result
        assert "LONG" in result
        assert "BTC_MAJORS" in result

    def test_no_warning_different_sides(self):
        signals = [
            _make_active_signal("BTC", Side.LONG),
            _make_active_signal("ETH", Side.SHORT),
            _make_active_signal("SOL", Side.LONG),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        # Only 2 LONG in BTC_MAJORS — no warning
        assert result is None

    def test_closed_signals_excluded(self):
        signals = [
            _make_active_signal("BTC", Side.LONG, closed=True),
            _make_active_signal("ETH", Side.LONG, closed=True),
            _make_active_signal("SOL", Side.LONG, closed=False),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_no_warning_when_not_in_group(self):
        # UNKNOWN_TOKEN is not in any group
        signals = [
            _make_active_signal("UNKNOWN1", Side.LONG),
            _make_active_signal("UNKNOWN2", Side.LONG),
            _make_active_signal("UNKNOWN3", Side.LONG),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_warning_message_format(self):
        signals = [
            _make_active_signal("BTC", Side.SHORT),
            _make_active_signal("ETH", Side.SHORT),
            _make_active_signal("SOL", Side.SHORT),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "⚠️" in result
        assert "3" in result
        assert "SHORT" in result

    def test_meme_group_triggers_warning(self):
        signals = [
            _make_active_signal("DOGE", Side.LONG),
            _make_active_signal("SHIB", Side.LONG),
            _make_active_signal("PEPE", Side.LONG),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "MEME" in result

    def test_custom_threshold(self):
        signals = [
            _make_active_signal("BTC", Side.LONG),
            _make_active_signal("ETH", Side.LONG),
        ]
        # threshold of 2 should trigger
        result = check_correlation_risk(signals, max_same_group=2)
        assert result is not None
        # threshold of 3 should not trigger
        result2 = check_correlation_risk(signals, max_same_group=3)
        assert result2 is None
