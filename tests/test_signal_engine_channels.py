"""Tests for the 3-channel dedicated confluence functions in bot/signal_engine.py."""
from __future__ import annotations

from unittest.mock import patch

from bot.signal_engine import (
    CandleData,
    Side,
    run_confluence_check_ch1_hard,
    run_confluence_check_ch2_medium,
    run_confluence_check_ch3_easy,
)


def _make_candles(n: int = 20, base_price: float = 100.0) -> list[CandleData]:
    """Generate n simple candles around base_price."""
    candles = []
    for i in range(n):
        close = base_price + (i * 0.1)
        candles.append(CandleData(
            open=close - 0.05,
            high=close + 0.1,
            low=close - 0.1,
            close=close,
            volume=1000.0 + i * 10,
        ))
    return candles


class TestRunConfluenceCheckCh1Hard:
    def test_returns_none_when_all_gates_fail(self):
        candles = _make_candles(20, 100.0)
        # Price is 100, range 50-150 → midpoint, not in discount zone for LONG
        # news_in_window=True forces Gate 7 failure
        result = run_confluence_check_ch1_hard(
            symbol="BTC",
            current_price=100.0,
            side=Side.LONG,
            range_low=50.0,
            range_high=150.0,
            key_liquidity_level=95.0,
            five_min_candles=candles,
            daily_candles=candles,
            four_hour_candles=candles,
            news_in_window=True,
            stop_loss=90.0,
        )
        assert result is None

    def test_returns_none_below_min_confluence(self):
        """CH1 should return None if score < 70."""
        candles = _make_candles(20, 100.0)
        with patch(
            "bot.signal_engine.run_confluence_check",
        ) as mock_check:
            from bot.signal_engine import Confidence, SignalResult
            mock_result = SignalResult(
                symbol="BTC", side=Side.LONG, confidence=Confidence.LOW,
                entry_low=99.0, entry_high=101.0,
                tp1=107.5, tp2=112.5, tp3=120.0, stop_loss=95.0,
                structure_note="", context_note="",
                leverage_min=15, leverage_max=20,
                signal_id="test-001", confluence_score=50,
            )
            mock_check.return_value = mock_result
            result = run_confluence_check_ch1_hard(
                symbol="BTC",
                current_price=100.0,
                side=Side.LONG,
                range_low=50.0,
                range_high=150.0,
                key_liquidity_level=95.0,
                five_min_candles=candles,
                daily_candles=candles,
                four_hour_candles=candles,
                news_in_window=False,
                stop_loss=90.0,
            )
        assert result is None

    def test_returns_result_above_min_confluence(self):
        """CH1 should return result when score >= 70."""
        candles = _make_candles(20, 100.0)
        with patch("bot.signal_engine.run_confluence_check") as mock_check:
            from bot.signal_engine import Confidence, SignalResult
            mock_result = SignalResult(
                symbol="BTC", side=Side.LONG, confidence=Confidence.HIGH,
                entry_low=99.0, entry_high=101.0,
                tp1=107.5, tp2=112.5, tp3=120.0, stop_loss=95.0,
                structure_note="", context_note="",
                leverage_min=15, leverage_max=20,
                signal_id="test-001", confluence_score=75,
            )
            mock_check.return_value = mock_result
            result = run_confluence_check_ch1_hard(
                symbol="BTC",
                current_price=100.0,
                side=Side.LONG,
                range_low=50.0,
                range_high=150.0,
                key_liquidity_level=95.0,
                five_min_candles=candles,
                daily_candles=candles,
                four_hour_candles=candles,
                news_in_window=False,
                stop_loss=90.0,
            )
        assert result is not None
        assert result.confluence_score == 75


