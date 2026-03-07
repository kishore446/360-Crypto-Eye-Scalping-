"""Tests for bot/confluence_score.py"""
from __future__ import annotations

from bot.confluence_score import (
    WEIGHTS,
    ConfluenceFactors,
    build_confluence_factors,
    compute_confluence_score,
)
from bot.signal_engine import CandleData, Side


class TestComputeConfluenceScore:
    def test_all_true_returns_100(self):
        factors = ConfluenceFactors(
            macro_bias_aligned=True,
            in_discount_premium_zone=True,
            liquidity_swept=True,
            mss_confirmed=True,
            fvg_present=True,
            ob_present=True,
            session_active=True,
        )
        assert compute_confluence_score(factors) == 100

    def test_all_false_returns_zero(self):
        factors = ConfluenceFactors(
            macro_bias_aligned=False,
            in_discount_premium_zone=False,
            liquidity_swept=False,
            mss_confirmed=False,
            fvg_present=False,
            ob_present=False,
            session_active=False,
        )
        assert compute_confluence_score(factors) == 0

    def test_individual_weights(self):
        for key, weight in WEIGHTS.items():
            factors = ConfluenceFactors(**{key: True})
            assert compute_confluence_score(factors) == weight

    def test_partial_score(self):
        factors = ConfluenceFactors(
            macro_bias_aligned=True,
            liquidity_swept=True,
            mss_confirmed=True,
        )
        expected = WEIGHTS["macro_bias_aligned"] + WEIGHTS["liquidity_swept"] + WEIGHTS["mss_confirmed"]
        assert compute_confluence_score(factors) == expected


class TestBuildConfluenceFactors:
    def _bullish_candles(self, n: int = 20) -> list[CandleData]:
        return [
            CandleData(open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.5 + i, volume=1000.0)
            for i in range(n)
        ]

    def _bearish_candles(self, n: int = 20) -> list[CandleData]:
        return [
            CandleData(open=200.0 - i, high=201.0 - i, low=198.0 - i, close=198.5 - i, volume=1000.0)
            for i in range(n)
        ]

    def test_returns_confluence_factors(self):
        daily = self._bullish_candles(20)
        four_h = self._bullish_candles(5)
        five_m = [
            CandleData(open=100.0, high=101.0, low=99.0, close=100.5, volume=200.0)
            for _ in range(5)
        ]
        factors = build_confluence_factors(
            current_price=100.5,
            side=Side.LONG,
            range_low=95.0,
            range_high=110.0,
            key_liquidity_level=99.0,
            five_min_candles=five_m,
            daily_candles=daily,
            four_hour_candles=four_h,
            session_active=True,
        )
        assert isinstance(factors, ConfluenceFactors)
        assert factors.session_active is True

    def test_score_between_0_and_100(self):
        daily = self._bullish_candles(20)
        four_h = self._bullish_candles(5)
        five_m = [
            CandleData(open=100.0, high=101.0, low=99.0, close=100.5, volume=200.0)
            for _ in range(5)
        ]
        factors = build_confluence_factors(
            current_price=100.5,
            side=Side.LONG,
            range_low=95.0,
            range_high=110.0,
            key_liquidity_level=99.0,
            five_min_candles=five_m,
            daily_candles=daily,
            four_hour_candles=four_h,
        )
        score = compute_confluence_score(factors)
        assert 0 <= score <= 100
