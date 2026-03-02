"""
Tests for bot/signal_engine.py
"""

from __future__ import annotations

import pytest

from bot.signal_engine import (
    CandleData,
    Confidence,
    Side,
    SignalResult,
    _average_volume,
    assess_macro_bias,
    calculate_targets,
    detect_liquidity_sweep,
    detect_market_structure_shift,
    is_discount_zone,
    is_premium_zone,
    run_confluence_check,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _bullish_daily_candles(n: int = 20, base: float = 100.0) -> list[CandleData]:
    """Return *n* daily candles in a clear uptrend."""
    return [
        CandleData(
            open=base + i,
            high=base + i + 1,
            low=base + i - 0.5,
            close=base + i + 0.8,
            volume=1000.0,
        )
        for i in range(n)
    ]


def _bearish_daily_candles(n: int = 20, base: float = 200.0) -> list[CandleData]:
    """Return *n* daily candles in a clear downtrend."""
    return [
        CandleData(
            open=base - i,
            high=base - i + 0.5,
            low=base - i - 1,
            close=base - i - 0.8,
            volume=1000.0,
        )
        for i in range(n)
    ]


def _bullish_4h_candles(n: int = 5, base: float = 100.0) -> list[CandleData]:
    return [
        CandleData(open=base + i * 0.5, high=base + i * 0.5 + 0.3,
                   low=base + i * 0.5 - 0.3, close=base + i * 0.5 + 0.2,
                   volume=500.0)
        for i in range(n)
    ]


def _bearish_4h_candles(n: int = 5, base: float = 200.0) -> list[CandleData]:
    return [
        CandleData(open=base - i * 0.5, high=base - i * 0.5 + 0.3,
                   low=base - i * 0.5 - 0.3, close=base - i * 0.5 - 0.2,
                   volume=500.0)
        for i in range(n)
    ]


def _long_5m_candles(sweep_level: float = 99.0, base: float = 100.0) -> list[CandleData]:
    """5m candles that exhibit a liquidity sweep below sweep_level and a bullish MSS."""
    avg_vol = 200.0
    return [
        CandleData(open=base, high=base + 0.2, low=base - 0.2, close=base + 0.1, volume=avg_vol * 0.9),
        CandleData(open=base + 0.1, high=base + 0.3, low=base - 0.3, close=base + 0.2, volume=avg_vol * 0.8),
        # Sweep: low pierces sweep_level, close back above
        CandleData(open=base, high=base + 0.2, low=sweep_level - 0.1, close=sweep_level + 0.5, volume=avg_vol * 1.1),
        # MSS: close above prior swing high with high volume
        CandleData(open=base, high=base + 0.8, low=base - 0.1, close=base + 0.6, volume=avg_vol * 1.5),
    ]


def _short_5m_candles(sweep_level: float = 101.0, base: float = 100.0) -> list[CandleData]:
    """5m candles that exhibit a liquidity sweep above sweep_level and a bearish MSS."""
    avg_vol = 200.0
    return [
        CandleData(open=base, high=base + 0.2, low=base - 0.2, close=base - 0.1, volume=avg_vol * 0.9),
        CandleData(open=base - 0.1, high=base + 0.1, low=base - 0.3, close=base - 0.2, volume=avg_vol * 0.8),
        # Sweep: high pierces sweep_level, close back below
        CandleData(open=base, high=sweep_level + 0.1, low=base - 0.2, close=sweep_level - 0.5, volume=avg_vol * 1.1),
        # MSS: close below prior swing low with high volume
        CandleData(open=base, high=base + 0.1, low=base - 0.8, close=base - 0.6, volume=avg_vol * 1.5),
    ]


# ── Zone tests ────────────────────────────────────────────────────────────────

class TestZoneDetection:
    def test_discount_zone_below_midpoint(self):
        assert is_discount_zone(price=40.0, range_low=0.0, range_high=100.0) is True

    def test_discount_zone_at_midpoint(self):
        assert is_discount_zone(price=50.0, range_low=0.0, range_high=100.0) is True

    def test_discount_zone_above_midpoint(self):
        assert is_discount_zone(price=60.0, range_low=0.0, range_high=100.0) is False

    def test_premium_zone_above_midpoint(self):
        assert is_premium_zone(price=60.0, range_low=0.0, range_high=100.0) is True

    def test_premium_zone_at_midpoint(self):
        assert is_premium_zone(price=50.0, range_low=0.0, range_high=100.0) is True

    def test_premium_zone_below_midpoint(self):
        assert is_premium_zone(price=40.0, range_low=0.0, range_high=100.0) is False


# ── Liquidity Sweep tests ─────────────────────────────────────────────────────

class TestLiquiditySweep:
    def test_detects_bullish_sweep(self):
        """Low dips below key level, close above it — valid LONG sweep."""
        candles = [
            CandleData(open=100, high=101, low=99.5, close=100.5, volume=100),
        ]
        assert detect_liquidity_sweep(candles, key_level=100.0, side=Side.LONG) is True

    def test_no_sweep_when_close_below_level(self):
        """Low dips below level but close stays below — not a sweep."""
        candles = [
            CandleData(open=100, high=101, low=99.5, close=99.8, volume=100),
        ]
        assert detect_liquidity_sweep(candles, key_level=100.0, side=Side.LONG) is False

    def test_detects_bearish_sweep(self):
        """High pierces above key level, close below it — valid SHORT sweep."""
        candles = [
            CandleData(open=100, high=100.5, low=99, close=99.8, volume=100),
        ]
        assert detect_liquidity_sweep(candles, key_level=100.2, side=Side.SHORT) is True

    def test_no_sweep_when_close_above_level_short(self):
        candles = [
            CandleData(open=100, high=100.5, low=99, close=100.3, volume=100),
        ]
        assert detect_liquidity_sweep(candles, key_level=100.2, side=Side.SHORT) is False

    def test_empty_candles(self):
        assert detect_liquidity_sweep([], key_level=100.0, side=Side.LONG) is False


# ── MSS / ChoCh tests ─────────────────────────────────────────────────────────

class TestMarketStructureShift:
    def test_detects_bullish_mss(self):
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),
            CandleData(open=100.5, high=101.5, low=100, close=101, volume=90),
            # Last candle breaks prior swing high with higher volume
            CandleData(open=101, high=102.5, low=100.5, close=102, volume=200),
        ]
        assert detect_market_structure_shift(candles, Side.LONG) is True

    def test_no_mss_without_volume(self):
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=200),
            CandleData(open=100.5, high=101.5, low=100, close=101, volume=180),
            # Breaks swing high but volume is BELOW average
            CandleData(open=101, high=102.5, low=100.5, close=102, volume=50),
        ]
        assert detect_market_structure_shift(candles, Side.LONG) is False

    def test_detects_bearish_mss(self):
        candles = [
            CandleData(open=100, high=101, low=99, close=99.5, volume=100),
            CandleData(open=99.5, high=100, low=98.5, close=99, volume=90),
            # Last candle breaks prior swing low with higher volume
            CandleData(open=99, high=99.5, low=97.5, close=98, volume=200),
        ]
        assert detect_market_structure_shift(candles, Side.SHORT) is True

    def test_insufficient_candles(self):
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),
        ]
        assert detect_market_structure_shift(candles, Side.LONG) is False


