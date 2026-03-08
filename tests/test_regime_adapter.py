"""
Tests for bot/regime_adapter.py
"""
from __future__ import annotations

import pytest

from bot.regime_adapter import get_regime_adjustments


class TestGetRegimeAdjustments:
    def test_bull_regime(self):
        adj = get_regime_adjustments("BULL")
        assert adj["tp3_rr"] == pytest.approx(5.0)
        assert adj["max_signals"] == 5
        assert adj["risk_modifier"] == pytest.approx(1.0)

    def test_bear_regime(self):
        adj = get_regime_adjustments("BEAR")
        assert adj["tp3_rr"] == pytest.approx(3.0)
        assert adj["max_signals"] == 3
        assert adj["risk_modifier"] == pytest.approx(0.75)

    def test_sideways_regime(self):
        adj = get_regime_adjustments("SIDEWAYS")
        assert adj["tp3_rr"] == pytest.approx(2.5)
        assert adj["max_signals"] == 2
        assert adj["risk_modifier"] == pytest.approx(0.5)

    def test_case_insensitive(self):
        assert get_regime_adjustments("bull") == get_regime_adjustments("BULL")
        assert get_regime_adjustments("Bear") == get_regime_adjustments("BEAR")
        assert get_regime_adjustments("sideways") == get_regime_adjustments("SIDEWAYS")

    def test_unknown_regime_has_neutral_settings(self):
        """UNKNOWN regime should map to neutral/moderate parameters, not SIDEWAYS."""
        adj = get_regime_adjustments("UNKNOWN")
        assert adj["tp3_rr"] == pytest.approx(4.0)
        assert adj["max_signals"] == 4
        assert adj["risk_modifier"] == pytest.approx(0.85)

    def test_unknown_regime_is_not_sideways(self):
        """UNKNOWN must have distinct parameters from SIDEWAYS."""
        adj = get_regime_adjustments("UNKNOWN")
        sideways = get_regime_adjustments("SIDEWAYS")
        assert adj != sideways

    def test_empty_string_falls_back_to_sideways(self):
        adj = get_regime_adjustments("")
        sideways = get_regime_adjustments("SIDEWAYS")
        assert adj == sideways

    def test_returns_dict_with_required_keys(self):
        for regime in ("BULL", "BEAR", "SIDEWAYS"):
            adj = get_regime_adjustments(regime)
            assert "tp3_rr" in adj
            assert "max_signals" in adj
            assert "risk_modifier" in adj

    def test_risk_modifier_decreases_bear_to_sideways(self):
        bull = get_regime_adjustments("BULL")
        bear = get_regime_adjustments("BEAR")
        sideways = get_regime_adjustments("SIDEWAYS")
        assert bull["risk_modifier"] >= bear["risk_modifier"] >= sideways["risk_modifier"]

    def test_tp3_rr_decreases_bull_to_sideways(self):
        bull = get_regime_adjustments("BULL")
        bear = get_regime_adjustments("BEAR")
        sideways = get_regime_adjustments("SIDEWAYS")
        assert bull["tp3_rr"] > bear["tp3_rr"] > sideways["tp3_rr"]
