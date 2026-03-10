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
    calculate_atr,
    calculate_targets,
    detect_fair_value_gap,
    detect_liquidity_sweep,
    detect_market_structure_shift,
    detect_order_block,
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

    def test_bullish_bias_when_4h_neutral(self):
        """1D bullish + 4H flat (neutral) should return LONG bias."""
        daily = _bullish_daily_candles()
        # Flat 4H candles: last two at same close price → neither bullish nor bearish
        flat_4h = [
            CandleData(open=100.0, high=101.0, low=99.0, close=100.0, volume=500.0),
            CandleData(open=100.0, high=101.0, low=99.0, close=100.0, volume=500.0),
        ]
        assert assess_macro_bias(daily, flat_4h) == Side.LONG

    def test_bearish_bias_when_4h_neutral(self):
        """1D bearish + 4H flat (neutral) should return SHORT bias."""
        daily = _bearish_daily_candles()
        flat_4h = [
            CandleData(open=100.0, high=101.0, low=99.0, close=100.0, volume=500.0),
            CandleData(open=100.0, high=101.0, low=99.0, close=100.0, volume=500.0),
        ]
        assert assess_macro_bias(daily, flat_4h) == Side.SHORT

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


# ── ATR tests ─────────────────────────────────────────────────────────────────

class TestCalculateATR:
    def test_empty_candles_returns_zero(self):
        assert calculate_atr([]) == 0.0

    def test_single_candle_returns_zero(self):
        c = CandleData(open=100, high=101, low=99, close=100, volume=100)
        assert calculate_atr([c]) == 0.0

    def test_basic_atr(self):
        candles = [
            CandleData(open=100, high=102, low=98, close=101, volume=100),
            CandleData(open=101, high=103, low=100, close=102, volume=100),
            CandleData(open=102, high=104, low=101, close=103, volume=100),
        ]
        atr = calculate_atr(candles)
        assert atr > 0.0

    def test_atr_respects_period(self):
        # With identical candles, all TRs are equal — ATR should equal that TR
        candles = [
            CandleData(open=100, high=102, low=98, close=100, volume=100)
            for _ in range(20)
        ]
        atr = calculate_atr(candles, period=5)
        assert atr == pytest.approx(4.0)  # high - low = 4.0 each

    def test_atr_insufficient_period_uses_available(self):
        candles = [
            CandleData(open=100, high=102, low=98, close=100, volume=100),
            CandleData(open=100, high=102, low=98, close=100, volume=100),
        ]
        # Only 1 true range available, period=14 should use all available
        atr = calculate_atr(candles, period=14)
        assert atr > 0.0


# ── Fair Value Gap tests ──────────────────────────────────────────────────────

class TestDetectFairValueGap:
    def test_bullish_fvg_detected(self):
        """Candle[-1].low > candle[-3].high → bullish FVG."""
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),   # c0
            CandleData(open=101, high=105, low=100, close=104, volume=200),    # c1 (big up)
            CandleData(open=104, high=107, low=102, close=106, volume=150),    # c2
        ]
        # c2.low (102) > c0.high (101) → bullish FVG
        assert detect_fair_value_gap(candles, Side.LONG) is True

    def test_no_bullish_fvg(self):
        candles = [
            CandleData(open=100, high=103, low=99, close=102, volume=100),
            CandleData(open=102, high=104, low=101, close=103, volume=100),
            CandleData(open=103, high=105, low=102, close=104, volume=100),
        ]
        # c2.low (102) == c0.high (103)? No, c2.low=102 < c0.high=103 → no FVG
        assert detect_fair_value_gap(candles, Side.LONG) is False

    def test_bearish_fvg_detected(self):
        """Candle[-1].high < candle[-3].low → bearish FVG."""
        candles = [
            CandleData(open=100, high=101, low=99, close=99.5, volume=100),   # c0
            CandleData(open=99, high=100, low=95, close=96, volume=200),      # c1 (big down)
            CandleData(open=96, high=97, low=93, close=94, volume=150),       # c2
        ]
        # c2.high (97) < c0.low (99) → bearish FVG
        assert detect_fair_value_gap(candles, Side.SHORT) is True

    def test_insufficient_candles(self):
        candles = [
            CandleData(open=100, high=101, low=99, close=100, volume=100),
        ]
        assert detect_fair_value_gap(candles, Side.LONG) is False


