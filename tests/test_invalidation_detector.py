"""
Tests for bot/invalidation_detector.py
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.invalidation_detector import InvalidationDetector, _compute_atr
from bot.signal_engine import CandleData, Side

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_candle(close: float, high: float | None = None, low: float | None = None, volume: float = 100.0) -> CandleData:
    h = high if high is not None else close * 1.01
    low_val = low if low is not None else close * 0.99
    return CandleData(open=close, high=h, low=low_val, close=close, volume=volume)


def _make_signal(side: str = "LONG", entry_low: float = 100.0, entry_high: float = 102.0, created_regime: str = "BULL") -> MagicMock:
    sig = MagicMock()
    sig.result.side = Side.LONG if side == "LONG" else Side.SHORT
    sig.result.symbol = "BTC"
    sig.result.entry_low = entry_low
    sig.result.entry_high = entry_high
    sig.result.stop_loss = entry_low - 5.0 if side == "LONG" else entry_high + 5.0
    sig.result.tp1 = entry_high + 10.0 if side == "LONG" else entry_low - 10.0
    sig.entry_mid = (entry_low + entry_high) / 2
    sig.created_regime = created_regime
    return sig


# ── _compute_atr ──────────────────────────────────────────────────────────────


class TestComputeAtr:
    def test_empty_candles(self):
        assert _compute_atr([]) == 0.0

    def test_single_candle(self):
        candles = [_make_candle(100.0, high=102.0, low=98.0)]
        # _compute_atr requires at least 2 candles; returns 0.0 for single candle
        atr = _compute_atr(candles)
        assert atr == 0.0

    def test_typical_range(self):
        candles = [_make_candle(100.0, high=105.0, low=95.0) for _ in range(14)]
        atr = _compute_atr(candles)
        assert atr > 0.0

    def test_returns_float(self):
        candles = [_make_candle(50.0) for _ in range(5)]
        atr = _compute_atr(candles)
        assert isinstance(atr, float)


# ── InvalidationDetector.check_invalidation ───────────────────────────────────


class TestCheckInvalidation:
    def setup_method(self) -> None:
        self.detector = InvalidationDetector()
        self.candles_5m = [_make_candle(100.0) for _ in range(20)]
        self.candles_4h = [_make_candle(100.0) for _ in range(10)]

    def test_no_invalidation_when_price_within_zone(self):
        sig = _make_signal("LONG", entry_low=98.0, entry_high=102.0)
        result = self.detector.check_invalidation(sig, 100.0, self.candles_5m, self.candles_4h, "BULL")
        assert result is None

    def test_ob_breach_long(self):
        sig = _make_signal("LONG", entry_low=100.0, entry_high=102.0)
        # Price well below entry_low - 0.5*ATR
        candles = [_make_candle(100.0, high=101.0, low=99.0) for _ in range(14)]
        atr = _compute_atr(candles)
        breach_price = 100.0 - 0.5 * atr - 1.0
        result = self.detector.check_invalidation(sig, breach_price, candles, self.candles_4h, "BULL")
        assert result is not None
        assert "OB Breach" in result

    def test_ob_breach_short(self):
        sig = _make_signal("SHORT", entry_low=98.0, entry_high=102.0)
        candles = [_make_candle(100.0, high=101.0, low=99.0) for _ in range(14)]
        atr = _compute_atr(candles)
        breach_price = 102.0 + 0.5 * atr + 1.0
        result = self.detector.check_invalidation(sig, breach_price, candles, self.candles_4h, "BEAR")
        assert result is not None
        assert "OB Breach" in result

    def test_regime_flip_long(self):
        # LONG signal created in BULL, now BEAR
        sig = _make_signal("LONG", created_regime="BULL")
        result = self.detector.check_invalidation(sig, 101.0, self.candles_5m, self.candles_4h, "BEAR")
        assert result is not None
        assert "Regime Flip" in result

    def test_regime_flip_short(self):
        # SHORT signal created in BEAR, now BULL
        sig = _make_signal("SHORT", created_regime="BEAR")
        result = self.detector.check_invalidation(sig, 99.0, self.candles_5m, self.candles_4h, "BULL")
        assert result is not None
        assert "Regime Flip" in result

    def test_no_regime_flip_when_unknown(self):
        sig = _make_signal("LONG", created_regime="UNKNOWN")
        result = self.detector.check_invalidation(sig, 101.0, self.candles_5m, self.candles_4h, "BEAR")
        # OB breach not triggered (price within zone), regime flip skipped for UNKNOWN
        assert result is None or "OB Breach" in (result or "")

    def test_volume_death(self):
        sig = _make_signal("LONG", entry_low=98.0, entry_high=102.0)
        # 20 normal candles + 5 dead volume candles
        normal_candles = [_make_candle(100.0, volume=100.0) for _ in range(20)]
        dead_candles = [_make_candle(100.0, volume=1.0) for _ in range(5)]
        all_candles = normal_candles + dead_candles
        result = self.detector.check_invalidation(sig, 100.5, all_candles, self.candles_4h, "BULL")
        # Volume death should be detected (last 5 are 1% of avg=100)
        assert result is not None
        assert "Volume Death" in result

    def test_no_volume_death_insufficient_candles(self):
        sig = _make_signal("LONG")
        # Only 15 candles (< 20 required)
        candles = [_make_candle(100.0, volume=1.0) for _ in range(15)]
        result = self.detector.check_invalidation(sig, 100.5, candles, self.candles_4h, "BULL")
        # Should not trigger volume death (not enough data)
        if result is not None:
            assert "Volume Death" not in result


# ── InvalidationDetector.format_alert ────────────────────────────────────────


class TestFormatAlert:
    def test_format_alert_structure(self):
        detector = InvalidationDetector()
        sig = _make_signal("LONG", entry_low=98.0, entry_high=102.0)
        alert = detector.format_alert(sig, "OB Breach (test)", 97.5)
        assert "SIGNAL INVALIDATION" in alert
        assert "BTC" in alert
        assert "LONG" in alert
        assert "OB Breach (test)" in alert
        assert "97.5" in alert

    def test_format_alert_short(self):
        detector = InvalidationDetector()
        sig = _make_signal("SHORT", entry_low=98.0, entry_high=102.0)
        alert = detector.format_alert(sig, "Volume Death", 103.5)
        assert "SHORT" in alert
        assert "Volume Death" in alert

    def test_format_alert_no_hash_before_symbol(self):
        """Regression: symbol must not be prefixed with # to avoid Telegram Markdown parse errors."""
        detector = InvalidationDetector()
        sig = _make_signal("LONG", entry_low=98.0, entry_high=102.0)
        alert = detector.format_alert(sig, "OB Breach", 97.5)
        assert "#BTC" not in alert
        assert "BTC/USDT" in alert