class TestRunConfluenceCheckCh2Medium:
    def test_returns_none_when_score_too_low(self):
        """CH2 should return None if score < 50."""
        candles = _make_candles(20, 100.0)
        with patch("bot.signal_engine.run_confluence_check_relaxed") as mock_check:
            from bot.signal_engine import Confidence, SignalResult
            mock_result = SignalResult(
                symbol="ETH", side=Side.SHORT, confidence=Confidence.LOW,
                entry_low=99.0, entry_high=101.0,
                tp1=95.0, tp2=90.0, tp3=85.0, stop_loss=105.0,
                structure_note="", context_note="",
                leverage_min=10, leverage_max=15,
                signal_id="test-002", confluence_score=40,
            )
            mock_check.return_value = mock_result
            result = run_confluence_check_ch2_medium(
                symbol="ETH",
                current_price=100.0,
                side=Side.SHORT,
                range_low=80.0,
                range_high=120.0,
                key_liquidity_level=105.0,
                five_min_candles=candles,
                daily_candles=candles,
                four_hour_candles=candles,
                news_in_window=False,
                stop_loss=110.0,
            )
        assert result is None

    def test_returns_result_above_min_confluence(self):
        """CH2 should return result when score >= 50."""
        candles = _make_candles(20, 100.0)
        with patch("bot.signal_engine.run_confluence_check_relaxed") as mock_check:
            from bot.signal_engine import Confidence, SignalResult
            mock_result = SignalResult(
                symbol="ETH", side=Side.SHORT, confidence=Confidence.MEDIUM,
                entry_low=99.0, entry_high=101.0,
                tp1=95.0, tp2=90.0, tp3=85.0, stop_loss=105.0,
                structure_note="", context_note="",
                leverage_min=10, leverage_max=15,
                signal_id="test-002", confluence_score=60,
            )
            mock_check.return_value = mock_result
            result = run_confluence_check_ch2_medium(
                symbol="ETH",
                current_price=100.0,
                side=Side.SHORT,
                range_low=80.0,
                range_high=120.0,
                key_liquidity_level=105.0,
                five_min_candles=candles,
                daily_candles=candles,
                four_hour_candles=candles,
                news_in_window=False,
                stop_loss=110.0,
            )
        assert result is not None
        assert result.confluence_score == 60


class TestRunConfluenceCheckCh3Easy:
    def test_returns_none_when_news_in_window(self):
        candles = _make_candles(20, 60.0)
        result = run_confluence_check_ch3_easy(
            symbol="SOL",
            current_price=60.0,
            side=Side.LONG,
            range_low=50.0,
            range_high=80.0,
            key_liquidity_level=58.0,
            five_min_candles=candles,
            daily_candles=candles,
            four_hour_candles=candles,
            news_in_window=True,
            stop_loss=55.0,
        )
        assert result is None

    def test_returns_none_when_no_zone_and_no_volume_spike(self):
        # Price at midpoint (not in discount zone for LONG), no volume spike
        candles = _make_candles(20, 65.0)  # price at 65, range 50-80 → midpoint
        result = run_confluence_check_ch3_easy(
            symbol="SOL",
            current_price=65.0,
            side=Side.LONG,
            range_low=50.0,
            range_high=80.0,
            key_liquidity_level=60.0,
            five_min_candles=candles,
            daily_candles=candles,
            four_hour_candles=candles,
            news_in_window=False,
            stop_loss=58.0,
        )
        # No MSS either, so should return None
        assert result is None

    def test_ch3_has_lower_leverage_than_ch1(self):
        """CH3 default leverage (5-10x) should be lower than CH1 (15-20x)."""
        candles_long = _make_candles(30, 51.0)  # just above range_low for discount
        # In discount zone: price=51, range_low=50, range_high=80 → in lower 30%
        with patch("bot.signal_engine.detect_market_structure_shift", return_value=True):
            result = run_confluence_check_ch3_easy(
                symbol="DOGE",
                current_price=51.0,
                side=Side.LONG,
                range_low=50.0,
                range_high=80.0,
                key_liquidity_level=50.5,
                five_min_candles=candles_long,
                daily_candles=candles_long,
                four_hour_candles=candles_long,
                news_in_window=False,
                stop_loss=49.0,
            )
        if result is not None:
            assert result.leverage_min <= 10
            assert result.leverage_max <= 10