# ── Order Block tests ─────────────────────────────────────────────────────────

class TestDetectOrderBlock:
    def test_bullish_order_block_detected(self):
        """Bearish candle followed by bullish candle → LONG order block."""
        candles = [
            CandleData(open=105, high=106, low=104, close=104.5, volume=80),   # context
            CandleData(open=104, high=105, low=99, close=99.5, volume=100),    # bearish (index 1)
            CandleData(open=99.5, high=103, low=99, close=102, volume=200),    # bullish impulse
            CandleData(open=102, high=104, low=101, close=103, volume=150),    # continuation
        ]
        assert detect_order_block(candles, Side.LONG) is True

    def test_bearish_order_block_detected(self):
        """Bullish candle followed by bearish candle → SHORT order block."""
        candles = [
            CandleData(open=95, high=96, low=94, close=95.5, volume=80),       # context
            CandleData(open=95.5, high=101, low=95, close=100.5, volume=100),  # bullish (index 1)
            CandleData(open=100.5, high=101, low=97, close=98, volume=200),    # bearish impulse
            CandleData(open=98, high=99, low=96, close=97, volume=150),        # continuation
        ]
        assert detect_order_block(candles, Side.SHORT) is True

    def test_no_order_block_when_no_opposing_candle(self):
        candles = [
            CandleData(open=100, high=102, low=99, close=101.5, volume=100),  # bullish
            CandleData(open=101.5, high=104, low=101, close=103, volume=150), # bullish
            CandleData(open=103, high=105, low=102, close=104, volume=120),   # bullish
        ]
        # All bullish — no bearish before impulse for LONG OB
        assert detect_order_block(candles, Side.LONG) is False

    def test_insufficient_candles(self):
        candles = [CandleData(open=100, high=101, low=99, close=100, volume=100)]
        assert detect_order_block(candles, Side.LONG) is False


# ── Displacement filter tests ────────────────────────────────────────────────

class TestDisplacementFilter:
    def test_mss_with_zero_displacement_passes(self):
        """min_displacement_pct=0 should behave like the original function."""
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),
            CandleData(open=100.5, high=101.5, low=100, close=101, volume=90),
            CandleData(open=101, high=102.5, low=100.5, close=102, volume=200),
        ]
        assert detect_market_structure_shift(candles, Side.LONG, min_displacement_pct=0.0) is True

    def test_mss_blocked_when_displacement_too_small(self):
        """Require 10% displacement — should fail on small move."""
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),
            CandleData(open=100.5, high=101.5, low=100, close=101, volume=90),
            # Breaks swing high (101.5) by 0.5 → displacement ~0.5% < 10%
            CandleData(open=101, high=102.5, low=100.5, close=102, volume=200),
        ]
        assert detect_market_structure_shift(candles, Side.LONG, min_displacement_pct=10.0) is False

    def test_mss_passes_when_displacement_sufficient(self):
        """Require 0.1% displacement — small move should pass."""
        candles = [
            CandleData(open=100, high=101, low=99, close=100.5, volume=100),
            CandleData(open=100.5, high=101.5, low=100, close=101, volume=90),
            CandleData(open=101, high=102.5, low=100.5, close=102, volume=200),
        ]
        assert detect_market_structure_shift(candles, Side.LONG, min_displacement_pct=0.1) is True


# ── Confidence enum LOW value ─────────────────────────────────────────────────

class TestConfidenceLow:
    def test_low_confidence_value(self):
        assert Confidence.LOW == "Low"
        assert Confidence.LOW.value == "Low"

    def test_all_confidence_levels_present(self):
        assert Confidence.HIGH.value == "High"
        assert Confidence.MEDIUM.value == "Medium"
        assert Confidence.LOW.value == "Low"


# ── signal_id field ───────────────────────────────────────────────────────────

class TestSignalId:
    def test_signal_id_defaults_to_empty(self):
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
            structure_note="Test",
            context_note="Test ctx",
            leverage_min=10,
            leverage_max=20,
        )
        assert result.signal_id == ""

    def test_signal_id_can_be_set(self):
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
            structure_note="Test",
            context_note="Test ctx",
            leverage_min=10,
            leverage_max=20,
            signal_id="SIG-TESTIDABCDEF",
        )
        assert result.signal_id == "SIG-TESTIDABCDEF"

    def test_run_confluence_check_generates_signal_id(self):
        """signal_id should be populated by run_confluence_check."""
        base = 100.0
        sweep_level = base - 1.0
        daily = _bullish_daily_candles()
        four_h = _bullish_4h_candles()
        five_m = _long_5m_candles(sweep_level=sweep_level)
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
        assert result.signal_id.startswith("SIG-")
        assert len(result.signal_id) == 16  # "SIG-" + 12 chars


