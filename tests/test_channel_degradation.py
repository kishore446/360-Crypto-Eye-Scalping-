"""
Tests for bot/channel_degradation.py — Per-Channel Auto-Degradation (Part G)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.channel_degradation import ChannelDegradationManager


def _make_mock_dashboard(channel_stats: dict[str, dict]) -> MagicMock:
    """Create a mock dashboard with specified per-channel rolling stats."""
    db = MagicMock()
    db.per_channel_rolling_stats.return_value = channel_stats
    return db


class TestChannelDegradationInitial:
    def test_no_channels_degraded_initially(self):
        db = _make_mock_dashboard({})
        mgr = ChannelDegradationManager(db)
        assert mgr.get_extra_confluence("CH1_HARD") == 0
        assert mgr.is_channel_suppressed("CH1_HARD") is False

    def test_degraded_tiers_empty_initially(self):
        db = _make_mock_dashboard({})
        mgr = ChannelDegradationManager(db)
        assert mgr.degraded_tiers() == []

    def test_suppressed_tiers_empty_initially(self):
        db = _make_mock_dashboard({})
        mgr = ChannelDegradationManager(db)
        assert mgr.suppressed_tiers() == []


class TestChannelDegradationTriggers:
    def test_channel_degraded_below_35_wr(self):
        db = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 30.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db)
        alerts = mgr.check_and_update()
        assert len(alerts) == 1
        assert "Degraded" in alerts[0]
        assert mgr.get_extra_confluence("CH1_HARD") == 15
        assert mgr.is_channel_suppressed("CH1_HARD") is False

    def test_channel_suppressed_below_25_wr(self):
        db = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 20.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db)
        alerts = mgr.check_and_update()
        assert len(alerts) == 1
        assert "Suppressed" in alerts[0]
        assert mgr.is_channel_suppressed("CH1_HARD") is True

    def test_no_degradation_with_insufficient_data(self):
        db = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 10.0, "total_signals": 3},
        })
        mgr = ChannelDegradationManager(db)
        alerts = mgr.check_and_update()
        assert alerts == []
        assert mgr.get_extra_confluence("CH1_HARD") == 0

    def test_no_degradation_above_35_wr(self):
        db = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 60.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db)
        alerts = mgr.check_and_update()
        assert alerts == []

    def test_multiple_channels_can_degrade_independently(self):
        db = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 30.0, "total_signals": 20},
            "CH2_MEDIUM": {"win_rate": 20.0, "total_signals": 15},
            "CH3_EASY": {"win_rate": 60.0, "total_signals": 10},
        })
        mgr = ChannelDegradationManager(db)
        alerts = mgr.check_and_update()
        assert len(alerts) == 2
        assert mgr.is_channel_suppressed("CH2_MEDIUM") is True
        assert mgr.get_extra_confluence("CH1_HARD") == 15
        assert mgr.get_extra_confluence("CH3_EASY") == 0


class TestChannelDegradationRecovery:
    def test_channel_restores_above_50_wr(self):
        db_bad = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 30.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db_bad)
        mgr.check_and_update()
        assert mgr.get_extra_confluence("CH1_HARD") == 15

        db_good = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 55.0, "total_signals": 25},
        })
        mgr._dashboard = db_good
        alerts = mgr.check_and_update()
        assert any("Restored" in a for a in alerts)
        assert mgr.get_extra_confluence("CH1_HARD") == 0

    def test_suppressed_channel_restores(self):
        db_bad = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 20.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db_bad)
        mgr.check_and_update()
        assert mgr.is_channel_suppressed("CH1_HARD") is True

        db_good = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 55.0, "total_signals": 25},
        })
        mgr._dashboard = db_good
        alerts = mgr.check_and_update()
        assert any("Restored" in a for a in alerts)
        assert mgr.is_channel_suppressed("CH1_HARD") is False

    def test_no_duplicate_alerts_for_already_degraded_channel(self):
        db_bad = _make_mock_dashboard({
            "CH1_HARD": {"win_rate": 30.0, "total_signals": 20},
        })
        mgr = ChannelDegradationManager(db_bad)
        first_alerts = mgr.check_and_update()
        second_alerts = mgr.check_and_update()
        assert len(first_alerts) == 1
        assert len(second_alerts) == 0   # no new alert on second check
