"""Tests for RiskManager.dynamic_risk_fraction()."""
from __future__ import annotations

import pytest

from bot.risk_manager import RiskManager


@pytest.fixture()
def risk_manager():
    return RiskManager()


class MockCooldown:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    def is_cooldown_active(self) -> bool:
        return self._active


# ── Normal (no cooldown) ─────────────────────────────────────────────────────

class TestDynamicRiskNormalMode:
    def test_high_confidence_normal(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("HIGH", cm) == 0.015

    def test_medium_confidence_normal(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("MEDIUM", cm) == 0.01

    def test_low_confidence_normal(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("LOW", cm) == 0.005

    def test_case_insensitive_high(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("High", cm) == 0.015

    def test_case_insensitive_medium(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("Medium", cm) == 0.01

    def test_case_insensitive_low(self, risk_manager):
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("Low", cm) == 0.005


# ── Cooldown active ───────────────────────────────────────────────────────────

class TestDynamicRiskCooldownMode:
    def test_high_confidence_cooldown(self, risk_manager):
        cm = MockCooldown(active=True)
        assert risk_manager.dynamic_risk_fraction("HIGH", cm) == 0.0075

    def test_medium_confidence_cooldown(self, risk_manager):
        cm = MockCooldown(active=True)
        assert risk_manager.dynamic_risk_fraction("MEDIUM", cm) == 0.005

    def test_low_confidence_cooldown_suppressed(self, risk_manager):
        """LOW confidence during cooldown must return 0.0 (suppressed)."""
        cm = MockCooldown(active=True)
        assert risk_manager.dynamic_risk_fraction("LOW", cm) == 0.0

    def test_low_confidence_cooldown_is_exactly_zero(self, risk_manager):
        cm = MockCooldown(active=True)
        result = risk_manager.dynamic_risk_fraction("low", cm)
        assert result == 0.0
        assert isinstance(result, float)


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestDynamicRiskEdgeCases:
    def test_none_cooldown_treated_as_no_cooldown(self, risk_manager):
        """If cooldown_manager is None, treat as not in cooldown."""
        assert risk_manager.dynamic_risk_fraction("HIGH", None) == 0.015
        assert risk_manager.dynamic_risk_fraction("MEDIUM", None) == 0.01
        assert risk_manager.dynamic_risk_fraction("LOW", None) == 0.005

    def test_unknown_confidence_treated_as_low(self, risk_manager):
        """Unknown confidence string falls through to LOW branch."""
        cm = MockCooldown(active=False)
        assert risk_manager.dynamic_risk_fraction("UNKNOWN_CONF", cm) == 0.005

    def test_cooldown_halves_high(self, risk_manager):
        """Cooldown risk should be exactly 0.5× normal risk."""
        cm_normal = MockCooldown(active=False)
        cm_cool = MockCooldown(active=True)
        normal = risk_manager.dynamic_risk_fraction("HIGH", cm_normal)
        cool = risk_manager.dynamic_risk_fraction("HIGH", cm_cool)
        assert cool == pytest.approx(normal * 0.5)

    def test_cooldown_halves_medium(self, risk_manager):
        cm_normal = MockCooldown(active=False)
        cm_cool = MockCooldown(active=True)
        normal = risk_manager.dynamic_risk_fraction("MEDIUM", cm_normal)
        cool = risk_manager.dynamic_risk_fraction("MEDIUM", cm_cool)
        assert cool == pytest.approx(normal * 0.5)