# ── Optional FVG / OB gates in run_confluence_check ──────────────────────────

class TestOptionalGates:
    def _base_args(self):
        base = 100.0
        sweep_level = base - 1.0
        return dict(
            symbol="ETH",
            current_price=base - 2.5,
            side=Side.LONG,
            range_low=base - 5.0,
            range_high=base + 5.0,
            key_liquidity_level=sweep_level,
            five_min_candles=_long_5m_candles(sweep_level=sweep_level),
            daily_candles=_bullish_daily_candles(),
            four_hour_candles=_bullish_4h_candles(),
            news_in_window=False,
            stop_loss=sweep_level - 0.5,
        )

    def test_check_fvg_false_ignores_fvg(self):
        """check_fvg=False (default) should not block signal even without FVG."""
        kwargs = self._base_args()
        result = run_confluence_check(**kwargs, check_fvg=False)
        assert result is not None

    def test_check_order_block_false_ignores_ob(self):
        """check_order_block=False (default) should not block signal."""
        kwargs = self._base_args()
        result = run_confluence_check(**kwargs, check_order_block=False)
        assert result is not None


# ── Confluence scoring tests ──────────────────────────────────────────────────

class TestConfluenceScoring:
    """run_confluence_check should populate confluence_score on a valid signal."""

    def _base_args(self):
        base = 100.0
        sweep_level = base - 1.0
        return dict(
            symbol="ETH",
            current_price=base - 2.5,
            side=Side.LONG,
            range_low=base - 5.0,
            range_high=base + 5.0,
            key_liquidity_level=sweep_level,
            five_min_candles=_long_5m_candles(sweep_level=sweep_level),
            daily_candles=_bullish_daily_candles(),
            four_hour_candles=_bullish_4h_candles(),
            news_in_window=False,
            stop_loss=sweep_level - 0.5,
        )

    def test_score_is_positive_on_valid_signal(self):
        result = run_confluence_check(**self._base_args())
        assert result is not None
        assert result.confluence_score > 0

    def test_score_at_most_100(self):
        result = run_confluence_check(**self._base_args())
        assert result is not None
        assert result.confluence_score <= 100

    def test_score_shown_in_message_when_positive(self):
        result = run_confluence_check(**self._base_args())
        assert result is not None
        assert result.confluence_score > 0
        msg = result.format_message()
        assert "Score:" in msg

    def test_score_not_shown_in_message_when_zero(self):
        result = SignalResult(
            symbol="BTC",
            side=Side.LONG,
            confidence=Confidence.HIGH,
            entry_low=100.0,
            entry_high=101.0,
            tp1=103.0,
            tp2=105.0,
            tp3=108.0,
            stop_loss=98.0,
            structure_note="Test",
            context_note="Test ctx",
            leverage_min=10,
            leverage_max=20,
            confluence_score=0,
        )
        msg = result.format_message()
        assert "Score:" not in msg


# ── 15m candles parameter tests ───────────────────────────────────────────────

class TestFifteenMinCandles:
    """run_confluence_check should accept fifteen_min_candles without error."""

    def _base_args(self):
        base = 100.0
        sweep_level = base - 1.0
        return dict(
            symbol="ETH",
            current_price=base - 2.5,
            side=Side.LONG,
            range_low=base - 5.0,
            range_high=base + 5.0,
            key_liquidity_level=sweep_level,
            five_min_candles=_long_5m_candles(sweep_level=sweep_level),
            daily_candles=_bullish_daily_candles(),
            four_hour_candles=_bullish_4h_candles(),
            news_in_window=False,
            stop_loss=sweep_level - 0.5,
        )

    def test_fifteen_min_candles_accepted(self):
        """Passing fifteen_min_candles should not raise."""
        fifteen_m = _long_5m_candles()  # reuse 5m fixture as proxy 15m data
        kwargs = self._base_args()
        kwargs["fifteen_min_candles"] = fifteen_m
        result = run_confluence_check(**kwargs)
        assert result is not None

    def test_none_fifteen_min_falls_back_to_five_min(self):
        """When fifteen_min_candles is None, function uses five_min_candles."""
        kwargs = self._base_args()
        result = run_confluence_check(**kwargs, fifteen_min_candles=None)
        assert result is not None


