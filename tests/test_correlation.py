"""Tests for calculate_correlation() and format_correlation_report()."""
from __future__ import annotations

import pytest

from bot.insights.correlation_matrix import calculate_correlation, format_correlation_report
from bot.signal_engine import CandleData


def _make_candles(closes: list[float]) -> list[CandleData]:
    return [CandleData(open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1000.0)
            for c in closes]


class TestCalculateCorrelation:
    def test_perfect_positive_correlation(self):
        # Identical price series → correlation = 1.0
        prices = [100.0, 102.0, 105.0, 103.0, 108.0]
        a = _make_candles(prices)
        b = _make_candles(prices)
        corr = calculate_correlation(a, b)
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative_correlation(self):
        # Inverse price series → correlation ≈ -1.0
        prices_a = [100.0, 102.0, 105.0, 103.0, 108.0]
        prices_b = [108.0, 103.0, 105.0, 102.0, 100.0]
        a = _make_candles(prices_a)
        b = _make_candles(prices_b)
        corr = calculate_correlation(a, b)
        assert corr < 0

    def test_no_correlation_returns_float(self):
        import random
        random.seed(42)
        a = _make_candles([100 + random.gauss(0, 1) for _ in range(20)])
        b = _make_candles([100 + random.gauss(0, 1) for _ in range(20)])
        corr = calculate_correlation(a, b)
        assert isinstance(corr, float)
        assert -1.0 <= corr <= 1.0

    def test_fewer_than_3_returns_zero(self):
        a = _make_candles([100.0, 101.0])
        b = _make_candles([100.0, 101.0])
        assert calculate_correlation(a, b) == 0.0

    def test_empty_series_returns_zero(self):
        assert calculate_correlation([], []) == 0.0

    def test_constant_series_returns_zero(self):
        # Constant price → std = 0 → correlation undefined → return 0.0
        a = _make_candles([100.0, 100.0, 100.0, 100.0, 100.0])
        b = _make_candles([100.0, 100.0, 100.0, 100.0, 100.0])
        assert calculate_correlation(a, b) == 0.0

    def test_mismatched_lengths_uses_shorter(self):
        a = _make_candles([100.0, 102.0, 105.0, 103.0, 108.0])
        b = _make_candles([100.0, 102.0, 105.0])
        corr = calculate_correlation(a, b)
        # Should not raise; result should be a valid float
        assert isinstance(corr, float)

    def test_known_correlation_value(self):
        # Manually computed: x=[1,2,3,4,5], y=[2,4,6,8,10] → correlation=1.0
        a = _make_candles([1.0, 2.0, 3.0, 4.0, 5.0])
        b = _make_candles([2.0, 4.0, 6.0, 8.0, 10.0])
        corr = calculate_correlation(a, b)
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_range_is_within_bounds(self):
        prices_a = [100.0 + i * 0.5 for i in range(30)]
        prices_b = [200.0 - i * 0.3 for i in range(30)]
        corr = calculate_correlation(_make_candles(prices_a), _make_candles(prices_b))
        assert -1.0 <= corr <= 1.0


class TestFormatCorrelationReport:
    def test_basic_format(self):
        correlations = {"ETH": 0.87, "SOL": 0.72, "DOGE": -0.34}
        msg = format_correlation_report(correlations)
        assert "ETH" in msg
        assert "SOL" in msg
        assert "DOGE" in msg
        assert "BTC" in msg.upper()

    def test_empty_correlations(self):
        msg = format_correlation_report({})
        assert "No data" in msg

    def test_positive_marked_green(self):
        msg = format_correlation_report({"ETH": 0.9})
        assert "🟢" in msg

    def test_negative_marked_red(self):
        msg = format_correlation_report({"DOGE": -0.5})
        assert "🔴" in msg

    def test_correlation_value_shown(self):
        msg = format_correlation_report({"BTC": 0.95})
        assert "0.95" in msg

    def test_explanatory_note_present(self):
        msg = format_correlation_report({"ETH": 0.8})
        assert "correlation" in msg.lower() or "btc" in msg.lower()