# ── Macro Bias tests ──────────────────────────────────────────────────────────

class TestMacroBias:
    def test_bullish_bias_when_both_timeframes_agree(self):
        daily = _bullish_daily_candles()
        four_h = _bullish_4h_candles()
        assert assess_macro_bias(daily, four_h) == Side.LONG

    def test_bearish_bias_when_both_timeframes_agree(self):
        daily = _bearish_daily_candles()
        four_h = _bearish_4h_candles()
        assert assess_macro_bias(daily, four_h) == Side.SHORT

    def test_no_bias_when_timeframes_conflict(self):
        daily = _bullish_daily_candles()
        four_h = _bearish_4h_candles()
        assert assess_macro_bias(daily, four_h) is None

    def test_no_bias_insufficient_daily_data(self):
        daily = _bullish_daily_candles(n=5)
        four_h = _bullish_4h_candles()
        assert assess_macro_bias(daily, four_h) is None

    def test_no_bias_insufficient_4h_data(self):
        daily = _bullish_daily_candles()
        assert assess_macro_bias(daily, []) is None


# ── Target calculation tests ──────────────────────────────────────────────────

class TestCalculateTargets:
    def test_long_targets_are_above_entry(self):
        tp1, tp2, tp3 = calculate_targets(entry=100.0, stop_loss=98.0, side=Side.LONG)
        assert tp1 > 100.0
        assert tp2 > tp1
        assert tp3 > tp2

    def test_short_targets_are_below_entry(self):
        tp1, tp2, tp3 = calculate_targets(entry=100.0, stop_loss=102.0, side=Side.SHORT)
        assert tp1 < 100.0
        assert tp2 < tp1
        assert tp3 < tp2

    def test_long_tp1_rr_ratio(self):
        tp1, _, _ = calculate_targets(entry=100.0, stop_loss=98.0, side=Side.LONG, tp1_rr=1.5)
        # Risk = 2.0; TP1 should be 100 + 1.5 * 2 = 103.0
        assert abs(tp1 - 103.0) < 1e-9