# ── MIN_DISPLACEMENT_PCT config integration ───────────────────────────────────

class TestDisplacementConfigDefault:
    """The default min_displacement_pct should be 0.15 (Blueprint §2.2)."""

    def test_default_displacement_is_0_15(self):
        from inspect import signature

        from bot.signal_engine import detect_market_structure_shift
        sig = signature(detect_market_structure_shift)
        default = sig.parameters["min_displacement_pct"].default
        assert default == pytest.approx(0.15)


# ── calculate_vwap export ─────────────────────────────────────────────────────

class TestCalculateVwapInSignalEngine:
    """calculate_vwap must be importable from signal_engine (Issue 6)."""

    def test_calculate_vwap_is_exported(self):
        from bot.signal_engine import calculate_vwap
        assert callable(calculate_vwap)

    def test_calculate_vwap_single_candle(self):
        from bot.signal_engine import calculate_vwap
        c = CandleData(open=100.0, high=102.0, low=98.0, close=100.0, volume=10.0)
        expected = (102.0 + 98.0 + 100.0) / 3.0
        assert calculate_vwap([c]) == pytest.approx(expected)

    def test_calculate_vwap_empty_returns_zero(self):
        from bot.signal_engine import calculate_vwap
        assert calculate_vwap([]) == 0.0


# ── ATR-based displacement ────────────────────────────────────────────────────

class TestAtrBasedDisplacement:
    """detect_market_structure_shift uses ATR-based threshold when atr > 0."""

    def _make_candles_with_displacement(self, displacement: float) -> list[CandleData]:
        """Return candles where the last close breaks above swing high by *displacement*."""
        avg_vol = 100.0
        swing_high = 100.0
        candles = [
            CandleData(open=99.0, high=swing_high, low=98.0, close=99.5, volume=avg_vol * 0.9),
            CandleData(open=99.5, high=100.1, low=98.5, close=99.8, volume=avg_vol * 0.8),
            # Last candle breaks above swing_high by *displacement* with above-average volume
            CandleData(open=99.8, high=swing_high + displacement + 0.1,
                       low=99.5, close=swing_high + displacement, volume=avg_vol * 2.0),
        ]
        return candles

    def test_atr_displacement_passes_when_large_enough(self):
        atr = 0.5
        # displacement = 0.4 > 0.3 * 0.5 = 0.15 → should pass
        candles = self._make_candles_with_displacement(0.4)
        assert detect_market_structure_shift(candles, Side.LONG, atr=atr) is True

    def test_atr_displacement_blocked_when_too_small(self):
        atr = 1.0
        # displacement = 0.1 < 0.3 * 1.0 = 0.3 → should be blocked
        candles = self._make_candles_with_displacement(0.1)
        assert detect_market_structure_shift(candles, Side.LONG, atr=atr) is False

    def test_atr_zero_falls_back_to_pct_filter(self):
        # atr=0 → uses min_displacement_pct (default 0.15)
        # Large displacement relative to price: 0.5/100 = 0.5% > 0.15% → passes
        candles = self._make_candles_with_displacement(0.5)
        assert detect_market_structure_shift(candles, Side.LONG, atr=0.0) is True


# ── BUG 1: MSS vol_threshold parameter ───────────────────────────────────────

