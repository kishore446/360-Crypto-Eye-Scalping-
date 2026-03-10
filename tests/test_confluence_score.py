"""Tests for bot/confluence_score.py"""
from __future__ import annotations

from bot.confluence_score import (
    MAX_RAW_SCORE,
    WEIGHTS,
    ConfluenceFactors,
    build_confluence_factors,
    compute_confluence_score,
)
from bot.signal_engine import CandleData, Side


def _normalise(raw: int) -> int:
    """Expected normalised score matching the formula in compute_confluence_score."""
    return round(raw * 100 / MAX_RAW_SCORE)


class TestComputeConfluenceScore:
    def test_all_original_factors_true(self):
        """All 7 original factors produce a normalised 0-100 score."""
        factors = ConfluenceFactors(
            macro_bias_aligned=True,
            in_discount_premium_zone=True,
            liquidity_swept=True,
            mss_confirmed=True,
            fvg_present=True,
            ob_present=True,
            session_active=True,
        )
        raw = (
            WEIGHTS["macro_bias_aligned"]
            + WEIGHTS["in_discount_premium_zone"]
            + WEIGHTS["liquidity_swept"]
            + WEIGHTS["mss_confirmed"]
            + WEIGHTS["fvg_present"]
            + WEIGHTS["ob_present"]
            + WEIGHTS["session_active"]
        )
        assert compute_confluence_score(factors) == _normalise(raw)

    def test_all_factors_true_returns_100(self):
        """All factors true → normalised score is 100."""
        factors = ConfluenceFactors(
            macro_bias_aligned=True,
            in_discount_premium_zone=True,
            liquidity_swept=True,
            mss_confirmed=True,
            fvg_present=True,
            ob_present=True,
            session_active=True,
            macd_confirmed=True,
            bb_squeeze=True,
            cvd_confirmed=True,
            ema_ribbon_aligned=True,
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

    def test_score_within_0_100(self):
        """Score must always be in [0, 100] regardless of inputs."""
        factors = ConfluenceFactors(**{k: True for k in WEIGHTS if WEIGHTS[k] > 0})
        score = compute_confluence_score(factors)
        assert 0 <= score <= 100

    def test_individual_weights_produce_normalised_scores(self):
        """Each single-factor score matches the normalised equivalent of its raw weight."""
        for key, weight in WEIGHTS.items():
            if weight == 0:
                continue  # skip zero-weight tracking fields
            factors = ConfluenceFactors(**{key: True})
            assert compute_confluence_score(factors) == _normalise(weight), (
                f"Factor '{key}' (raw weight {weight}): expected normalised "
                f"{_normalise(weight)}, got {compute_confluence_score(factors)}"
            )

    def test_partial_score(self):
        factors = ConfluenceFactors(
            macro_bias_aligned=True,
            liquidity_swept=True,
            mss_confirmed=True,
        )
        raw = WEIGHTS["macro_bias_aligned"] + WEIGHTS["liquidity_swept"] + WEIGHTS["mss_confirmed"]
        assert compute_confluence_score(factors) == _normalise(raw)

    def test_new_indicator_weights(self):
        """New indicator fields each contribute their normalised weight to the score."""
        for key in ("macd_confirmed", "bb_squeeze", "cvd_confirmed", "ema_ribbon_aligned"):
            factors = ConfluenceFactors(**{key: True})
            assert compute_confluence_score(factors) == _normalise(WEIGHTS[key]), (
                f"Factor '{key}' normalised score mismatch"
            )


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

    def test_score_non_negative(self):
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
        assert score >= 0
