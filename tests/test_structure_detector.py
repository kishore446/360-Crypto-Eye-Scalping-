"""Tests for bot/structure_detector.py"""
from __future__ import annotations
import pytest
from bot.signal_engine import CandleData, Side
from bot.structure_detector import (
    SwingPoint,
    DealingRange,
    detect_swing_points,
    find_dealing_range,
    find_key_liquidity_level,
)


def _candles(highs: list[float], lows: list[float], close_offset: float = 0.0) -> list[CandleData]:
    return [
        CandleData(open=l + 0.1, high=h, low=l, close=l + close_offset, volume=100.0)
        for h, l in zip(highs, lows)
    ]


class TestDetectSwingPoints:
    def test_detects_swing_high(self):
        # Pattern: lower highs on both sides of center
        candles = _candles(
            highs=[1.0, 1.5, 2.0, 1.5, 1.0, 0.8, 0.7],
            lows= [0.5, 0.8, 1.0, 0.8, 0.5, 0.3, 0.2],
        )
        swings = detect_swing_points(candles, lookback=2)
        highs = [s for s in swings if s.kind == "high"]
        assert any(s.price == 2.0 for s in highs)

    def test_detects_swing_low(self):
        candles = _candles(
            highs=[2.0, 1.5, 1.2, 1.5, 2.0, 2.2, 2.3],
            lows= [1.5, 1.0, 0.5, 1.0, 1.5, 1.8, 1.9],
        )
        swings = detect_swing_points(candles, lookback=2)
        lows = [s for s in swings if s.kind == "low"]
        assert any(s.price == 0.5 for s in lows)

    def test_empty_candles(self):
        assert detect_swing_points([], lookback=2) == []

    def test_too_few_candles(self):
        candles = _candles([1.0, 2.0, 1.0], [0.5, 1.0, 0.5])
        # With lookback=2, need at least 5 candles; less returns empty
        result = detect_swing_points(candles, lookback=2)
        assert result == []

    def test_flat_candles_no_swings(self):
        candles = _candles([1.0] * 10, [0.5] * 10)
        result = detect_swing_points(candles, lookback=2)
        assert result == []


class TestFindDealingRange:
    def _bullish_4h(self, n: int = 15) -> list[CandleData]:
        return [
            CandleData(open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.0 + i, volume=1000.0)
            for i in range(n)
        ]

    def test_returns_dealing_range(self):
        candles_4h = self._bullish_4h(15)
        result = find_dealing_range(candles_4h, [])
        assert isinstance(result, DealingRange)
        assert result.high > result.low

    def test_fallback_empty_candles(self):
        result = find_dealing_range([], [])
        assert result == DealingRange(high=0.0, low=0.0)

    def test_uses_15m_fallback_when_4h_empty(self):
        candles_15m = [
            CandleData(open=50.0, high=55.0, low=45.0, close=52.0, volume=100.0)
            for _ in range(5)
        ]
        result = find_dealing_range([], candles_15m)
        assert result.high == 55.0
        assert result.low == 45.0


class TestFindKeyLiquidityLevel:
    def _price_candles(self, prices: list[float]) -> list[CandleData]:
        return [
            CandleData(open=p, high=p + 0.5, low=p - 0.5, close=p, volume=100.0)
            for p in prices
        ]

    def test_long_returns_level_below_price(self):
        candles = self._price_candles([100.0] * 15)
        level = find_key_liquidity_level(candles, Side.LONG)
        assert level < 100.0 or level == pytest.approx(99.5, abs=0.1)

    def test_short_returns_level_above_price(self):
        candles = self._price_candles([100.0] * 15)
        level = find_key_liquidity_level(candles, Side.SHORT)
        assert level >= 100.0

    def test_empty_returns_zero(self):
        assert find_key_liquidity_level([], Side.LONG) == 0.0