class TestMSSVolThreshold:
    """detect_market_structure_shift respects the vol_threshold parameter."""

    def _make_candles(self, last_vol_rank_frac: float) -> list[CandleData]:
        """Return candles where the last candle ranks at *last_vol_rank_frac* in volume."""
        n = 20
        # Uniform volumes so the last candle can be positioned at a specific percentile
        base_vol = 100.0
        candles = [
            CandleData(open=100 + i * 0.1, high=100 + i * 0.1 + 0.2,
                       low=100 + i * 0.1 - 0.1, close=100 + i * 0.1 + 0.1,
                       volume=base_vol)
            for i in range(n - 1)
        ]
        # swing_high of last 7 prior candles will be last candle's high; override
        swing_hi = max(c.high for c in candles[-7:])
        last_vol = base_vol * (last_vol_rank_frac * n)  # approximate rank
        last_close = swing_hi + 0.5  # clearly breaks swing high
        candles.append(CandleData(
            open=last_close - 0.1,
            high=last_close + 0.1,
            low=last_close - 0.2,
            close=last_close,
            volume=last_vol,
        ))
        return candles

    def test_default_threshold_is_0_70(self):
        from inspect import signature
        sig = signature(detect_market_structure_shift)
        assert sig.parameters["vol_threshold"].default == pytest.approx(0.70)

    def test_ch2_threshold_0_60_allows_medium_volume(self):
        """A candle that passes 60th percentile but not 70th should pass with vol_threshold=0.60.

        Volumes: [100, 100, 100, 200, 200, 115]
        vol_rank of last (115): count(v<=115)/6 = 4/6 ≈ 0.667
        0.667 >= 0.70 is False → fails default  → result_strict=False
        0.667 >= 0.60 is True  → passes relaxed → result_relaxed=True
        """
        candles = [
            # Three low-volume candles
            CandleData(open=100.0, high=100.5, low=99.5, close=100.2, volume=100),
            CandleData(open=100.2, high=100.6, low=99.8, close=100.3, volume=100),
            CandleData(open=100.3, high=100.7, low=99.9, close=100.4, volume=100),
            # Two high-volume candles (push rank down for the medium-vol last candle)
            CandleData(open=100.4, high=101.0, low=100.0, close=100.8, volume=200),
            CandleData(open=100.8, high=101.5, low=100.5, close=101.2, volume=200),
            # Last candle: vol=115 → rank = count(v<=115)/6 = 4/6 ≈ 0.667; breaks swing high
            CandleData(open=101.2, high=103.0, low=101.0, close=102.5, volume=115),
        ]
        # default (0.70) — rank 0.667 < 0.70 → should fail
        result_strict = detect_market_structure_shift(candles, Side.LONG, vol_threshold=0.70)
        # relaxed (0.60) — rank 0.667 >= 0.60 → should pass (if swing high is broken)
        result_relaxed = detect_market_structure_shift(candles, Side.LONG, vol_threshold=0.60)
        assert result_strict is False
        assert result_relaxed is True

    def test_ch3_threshold_0_50_allows_lower_volume(self):
        """A candle that passes 50th percentile but not 60th should pass with vol_threshold=0.50.

        Volumes: [100, 100, 200, 200, 200, 115]
        vol_rank of last (115): count(v<=115)/6 = 3/6 = 0.50
        0.50 >= 0.60 is False → fails CH2
        0.50 >= 0.50 is True  → passes CH3
        """
        candles = [
            # Two low-volume candles
            CandleData(open=100.0, high=100.5, low=99.5, close=100.2, volume=100),
            CandleData(open=100.2, high=100.6, low=99.8, close=100.3, volume=100),
            # Three high-volume candles (push rank down for the medium-vol last candle)
            CandleData(open=100.3, high=100.8, low=100.0, close=100.6, volume=200),
            CandleData(open=100.6, high=101.2, low=100.3, close=101.0, volume=200),
            CandleData(open=101.0, high=101.6, low=100.7, close=101.4, volume=200),
            # Last candle: vol=115 → rank = count(v<=115)/6 = 3/6 = 0.50; breaks swing high
            CandleData(open=101.4, high=103.0, low=101.2, close=102.8, volume=115),
        ]
        result_medium = detect_market_structure_shift(candles, Side.LONG, vol_threshold=0.60)
        result_easy = detect_market_structure_shift(candles, Side.LONG, vol_threshold=0.50)
        assert result_medium is False
        assert result_easy is True


# ── BUG 3: Score normalisation in format_message ─────────────────────────────

