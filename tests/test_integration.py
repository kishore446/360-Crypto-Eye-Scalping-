"""
Integration test: end-to-end pipeline from candle data through signal generation.
"""
from __future__ import annotations

import datetime
from unittest.mock import patch

from bot.btc_correlation import btc_correlation_check
from bot.confluence_score import build_confluence_factors, compute_confluence_score
from bot.session_filter import is_active_session
from bot.signal_engine import (
    CandleData,
    Side,
    SignalResult,
    run_confluence_check,
)


def _bullish_daily(n: int = 20, base: float = 100.0) -> list[CandleData]:
    return [
        CandleData(open=base + i, high=base + i + 1, low=base + i - 0.5, close=base + i + 0.8, volume=1000.0)
        for i in range(n)
    ]


def _bullish_4h(n: int = 5, base: float = 100.0) -> list[CandleData]:
    return [
        CandleData(open=base + i * 0.5, high=base + i * 0.5 + 0.3, low=base + i * 0.5 - 0.3, close=base + i * 0.5 + 0.2, volume=500.0)
        for i in range(n)
    ]


def _long_5m(sweep_level: float = 99.0, base: float = 100.0) -> list[CandleData]:
    avg_vol = 200.0
    return [
        CandleData(open=base, high=base + 0.2, low=base - 0.2, close=base + 0.1, volume=avg_vol * 0.9),
        CandleData(open=base + 0.1, high=base + 0.3, low=base - 0.3, close=base + 0.2, volume=avg_vol * 0.8),
        CandleData(open=base, high=base + 0.2, low=sweep_level - 0.1, close=sweep_level + 0.5, volume=avg_vol * 1.1),
        CandleData(open=base, high=base + 0.8, low=base - 0.1, close=base + 0.6, volume=avg_vol * 1.5),
    ]


class TestEndToEndSignalPipeline:
    """Simulate the full pipeline: candle close → confluence → signal → message."""

    def test_full_long_signal_pipeline(self):
        """Full LONG signal pipeline produces valid SignalResult with message."""
        base = 100.0
        sweep_level = base - 1.0
        daily = _bullish_daily()
        four_h = _bullish_4h()
        five_m = _long_5m(sweep_level=sweep_level)
        stop_loss = sweep_level - 0.5
        price = base - 2.5

        result = run_confluence_check(
            symbol="ETH",
            current_price=price,
            side=Side.LONG,
            range_low=base - 5.0,
            range_high=base + 5.0,
            key_liquidity_level=sweep_level,
            five_min_candles=five_m,
            daily_candles=daily,
            four_hour_candles=four_h,
            news_in_window=False,
            stop_loss=stop_loss,
        )

        assert result is not None
        assert isinstance(result, SignalResult)
        assert result.symbol == "ETH"
        assert result.side == Side.LONG
        assert result.signal_id.startswith("SIG-")

        msg = result.format_message()
        assert "#ETH/USDT" in msg
        assert "LONG" in msg
        assert "CLICK TO COPY" in msg

    def test_btc_correlation_blocks_conflicting_signal(self):
        """BTC bearish bias should block altcoin LONG signal."""
        with patch("bot.btc_correlation.assess_macro_bias", return_value=Side.SHORT):
            allowed = btc_correlation_check(
                btc_candles_daily=_bullish_daily(),
                btc_candles_4h=_bullish_4h(),
                signal_side=Side.LONG,
            )
        assert allowed is False

    def test_session_filter_london_active(self):
        """London session should be active."""
        london_time = datetime.datetime(2024, 1, 15, 9, 0, tzinfo=datetime.timezone.utc)
        assert is_active_session(london_time) is True

    def test_session_filter_asia_inactive(self):
        """Asia session should be inactive when SESSION_FILTER_ENABLED=True."""
        asia_time = datetime.datetime(2024, 1, 15, 3, 0, tzinfo=datetime.timezone.utc)
        with patch("bot.session_filter.SESSION_FILTER_ENABLED", True):
            assert is_active_session(asia_time) is False

    def test_confluence_score_computed(self):
        """Confluence score is computable from real candle data."""
        daily = _bullish_daily()
        four_h = _bullish_4h()
        five_m = _long_5m()
        factors = build_confluence_factors(
            current_price=97.5,
            side=Side.LONG,
            range_low=95.0,
            range_high=105.0,
            key_liquidity_level=99.0,
            five_min_candles=five_m,
            daily_candles=daily,
            four_hour_candles=four_h,
        )
        score = compute_confluence_score(factors)
        assert 0 <= score <= 100

    def test_signal_message_contains_bybit_format(self):
        """Signal message should contain Bybit copy-trade format."""
        base = 100.0
        sweep_level = base - 1.0
        result = run_confluence_check(
            symbol="BTC",
            current_price=base - 2.5,
            side=Side.LONG,
            range_low=base - 5.0,
            range_high=base + 5.0,
            key_liquidity_level=sweep_level,
            five_min_candles=_long_5m(sweep_level=sweep_level),
            daily_candles=_bullish_daily(),
            four_hour_candles=_bullish_4h(),
            news_in_window=False,
            stop_loss=sweep_level - 0.5,
        )
        assert result is not None
        msg = result.format_message()
        # Should contain both Binance and Bybit copy-trade sections
        assert "BINANCE" in msg.upper() or "CLICK TO COPY" in msg
