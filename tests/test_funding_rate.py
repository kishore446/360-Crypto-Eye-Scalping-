"""
Tests for bot/funding_rate.py — Gate ⑧ Funding Rate Sentiment.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

import bot.funding_rate as funding_rate_module
from bot.funding_rate import fetch_funding_rate, get_funding_sentiment
from bot.signal_engine import Side


class TestGetFundingSentiment:
    """Pure-computation tests — no I/O."""

    def test_extreme_negative_funding_boosts_long(self):
        """Extremely negative funding + LONG = contrarian edge → BOOST."""
        assert get_funding_sentiment(-0.0002, Side.LONG) == "BOOST"

    def test_extreme_negative_funding_reduces_short(self):
        """Extremely negative funding + SHORT = crowded trade → REDUCE."""
        assert get_funding_sentiment(-0.0002, Side.SHORT) == "REDUCE"

    def test_extreme_positive_funding_boosts_short(self):
        """Extremely positive funding + SHORT = contrarian edge → BOOST."""
        assert get_funding_sentiment(0.001, Side.SHORT) == "BOOST"

    def test_extreme_positive_funding_reduces_long(self):
        """Extremely positive funding + LONG = crowded trade → REDUCE."""
        assert get_funding_sentiment(0.001, Side.LONG) == "REDUCE"

    def test_normal_funding_neutral_long(self):
        """Normal (non-extreme) funding → NEUTRAL regardless of side."""
        assert get_funding_sentiment(0.0001, Side.LONG) == "NEUTRAL"

    def test_normal_funding_neutral_short(self):
        assert get_funding_sentiment(0.0001, Side.SHORT) == "NEUTRAL"

    def test_zero_funding_neutral(self):
        assert get_funding_sentiment(0.0, Side.LONG) == "NEUTRAL"

    def test_none_funding_neutral(self):
        """None (API failure) must gracefully return NEUTRAL."""
        assert get_funding_sentiment(None, Side.LONG) == "NEUTRAL"
        assert get_funding_sentiment(None, Side.SHORT) == "NEUTRAL"

    def test_boundary_extreme_negative_long(self):
        """Exactly at the extreme negative threshold → BOOST for LONG."""
        threshold = funding_rate_module.FUNDING_EXTREME_NEGATIVE
        # Just below threshold (more negative) → BOOST
        assert get_funding_sentiment(threshold - 0.00001, Side.LONG) == "BOOST"

    def test_boundary_extreme_positive_short(self):
        """Exactly at the extreme positive threshold → BOOST for SHORT."""
        threshold = funding_rate_module.FUNDING_EXTREME_POSITIVE
        assert get_funding_sentiment(threshold + 0.00001, Side.SHORT) == "BOOST"


class TestFetchFundingRate:
    """Network-layer tests using mocked requests."""

    def test_returns_float_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"lastFundingRate": "0.0003"}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.funding_rate.requests.get", return_value=mock_resp):
            result = fetch_funding_rate("BTC/USDT:USDT")
        assert result == pytest.approx(0.0003)

    def test_returns_none_on_request_error(self):
        import requests as req_lib
        with patch("bot.funding_rate.requests.get", side_effect=req_lib.RequestException("timeout")):
            result = fetch_funding_rate("BTC")
        assert result is None

    def test_returns_none_on_missing_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}  # no lastFundingRate
        mock_resp.raise_for_status.return_value = None
        with patch("bot.funding_rate.requests.get", return_value=mock_resp):
            result = fetch_funding_rate("ETH")
        assert result is None

    def test_symbol_normalised_without_slash(self):
        """Symbol should be normalised to BTCUSDT for the Binance API."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"lastFundingRate": "0.0001"}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.funding_rate.requests.get", return_value=mock_resp) as mock_get:
            fetch_funding_rate("BTC/USDT:USDT")
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["symbol"] == "BTCUSDT"

    def test_symbol_appends_usdt_if_missing(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"lastFundingRate": "0.0001"}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.funding_rate.requests.get", return_value=mock_resp) as mock_get:
            fetch_funding_rate("SOL")
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["symbol"] == "SOLUSDT"