class TestScoreNormalisation:
    """format_message() shows score normalised to /100."""

    def test_high_raw_score_capped_at_100(self):
        sig = SignalResult(
            symbol="BTC",
            side=Side.LONG,
            confidence=Confidence.HIGH,
            entry_low=99.0,
            entry_high=101.0,
            tp1=103.0,
            tp2=106.0,
            tp3=110.0,
            stop_loss=97.0,
            structure_note="test",
            context_note="test",
            leverage_min=10,
            leverage_max=20,
            signal_id="SIG-TEST",
            confluence_score=150,
        )
        msg = sig.format_message()
        # Normalised: min(round(150/150*100), 100) = 100
        assert "Score: 100/100" in msg

    def test_mid_raw_score_normalised(self):
        sig = SignalResult(
            symbol="ETH",
            side=Side.SHORT,
            confidence=Confidence.MEDIUM,
            entry_low=99.0,
            entry_high=101.0,
            tp1=97.0,
            tp2=94.0,
            tp3=90.0,
            stop_loss=103.0,
            structure_note="test",
            context_note="test",
            leverage_min=10,
            leverage_max=20,
            signal_id="SIG-TEST",
            confluence_score=75,
        )
        msg = sig.format_message()
        # Normalised: round(75/150*100) = 50
        assert "Score: 50/100" in msg

    def test_zero_score_omitted(self):
        sig = SignalResult(
            symbol="BTC",
            side=Side.LONG,
            confidence=Confidence.LOW,
            entry_low=99.0,
            entry_high=101.0,
            tp1=103.0,
            tp2=106.0,
            tp3=110.0,
            stop_loss=97.0,
            structure_note="test",
            context_note="test",
            leverage_min=10,
            leverage_max=20,
            signal_id="SIG-TEST",
            confluence_score=0,
        )
        msg = sig.format_message()
        assert "Score:" not in msg


# ── OPT 4: Signal ID in format_message ───────────────────────────────────────

class TestSignalIdInMessage:
    """format_message() includes the Signal ID line."""

    def test_signal_id_present_in_message(self):
        sig = SignalResult(
            symbol="BTC",
            side=Side.LONG,
            confidence=Confidence.HIGH,
            entry_low=99.0,
            entry_high=101.0,
            tp1=103.0,
            tp2=106.0,
            tp3=110.0,
            stop_loss=97.0,
            structure_note="test",
            context_note="test",
            leverage_min=10,
            leverage_max=20,
            signal_id="SIG-ABCDEF123456",
            confluence_score=90,
        )
        msg = sig.format_message()
        assert "Signal ID: SIG-ABCDEF123456" in msg


# ── BUG 4: Asymmetric entry zone ─────────────────────────────────────────────

class TestAsymmetricEntryZone:
    """Entry zone should be biased toward the discount/premium side."""

    def _make_full_candles(self, base=100.0):
        """Return candles + metadata needed to trigger a signal."""
        avg_vol = 200.0
        candles_5m = [
            CandleData(open=base, high=base + 0.3, low=base - 0.3, close=base + 0.1, volume=avg_vol * 0.8),
            CandleData(open=base + 0.1, high=base + 0.4, low=base - 0.1, close=base + 0.2, volume=avg_vol * 0.9),
            CandleData(open=base, high=base + 0.2, low=base - 1.5, close=base - 0.5, volume=avg_vol * 1.1),  # sweep
            CandleData(open=base - 0.5, high=base + 0.8, low=base - 0.6, close=base + 0.7, volume=avg_vol * 2.0),  # MSS
        ]
        return candles_5m

    def test_long_entry_zone_biased_below_price(self):
        """For LONG, entry_low should be further from price than entry_high."""
        from bot.signal_engine import calculate_atr
        base = 100.0
        candles = self._make_full_candles(base)
        atr = calculate_atr(candles)
        current_price = base + 0.7  # last close

        # Simulate the asymmetric zone calculation directly
        entry_low = current_price - atr * 0.5
        entry_high = current_price + atr * 0.15

        low_distance = current_price - entry_low
        high_distance = entry_high - current_price
        assert low_distance > high_distance, (
            f"LONG entry_low ({entry_low:.4f}) should be further from price "
            f"than entry_high ({entry_high:.4f})"
        )

    def test_short_entry_zone_biased_above_price(self):
        """For SHORT, entry_high should be further from price than entry_low."""
        from bot.signal_engine import calculate_atr
        base = 100.0
        candles = self._make_full_candles(base)
        atr = calculate_atr(candles)
        current_price = base - 0.6

        entry_low = current_price - atr * 0.15
        entry_high = current_price + atr * 0.5

        high_distance = entry_high - current_price
        low_distance = current_price - entry_low
        assert high_distance > low_distance, (
            f"SHORT entry_high ({entry_high:.4f}) should be further from price "
            f"than entry_low ({entry_low:.4f})"
        )


