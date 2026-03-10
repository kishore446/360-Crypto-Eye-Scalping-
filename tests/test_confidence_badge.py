"""Tests for bot/confidence_badge.py"""
from __future__ import annotations

from bot.confidence_badge import get_confidence_badge, get_expected_timeframe


class TestGetConfidenceBadge:
    def test_high_confidence(self):
        badge = get_confidence_badge("HIGH", ["G1", "G2", "G3", "G4", "G5", "G6", "G7"])
        assert "🔥" in badge
        assert "HIGH" in badge
        assert "7/7" in badge

    def test_medium_confidence(self):
        badge = get_confidence_badge("MEDIUM", ["G1", "G2", "G3", "G4", "G5"])
        assert "⚡" in badge
        assert "MEDIUM" in badge
        assert "5/7" in badge

    def test_low_confidence(self):
        badge = get_confidence_badge("LOW", ["G1", "G2", "G3"])
        assert "💡" in badge
        assert "LOW" in badge
        assert "3/7" in badge

    def test_lowercase_input(self):
        badge = get_confidence_badge("high", ["G1", "G2"])
        assert "🔥" in badge
        assert "HIGH" in badge

    def test_empty_gates_fired(self):
        badge = get_confidence_badge("LOW", [])
        assert "0/7" in badge

    def test_returns_string(self):
        badge = get_confidence_badge("HIGH", ["G1"])
        assert isinstance(badge, str)

    def test_gate_count_varies(self):
        badge6 = get_confidence_badge("HIGH", ["G1", "G2", "G3", "G4", "G5", "G6"])
        assert "6/7" in badge6

    def test_empty_confidence_uses_low(self):
        badge = get_confidence_badge("", ["G1"])
        assert "💡" in badge


class TestGetExpectedTimeframe:
    def test_zero_atr_returns_unknown(self):
        result = get_expected_timeframe(atr=0.0, entry=100.0, tp1=105.0)
        assert "Unknown" in result

    def test_zero_entry_returns_unknown(self):
        result = get_expected_timeframe(atr=1.0, entry=0.0, tp1=105.0)
        assert "Unknown" in result

    def test_very_small_distance_short_timeframe(self):
        # distance = 0.5, atr = 1.0 → ratio = 0.5 <= 1 → 15m-1h
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=100.5)
        assert "15m" in result

    def test_1x_atr_distance_short_timeframe(self):
        # distance = 1.0, atr = 1.0 → ratio = 1.0 <= 1 → 15m-1h
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=101.0)
        assert "15m" in result or "1h" in result

    def test_1_to_2x_atr_medium_timeframe(self):
        # distance = 1.5, atr = 1.0 → ratio = 1.5 → 1h-4h
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=101.5)
        assert "1h" in result or "4h" in result

    def test_2_to_4x_atr_longer_timeframe(self):
        # distance = 3.0, atr = 1.0 → ratio = 3.0 → 4h-24h
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=103.0)
        assert "4h" in result or "24h" in result

    def test_over_4x_atr_longest_timeframe(self):
        # distance = 6.0, atr = 1.0 → ratio = 6.0 → 1d-3d
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=106.0)
        assert "1d" in result or "3d" in result

    def test_returns_hourglass_icon(self):
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=101.0)
        assert "⏱" in result

    def test_sl_below_entry_works_abs(self):
        # TP below entry (short trade) — abs() should handle it
        result = get_expected_timeframe(atr=1.0, entry=100.0, tp1=99.0)
        assert "⏱" in result

    def test_prefix_est_hold(self):
        result = get_expected_timeframe(atr=2.0, entry=100.0, tp1=103.0)
        assert "Est. Hold" in result
