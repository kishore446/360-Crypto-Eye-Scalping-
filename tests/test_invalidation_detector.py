"""Tests for bot/invalidation_detector.py"""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.invalidation_detector import InvalidationDetector, format_invalidation_alert
from bot.signal_engine import CandleData, Confidence, Side, SignalResult

# ── fixtures ───────────────────────────────────────────────────────────────────

def _make_candles(
    n: int = 20,
    volume: float = 1000.0,
    close: float = 100.0,
) -> list[CandleData]:
    return [
        CandleData(
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=volume,
        )
        for _ in range(n)
    ]


def _make_signal(side: Side = Side.LONG, created_regime: str = "BULL") -> MagicMock:
    result = SignalResult(
        symbol="BTC",
        side=side,
        confidence=Confidence.HIGH,
        entry_low=100.0,
        entry_high=102.0,
        tp1=108.0,
        tp2=115.0,
        tp3=125.0,
        stop_loss=96.0,
        structure_note="",
        context_note="",
        leverage_min=10,
        leverage_max=20,
    )
    sig = MagicMock()
    sig.result = result
    sig.entry_mid = 101.0
    sig.created_regime = created_regime
    return sig


# ── InvalidationDetector.check_invalidation ────────────────────────────────────

class TestNoInvalidation:
    def test_no_invalidation_normal_conditions(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "BULL")
        candles = _make_candles(20, volume=1000.0, close=102.0)
        result = detector.check_invalidation(sig, 102.0, candles, candles, "BULL")
        assert result is None

    def test_returns_none_when_insufficient_candles(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "BULL")
        result = detector.check_invalidation(sig, 102.0, [], [], "BULL")
        assert result is None


class TestOBBreach:
    def test_long_ob_breach_detected(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "BULL")
        # High ATR candles to make breach_level close to entry_low
        atr_candles = [
            CandleData(open=90.0, high=110.0, low=80.0, close=95.0, volume=1000.0)
            for _ in range(15)
        ]
        # Last candle closes well below entry_low (100.0) AND breach_level (~85)
        close_candles = atr_candles[:-1] + [
            CandleData(open=82.0, high=83.0, low=80.0, close=80.0, volume=1000.0)
        ]
        result = detector.check_invalidation(sig, 80.0, close_candles, atr_candles, "BULL")
        # Should detect OB breach (close=80 well below entry_low=100 - 0.5*ATR)
        assert result is not None
        assert "order block" in result.lower() or "OB" in result or "breached" in result.lower()

    def test_short_ob_breach_detected(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.SHORT, "BEAR")
        sig.result = SignalResult(
            symbol="BTC",
            side=Side.SHORT,
            confidence=Confidence.HIGH,
            entry_low=98.0,
            entry_high=100.0,
            tp1=94.0,
            tp2=90.0,
            tp3=85.0,
            stop_loss=104.0,
            structure_note="",
            context_note="",
            leverage_min=10,
            leverage_max=20,
        )
        atr_candles = [
            CandleData(open=95.0, high=105.0, low=90.0, close=100.0, volume=1000.0)
            for _ in range(15)
        ]
        # Last candle closes well above entry_high (100.0)
        close_candles = atr_candles[:-1] + [
            CandleData(open=105.0, high=115.0, low=104.0, close=115.0, volume=1000.0)
        ]
        result = detector.check_invalidation(sig, 115.0, close_candles, atr_candles, "BEAR")
        assert result is not None


class TestRegimeFlip:
    def test_long_regime_flip_detected(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "BULL")
        candles = _make_candles(20, volume=1000.0, close=101.0)
        result = detector.check_invalidation(sig, 101.0, candles, candles, "BEAR")
        assert result is not None
        assert "regime" in result.lower() or "BULL" in result or "BEAR" in result

    def test_short_regime_flip_detected(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.SHORT, "BEAR")
        candles = _make_candles(20, volume=1000.0, close=99.0)
        result = detector.check_invalidation(sig, 99.0, candles, candles, "BULL")
        assert result is not None

    def test_no_flip_when_created_regime_unknown(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "UNKNOWN")
        candles = _make_candles(20, volume=1000.0, close=101.0)
        result = detector.check_invalidation(sig, 101.0, candles, candles, "BEAR")
        # Regime flip check should be skipped when created_regime is UNKNOWN
        # (may still return OB breach reason — just check regime flip isn't the reason)
        if result:
            assert "UNKNOWN" not in result

    def test_no_flip_when_regime_unchanged(self):
        detector = InvalidationDetector()
        sig = _make_signal(Side.LONG, "BULL")
        result = detector._check_regime_flip(sig, "BULL")
        assert result is None


class TestVolumeDeath:
    def test_volume_death_detected(self):
        detector = InvalidationDetector()
        # 15 normal-volume candles + 5 very-low-volume candles
        normal = _make_candles(15, volume=1000.0, close=101.0)
        low = _make_candles(5, volume=10.0, close=101.0)  # 1% of avg
        candles = normal + low
        result = detector._check_volume_death(candles)
        assert result is not None
        assert "volume" in result.lower()

    def test_no_volume_death_with_healthy_volume(self):
        detector = InvalidationDetector()
        candles = _make_candles(20, volume=1000.0, close=101.0)
        result = detector._check_volume_death(candles)
        assert result is None

    def test_volume_death_skipped_with_too_few_candles(self):
        detector = InvalidationDetector()
        candles = _make_candles(3, volume=10.0, close=101.0)
        result = detector._check_volume_death(candles)
        assert result is None


# ── format_invalidation_alert ─────────────────────────────────────────────────

class TestFormatInvalidationAlert:
    def test_format_contains_symbol(self):
        sig = _make_signal()
        msg = format_invalidation_alert(sig, "Test reason", 99.0)
        assert "BTC" in msg

    def test_format_contains_reason(self):
        sig = _make_signal()
        msg = format_invalidation_alert(sig, "Volume momentum exhausted", 99.0)
        assert "Volume momentum exhausted" in msg

    def test_format_contains_current_price(self):
        sig = _make_signal()
        msg = format_invalidation_alert(sig, "Test reason", 67_200.0)
        assert "67,200.00" in msg

    def test_format_contains_entry(self):
        sig = _make_signal()
        msg = format_invalidation_alert(sig, "Test reason", 99.0)
        assert "101.00" in msg  # entry_mid = (100+102)/2 = 101