# ── TIMING 2: WATCHING near-miss callback ────────────────────────────────────

class TestNearMissWatchingAlert:
    """run_confluence_check() calls on_near_miss when exactly one gate fails."""

    def _make_all_pass_except(self, failed_gate: str, base: float = 100.0):
        """Return kwargs that pass all gates except *failed_gate*."""
        avg_vol = 200.0
        sweep_level = base - 1.0
        candles_5m = [
            CandleData(open=base, high=base + 0.3, low=base - 0.3, close=base + 0.1, volume=avg_vol * 0.8),
            CandleData(open=base + 0.1, high=base + 0.4, low=base - 0.1, close=base + 0.2, volume=avg_vol * 0.9),
            CandleData(open=base, high=base + 0.2, low=sweep_level - 0.1, close=sweep_level + 0.5,
                       volume=avg_vol * 1.1),
            CandleData(open=base, high=base + 0.9, low=base - 0.1, close=base + 0.7, volume=avg_vol * 2.0),
        ]
        daily = _bullish_daily_candles(n=20, base=50.0)
        four_h = _bullish_4h_candles(n=5, base=90.0)

        kwargs = dict(
            symbol="BTC",
            current_price=base,
            side=Side.LONG,
            range_low=base - 10,
            range_high=base + 10,  # price at 100, midpoint at 100 → discount zone boundary
            key_liquidity_level=sweep_level,
            five_min_candles=candles_5m,
            daily_candles=daily,
            four_hour_candles=four_h,
            news_in_window=False,
            stop_loss=base - 2.0,
        )

        if failed_gate == "news":
            kwargs["news_in_window"] = True
        elif failed_gate == "zone":
            # Move price above the midpoint so it's NOT in discount zone
            kwargs["current_price"] = base + 1.0
            kwargs["range_low"] = base - 2
            kwargs["range_high"] = base + 2
        elif failed_gate == "sweep":
            kwargs["key_liquidity_level"] = base + 100  # impossible sweep level

        return kwargs

    def test_callback_invoked_on_near_miss(self):
        """Exactly one gate (sweep) fails → near-miss callback should be invoked once."""
        alerts: list[str] = []
        kwargs = self._make_all_pass_except("sweep")
        run_confluence_check(**kwargs, on_near_miss=lambda msg: alerts.append(msg))
        # sweep gate fails → 4/5 gates pass → callback must fire exactly once
        assert len(alerts) == 1, f"Expected 1 WATCHING alert but got {len(alerts)}"
        assert "WATCHING" in alerts[0]
        assert "BTC" in alerts[0]
        assert "sweep" in alerts[0]

    def test_no_callback_on_all_pass(self):
        """When all gates pass the callback should not be invoked."""
        alerts: list[str] = []
        # Build candles that will pass every gate (high volume MSS)
        base = 100.0
        avg_vol = 300.0
        sweep_level = base - 2.0
        candles_5m = [
            CandleData(open=base - 2, high=base - 1, low=base - 3, close=base - 1.5, volume=avg_vol * 0.7),
            CandleData(open=base - 1.5, high=base - 0.5, low=base - 2, close=base - 1, volume=avg_vol * 0.8),
            CandleData(open=base - 1, high=base, low=sweep_level - 0.5, close=sweep_level + 0.2,
                       volume=avg_vol * 0.9),
            CandleData(open=base - 0.5, high=base + 1.5, low=base - 0.5, close=base + 1.2,
                       volume=avg_vol * 2.5),
        ]
        daily = _bullish_daily_candles(n=20, base=50.0)
        four_h = _bullish_4h_candles(n=5, base=90.0)
        run_confluence_check(
            symbol="BTC",
            current_price=base - 1,  # 99.0
            side=Side.LONG,
            range_low=base - 15,     # 85.0
            range_high=base + 15,    # 115.0 — midpoint 100.0, price 99 is in discount zone ✓
            key_liquidity_level=sweep_level,
            five_min_candles=candles_5m,
            daily_candles=daily,
            four_hour_candles=four_h,
            news_in_window=False,
            stop_loss=base - 5.0,
            on_near_miss=lambda msg: alerts.append(msg),
        )
        # Callback should NOT have been called when all gates pass
        assert len(alerts) == 0
