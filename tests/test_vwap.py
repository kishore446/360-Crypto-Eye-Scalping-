"""Tests for bot/vwap.py"""
from __future__ import annotations
import pytest
from bot.signal_engine import CandleData
from bot.vwap import calculate_vwap, is_near_vwap


def _candle(high: float, low: float, close: float, volume: float) -> CandleData:
    return CandleData(open=(high + low) / 2, high=high, low=low, close=close, volume=volume)


class TestCalculateVwap:
    def test_empty_returns_zero(self):
        assert calculate_vwap([]) == 0.0

    def test_zero_volume_returns_zero(self):
        candles = [_candle(100.0, 98.0, 99.0, 0.0) for _ in range(5)]
        assert calculate_vwap(candles) == 0.0

    def test_single_candle(self):
        c = _candle(high=102.0, low=98.0, close=100.0, volume=10.0)
        vwap = calculate_vwap([c])
        typical = (102.0 + 98.0 + 100.0) / 3.0
        assert vwap == pytest.approx(typical)

    def test_equal_volume_candles(self):
        candles = [
            _candle(110.0, 90.0, 100.0, 100.0),
            _candle(120.0, 100.0, 110.0, 100.0),
        ]
        vwap = calculate_vwap(candles)
        t1 = (110.0 + 90.0 + 100.0) / 3.0
        t2 = (120.0 + 100.0 + 110.0) / 3.0
        expected = (t1 + t2) / 2.0
        assert vwap == pytest.approx(expected)

    def test_higher_volume_weights_more(self):
        c1 = _candle(100.0, 100.0, 100.0, 1.0)
        c2 = _candle(200.0, 200.0, 200.0, 9.0)
        vwap = calculate_vwap([c1, c2])
        # Weighted toward c2's typical price (200)
        assert vwap > 150.0


class TestIsNearVwap:
    def test_price_at_vwap_is_near(self):
        assert is_near_vwap(100.0, 100.0) is True

    def test_price_within_threshold(self):
        assert is_near_vwap(100.4, 100.0, threshold_pct=0.5) is True

    def test_price_outside_threshold(self):
        assert is_near_vwap(101.0, 100.0, threshold_pct=0.5) is False

    def test_zero_vwap_returns_false(self):
        assert is_near_vwap(100.0, 0.0) is False
