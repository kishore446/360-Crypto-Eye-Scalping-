"""
Tests for bot/news_fetcher.py — focusing on Bug Fix 1:
When COINMARKETCAL_API_KEY is empty, fetch_and_reload() must NOT call
mark_fetch_failed(), so signals are never frozen due to a missing key.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import bot.news_fetcher as news_fetcher_module
from bot.news_fetcher import fetch_and_reload
from bot.news_filter import NewsCalendar


class TestFetchAndReloadNoApiKey:
    """Verify that a missing API key leaves last_successful_refresh == 0.0."""

    def test_no_api_key_does_not_call_mark_fetch_failed(self):
        """mark_fetch_failed() must never be called when COINMARKETCAL_API_KEY is empty."""
        calendar = MagicMock(spec=NewsCalendar)
        with patch.object(news_fetcher_module, "COINMARKETCAL_API_KEY", ""):
            fetch_and_reload(calendar)
        calendar.mark_fetch_failed.assert_not_called()

    def test_no_api_key_does_not_load_events(self):
        """load_events() must not be called when COINMARKETCAL_API_KEY is empty."""
        calendar = MagicMock(spec=NewsCalendar)
        with patch.object(news_fetcher_module, "COINMARKETCAL_API_KEY", ""):
            fetch_and_reload(calendar)
        calendar.load_events.assert_not_called()

    def test_no_api_key_signals_not_frozen(self):
        """
        A real NewsCalendar with last_successful_refresh == 0.0 must return
        is_stale() == False and is_high_impact_imminent() == False,
        allowing signals to proceed.
        """
        calendar = NewsCalendar()
        assert calendar.last_successful_refresh == 0.0
        assert calendar.is_stale() is False
        assert calendar.is_high_impact_imminent() is False

    def test_no_api_key_leaves_refresh_at_zero(self):
        """fetch_and_reload() with no API key must leave last_successful_refresh unchanged."""
        calendar = NewsCalendar()
        assert calendar.last_successful_refresh == 0.0
        with patch.object(news_fetcher_module, "COINMARKETCAL_API_KEY", ""):
            fetch_and_reload(calendar)
        assert calendar.last_successful_refresh == 0.0

    def test_stale_does_not_freeze_signals(self):
        """
        Regression (fixed): calling mark_fetch_failed() sets last_successful_refresh = 1.0,
        which is_stale() treats as old. Previously is_high_impact_imminent() returned True
        (freezing all signals). Now it returns False with a warning — stale data should
        degrade gracefully, not block everything.
        """
        calendar = NewsCalendar()
        calendar.mark_fetch_failed()
        # is_stale() should return True because last_successful_refresh = 1.0 (very old)
        assert calendar.is_stale() is True
        # Fixed: stale data now allows signals through instead of freezing
        assert calendar.is_high_impact_imminent() is False


class TestFetchAndReloadWithApiKey:
    """Verify that a present API key triggers a real fetch attempt."""

    def test_with_api_key_calls_fetch_events(self):
        """When COINMARKETCAL_API_KEY is set, fetch_coinmarketcal_events should be called."""
        calendar = MagicMock(spec=NewsCalendar)
        with (
            patch.object(news_fetcher_module, "COINMARKETCAL_API_KEY", "test-key"),
            patch.object(
                news_fetcher_module, "fetch_coinmarketcal_events", return_value=[]
            ) as mock_fetch,
        ):
            fetch_and_reload(calendar)
        mock_fetch.assert_called_once()

    def test_with_api_key_loads_returned_events(self):
        """Events returned by the API should be loaded into the calendar."""
        import time

        from bot.news_filter import NewsEvent

        fake_event = NewsEvent("FOMC", time.time() + 3600, "HIGH", "USD")
        calendar = MagicMock(spec=NewsCalendar)
        with (
            patch.object(news_fetcher_module, "COINMARKETCAL_API_KEY", "test-key"),
            patch.object(
                news_fetcher_module,
                "fetch_coinmarketcal_events",
                return_value=[fake_event],
            ),
        ):
            fetch_and_reload(calendar)
        calendar.load_events.assert_called_once_with([fake_event])
