"""Tests for bot/session_filter.py"""
from __future__ import annotations
import datetime
import pytest
from unittest.mock import patch
from bot.session_filter import get_current_session, is_active_session


def _utc(hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2024, 1, 15, hour, minute, tzinfo=datetime.timezone.utc)


class TestGetCurrentSession:
    def test_london_session(self):
        assert get_current_session(_utc(8)) == "LONDON"
        assert get_current_session(_utc(10)) == "LONDON"
        assert get_current_session(_utc(11)) == "LONDON"

    def test_london_nyc_overlap(self):
        assert get_current_session(_utc(12)) == "LONDON+NYC_OVERLAP"
        assert get_current_session(_utc(14)) == "LONDON+NYC_OVERLAP"
        assert get_current_session(_utc(15)) == "LONDON+NYC_OVERLAP"

    def test_new_york_session(self):
        assert get_current_session(_utc(16)) == "NEW_YORK"
        assert get_current_session(_utc(18)) == "NEW_YORK"
        assert get_current_session(_utc(20)) == "NEW_YORK"

    def test_asia_session(self):
        assert get_current_session(_utc(0)) == "ASIA"
        assert get_current_session(_utc(3)) == "ASIA"
        assert get_current_session(_utc(6)) == "ASIA"

    def test_off_hours(self):
        assert get_current_session(_utc(21)) == "OFF_HOURS"
        assert get_current_session(_utc(23)) == "OFF_HOURS"

    def test_uses_current_time_when_none(self):
        # Just verify it doesn't raise
        result = get_current_session(None)
        assert result in ("LONDON", "NEW_YORK", "LONDON+NYC_OVERLAP", "ASIA", "OFF_HOURS")


class TestIsActiveSessionFilterEnabled:
    """Tests for is_active_session() when SESSION_FILTER_ENABLED=True."""

    def test_london_is_active(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(_utc(9)) is True

    def test_new_york_is_active(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(_utc(17)) is True

    def test_overlap_is_active(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(_utc(13)) is True

    def test_asia_is_not_active(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(_utc(3)) is False

    def test_off_hours_is_not_active(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(_utc(22)) is False


class TestIsActiveSessionFilterDisabled:
    """Tests for is_active_session() when SESSION_FILTER_ENABLED=False (default)."""

    def test_asia_is_active_when_filter_disabled(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", False):
            assert is_active_session(_utc(3)) is True

    def test_off_hours_is_active_when_filter_disabled(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", False):
            assert is_active_session(_utc(22)) is True

    def test_london_is_active_when_filter_disabled(self):
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", False):
            assert is_active_session(_utc(9)) is True

    def test_all_hours_active_when_filter_disabled(self):
        """All 24 hours should return True when SESSION_FILTER_ENABLED=False."""
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", False):
            for hour in range(24):
                assert is_active_session(_utc(hour)) is True, f"Hour {hour} should be active"
