"""
Tests for bot/open_interest.py — Open Interest Change Monitor.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.open_interest import analyze_oi_change, fetch_open_interest
from bot.signal_engine import Side


class TestAnalyzeOIChange:
    """Pure-computation tests — no I/O."""

    # ── OI up + price up = strong trend continuation ──────────────────────────

    def test_oi_up_price_up_boosts_long(self):
        result = analyze_oi_change(
            current_oi=1_100_000,
            previous_oi=1_000_000,
            price_change_pct=2.0,
            side=Side.LONG,
        )
        assert result == "BOOST"

    def test_oi_up_price_up_reduces_short(self):
        result = analyze_oi_change(
            current_oi=1_100_000,
            previous_oi=1_000_000,
            price_change_pct=2.0,
            side=Side.SHORT,
        )
        assert result == "REDUCE"

    # ── OI down + price up = weak rally / distribution ────────────────────────

    def test_oi_down_price_up_reduces_long(self):
        result = analyze_oi_change(
            current_oi=900_000,
            previous_oi=1_000_000,
            price_change_pct=2.0,
            side=Side.LONG,
        )
        assert result == "REDUCE"

    def test_oi_down_price_up_neutral_short(self):
        result = analyze_oi_change(
            current_oi=900_000,
            previous_oi=1_000_000,
            price_change_pct=2.0,
            side=Side.SHORT,
        )
        assert result == "NEUTRAL"

    # ── OI up + price down = bearish accumulation ─────────────────────────────

    def test_oi_up_price_down_boosts_short(self):
        result = analyze_oi_change(
            current_oi=1_100_000,
            previous_oi=1_000_000,
            price_change_pct=-2.0,
            side=Side.SHORT,
        )
        assert result == "BOOST"

    def test_oi_up_price_down_reduces_long(self):
        result = analyze_oi_change(
            current_oi=1_100_000,
            previous_oi=1_000_000,
            price_change_pct=-2.0,
            side=Side.LONG,
        )
        assert result == "REDUCE"

    # ── OI down + price down = capitulation / long squeeze ending ─────────────

    def test_oi_down_price_down_boosts_long(self):
        result = analyze_oi_change(
            current_oi=900_000,
            previous_oi=1_000_000,
            price_change_pct=-2.0,
            side=Side.LONG,
        )
        assert result == "BOOST"

    def test_oi_down_price_down_neutral_short(self):
        result = analyze_oi_change(
            current_oi=900_000,
            previous_oi=1_000_000,
            price_change_pct=-2.0,
            side=Side.SHORT,
        )
        assert result == "NEUTRAL"

    # ── Small OI change — below threshold ────────────────────────────────────

    def test_small_oi_change_neutral(self):
        """OI change below OI_CHANGE_THRESHOLD should always return NEUTRAL."""
        # 1% change, threshold is 5%
        result = analyze_oi_change(
            current_oi=1_010_000,
            previous_oi=1_000_000,
            price_change_pct=2.0,
            side=Side.LONG,
        )
        assert result == "NEUTRAL"

    def test_zero_previous_oi_neutral(self):
        """Zero previous OI should return NEUTRAL (avoid division by zero)."""
        result = analyze_oi_change(
            current_oi=1_000_000,
            previous_oi=0,
            price_change_pct=2.0,
            side=Side.LONG,
        )
        assert result == "NEUTRAL"


class TestFetchOpenInterest:
    """Network-layer tests using mocked requests."""

    def test_returns_float_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"openInterest": "5000000.00"}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.open_interest.requests.get", return_value=mock_resp):
            result = fetch_open_interest("BTC/USDT:USDT")
        assert result == pytest.approx(5_000_000.0)

    def test_returns_none_on_request_error(self):
        import requests as req_lib
        with patch("bot.open_interest.requests.get", side_effect=req_lib.RequestException("err")):
            result = fetch_open_interest("ETH")
        assert result is None

    def test_returns_none_on_missing_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.open_interest.requests.get", return_value=mock_resp):
            result = fetch_open_interest("SOL")
        assert result is None

    def test_symbol_normalised(self):
        """Symbol should be normalised to SOLUSDT for the Binance API."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"openInterest": "1000000"}
        mock_resp.raise_for_status.return_value = None
        with patch("bot.open_interest.requests.get", return_value=mock_resp) as mock_get:
            fetch_open_interest("SOL")
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["symbol"] == "SOLUSDT"