# ── Signal Result formatting test ─────────────────────────────────────────────

class TestSignalResultFormatMessage:
    def test_message_contains_required_fields(self):
        result = SignalResult(
            symbol="BTC",
            side=Side.LONG,
            confidence=Confidence.HIGH,
            entry_low=64900.0,
            entry_high=65000.0,
            tp1=65750.0,
            tp2=66500.0,
            tp3=68000.0,
            stop_loss=64400.0,
            structure_note="4H Bullish OB + 5m MSS Confirmed.",
            context_note="BTC holding key VWAP; DXY showing weakness.",
            leverage_min=10,
            leverage_max=20,
        )
        msg = result.format_message()
        assert "#BTC/USDT" in msg
        assert "LONG" in msg
        assert "High" in msg
        assert "64900" in msg or "64,900" in msg
        assert "65750" in msg or "65,750" in msg
        assert "64400" in msg or "64,400" in msg
        assert "Cross 10x - 20x" in msg
        assert "CLICK TO COPY" in msg


# ── Full confluence check integration test ────────────────────────────────────

class TestRunConfluenceCheck:
    def _build_args(self, side: Side = Side.LONG) -> dict:
        base = 100.0
        sweep_level = base - 1.0 if side == Side.LONG else base + 1.0
        daily = _bullish_daily_candles() if side == Side.LONG else _bearish_daily_candles()
        four_h = _bullish_4h_candles() if side == Side.LONG else _bearish_4h_candles()
        five_m = _long_5m_candles(sweep_level=sweep_level) if side == Side.LONG else _short_5m_candles(sweep_level=sweep_level)
        stop_loss = sweep_level - 0.5 if side == Side.LONG else sweep_level + 0.5
        price = base - 2.5 if side == Side.LONG else base + 2.5
        range_low = base - 5.0
        range_high = base + 5.0
        return dict(
            symbol="ETH",
            current_price=price,
            side=side,
            range_low=range_low,
            range_high=range_high,
            key_liquidity_level=sweep_level,
            five_min_candles=five_m,
            daily_candles=daily,
            four_hour_candles=four_h,
            news_in_window=False,
            stop_loss=stop_loss,
        )

    def test_valid_long_signal_generated(self):
        kwargs = self._build_args(Side.LONG)
        result = run_confluence_check(**kwargs)
        assert result is not None
        assert result.side == Side.LONG
        assert result.symbol == "ETH"

    def test_valid_short_signal_generated(self):
        kwargs = self._build_args(Side.SHORT)
        result = run_confluence_check(**kwargs)
        assert result is not None
        assert result.side == Side.SHORT

    def test_news_freeze_blocks_signal(self):
        kwargs = self._build_args(Side.LONG)
        kwargs["news_in_window"] = True
        assert run_confluence_check(**kwargs) is None

    def test_wrong_zone_blocks_long(self):
        """A LONG signal should be blocked when price is in the premium zone."""
        kwargs = self._build_args(Side.LONG)
        # Move price above midpoint → premium zone → should block
        kwargs["range_low"] = 0.0
        kwargs["range_high"] = 100.0
        kwargs["current_price"] = 60.0  # above midpoint (50)
        result = run_confluence_check(**kwargs)
        assert result is None

    def test_macro_conflict_blocks_signal(self):
        """Conflicting daily/4H bias should block signal."""
        kwargs = self._build_args(Side.LONG)
        kwargs["four_hour_candles"] = _bearish_4h_candles()  # conflict
        assert run_confluence_check(**kwargs) is None


# ── _average_volume utility ───────────────────────────────────────────────────

class TestAverageVolume:
    def test_empty(self):
        assert _average_volume([]) == 0.0

    def test_single(self):
        c = CandleData(open=1, high=2, low=0.5, close=1.5, volume=200.0)
        assert _average_volume([c]) == 200.0

    def test_multiple(self):
        candles = [
            CandleData(open=1, high=2, low=0.5, close=1.5, volume=100.0),
            CandleData(open=1, high=2, low=0.5, close=1.5, volume=300.0),
        ]
        assert _average_volume(candles) == 200.0
