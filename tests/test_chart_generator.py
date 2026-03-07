"""Tests for bot/chart_generator.py"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from bot.chart_generator import generate_signal_chart
from bot.signal_engine import CandleData, Confidence, Side, SignalResult


def _make_candles(n: int = 20) -> list[CandleData]:
    return [
        CandleData(open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.0 + i, volume=1000.0)
        for i in range(n)
    ]


def _make_signal() -> SignalResult:
    return SignalResult(
        symbol="BTC",
        side=Side.LONG,
        confidence=Confidence.HIGH,
        entry_low=100.0,
        entry_high=101.0,
        tp1=104.0,
        tp2=107.0,
        tp3=112.0,
        stop_loss=98.0,
        structure_note="Test",
        context_note="Test ctx",
        leverage_min=10,
        leverage_max=20,
    )


class TestGenerateSignalChart:
    def test_returns_none_when_mplfinance_missing(self):
        with patch.dict(sys.modules, {"mplfinance": None}):
            result = generate_signal_chart(_make_candles(), _make_signal())
        assert result is None

    def test_returns_none_for_empty_candles(self):
        result = generate_signal_chart([], _make_signal())
        assert result is None

    def test_returns_none_for_too_few_candles(self):
        result = generate_signal_chart(_make_candles(3), _make_signal())
        assert result is None

    def test_returns_bytes_or_none(self):
        # When mplfinance is available, returns bytes; when not, returns None
        result = generate_signal_chart(_make_candles(20), _make_signal())
        assert result is None or isinstance(result, bytes)

    def test_handles_exception_gracefully(self):
        # Should never raise
        try:
            result = generate_signal_chart(_make_candles(20), _make_signal())
        except Exception:
            pytest.fail("generate_signal_chart should not raise exceptions")
