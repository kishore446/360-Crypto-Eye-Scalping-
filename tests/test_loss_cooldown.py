"""
Tests for bot/loss_streak_cooldown.py — Smart Cooldown After Loss Streak.
"""
from __future__ import annotations

import threading
import time

import pytest

from bot.loss_streak_cooldown import CooldownManager


class TestCooldownActivation:
    def setup_method(self):
        self.mgr = CooldownManager()

    def test_no_cooldown_initially(self):
        assert self.mgr.is_cooldown_active() is False

    def test_single_loss_no_cooldown(self):
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is False

    def test_two_losses_no_cooldown(self):
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is False

    def test_three_consecutive_losses_triggers_cooldown(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is True

    def test_record_outcome_returns_true_when_cooldown_activates(self):
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        result = self.mgr.record_outcome("LOSS")
        assert result is True

    def test_record_outcome_returns_false_when_no_cooldown(self):
        result = self.mgr.record_outcome("LOSS")
        assert result is False

    def test_win_resets_consecutive_loss_counter(self):
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("WIN")  # resets counter
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is False

    def test_be_resets_consecutive_loss_counter(self):
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("BE")  # break-even also counts as non-loss
        self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is False


class TestRiskModifier:
    def setup_method(self):
        self.mgr = CooldownManager()

    def test_risk_modifier_normal(self):
        assert self.mgr.get_risk_modifier() == pytest.approx(1.0)

    def test_risk_modifier_during_cooldown(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        assert self.mgr.get_risk_modifier() == pytest.approx(0.5)

    def test_risk_modifier_restores_after_cooldown(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        for _ in range(3):
            self.mgr.record_outcome("WIN")
        assert self.mgr.get_risk_modifier() == pytest.approx(1.0)


class TestLowConfidenceSuppression:
    def setup_method(self):
        self.mgr = CooldownManager()

    def test_no_suppression_normally(self):
        assert self.mgr.should_suppress_low_confidence() is False

    def test_suppression_during_cooldown(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        assert self.mgr.should_suppress_low_confidence() is True

    def test_no_suppression_after_cooldown_expires(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        for _ in range(3):
            self.mgr.record_outcome("WIN")
        assert self.mgr.should_suppress_low_confidence() is False


class TestCooldownReset:
    def setup_method(self):
        self.mgr = CooldownManager()

    def test_cooldown_resets_after_three_profitable_signals(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is True
        self.mgr.record_outcome("WIN")
        self.mgr.record_outcome("WIN")
        self.mgr.record_outcome("WIN")
        assert self.mgr.is_cooldown_active() is False

    def test_cooldown_resets_after_24_hours(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is True
        # Simulate 24+ hours passing
        past_time = time.time() - (25 * 3600)
        self.mgr._cooldown_started_at = past_time
        assert self.mgr.is_cooldown_active() is False

    def test_cooldown_still_active_before_24_hours(self):
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        past_time = time.time() - (23 * 3600)
        self.mgr._cooldown_started_at = past_time
        assert self.mgr.is_cooldown_active() is True

    def test_partial_recovery_keeps_cooldown_active(self):
        """Two wins out of three required should not deactivate cooldown."""
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        self.mgr.record_outcome("WIN")
        self.mgr.record_outcome("WIN")
        assert self.mgr.is_cooldown_active() is True

    def test_cooldown_not_activated_again_immediately_after_reset(self):
        """After cooldown resets via wins, single loss should not re-trigger cooldown."""
        for _ in range(3):
            self.mgr.record_outcome("LOSS")
        for _ in range(3):
            self.mgr.record_outcome("WIN")
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_cooldown_active() is False


class TestCooldownThreadSafety:
    def test_concurrent_record_outcome_no_errors(self):
        cm = CooldownManager()
        errors = []

        def record_losses(n):
            try:
                for _ in range(n):
                    cm.record_outcome("LOSS")
                    cm.record_outcome("WIN")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_losses, args=(50,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ── Part H: Win Streak (Hot Streak) ──────────────────────────────────────────

class TestHotStreak:
    def setup_method(self):
        self.mgr = CooldownManager()

    def test_no_hot_streak_initially(self):
        assert self.mgr.is_hot_streak_active() is False

    def test_hot_streak_not_active_before_threshold(self):
        for _ in range(4):
            self.mgr.record_outcome("WIN")
        assert self.mgr.is_hot_streak_active() is False

    def test_hot_streak_activates_at_threshold(self):
        for _ in range(5):
            self.mgr.record_outcome("WIN")
        assert self.mgr.is_hot_streak_active() is True

    def test_hot_streak_bonus_confluence_nonzero(self):
        for _ in range(5):
            self.mgr.record_outcome("WIN")
        assert self.mgr.get_hot_streak_bonus() > 0

    def test_hot_streak_resets_on_loss(self):
        for _ in range(5):
            self.mgr.record_outcome("WIN")
        assert self.mgr.is_hot_streak_active() is True
        self.mgr.record_outcome("LOSS")
        assert self.mgr.is_hot_streak_active() is False

    def test_hot_streak_bonus_zero_when_inactive(self):
        assert self.mgr.get_hot_streak_bonus() == 0

    def test_be_does_not_break_hot_streak(self):
        for _ in range(5):
            self.mgr.record_outcome("WIN")
        assert self.mgr.is_hot_streak_active() is True
        self.mgr.record_outcome("BE")
        assert self.mgr.is_hot_streak_active() is True
