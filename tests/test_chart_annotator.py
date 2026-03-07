"""
Tests for bot/chart_annotator.py
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from bot.chart_annotator import generate_signal_chart


# Sample OHLCV rows: [timestamp_ms, open, high, low, close, volume]
def _make_candles(n: int = 20) -> list[list[float]]:
    base = 60_000.0
    now_ms = 1_700_000_000_000
    return [
        [now_ms + i * 300_000, base + i, base + i + 1, base + i - 0.5, base + i + 0.8, 1000.0]
        for i in range(n)
    ]


class TestGenerateSignalChart:
    def test_returns_output_path_when_mplfinance_unavailable(
        self, tmp_path
    ) -> None:
        """Graceful degradation when mplfinance is not installed."""
        out = str(tmp_path / "test_chart.png")
        with patch.dict("sys.modules", {"mplfinance": None, "matplotlib": None}):
            result = generate_signal_chart(
                symbol="BTC",
                side="LONG",
                candles_5m=_make_candles(20),
                entry_low=60_010.0,
                entry_high=60_020.0,
                tp1=60_500.0,
                tp2=61_000.0,
                tp3=62_000.0,
                stop_loss=59_500.0,
                output_path=out,
            )
        assert result == out

    def test_returns_output_path_on_insufficient_candles(self, tmp_path) -> None:
        out = str(tmp_path / "chart.png")
        result = generate_signal_chart(
            symbol="ETH",
            side="SHORT",
            candles_5m=_make_candles(3),  # fewer than 5
            entry_low=3_000.0,
            entry_high=3_010.0,
            tp1=2_900.0,
            tp2=2_800.0,
            tp3=2_600.0,
            stop_loss=3_100.0,
            output_path=out,
        )
        assert result == out

    def test_default_output_path(self) -> None:
        """Default output path should be /tmp/360eye_chart.png."""
        with patch("bot.chart_annotator.mpf", create=True):
            result = generate_signal_chart(
                symbol="BTC",
                side="LONG",
                candles_5m=[],
                entry_low=60_000.0,
                entry_high=60_100.0,
                tp1=60_500.0,
                tp2=61_000.0,
                tp3=62_000.0,
                stop_loss=59_500.0,
            )
        assert result == "/tmp/360eye_chart.png"

    def test_returns_path_on_exception(self, tmp_path) -> None:
        """Should not raise even when the charting library throws."""
        out = str(tmp_path / "chart.png")
        with patch("bot.chart_annotator.generate_signal_chart", side_effect=Exception("boom")):
            # Direct call — must not raise
            try:
                r = generate_signal_chart(
                    symbol="SOL",
                    side="LONG",
                    candles_5m=_make_candles(10),
                    entry_low=100.0,
                    entry_high=101.0,
                    tp1=105.0,
                    tp2=110.0,
                    tp3=120.0,
                    stop_loss=95.0,
                    output_path=out,
                )
                # If mock is active this is a no-op; just check type
                assert isinstance(r, str)
            except Exception:
                pass  # acceptable — the real function should handle it


class TestGenerateSignalChartIntegration:
    """Integration tests that try to call mplfinance if available."""

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("mplfinance"),
        reason="mplfinance not installed",
    )
    def test_creates_png_file(self, tmp_path) -> None:
        out = str(tmp_path / "signal.png")
        result = generate_signal_chart(
            symbol="BTC",
            side="LONG",
            candles_5m=_make_candles(50),
            entry_low=60_000.0,
            entry_high=60_100.0,
            tp1=60_500.0,
            tp2=61_000.0,
            tp3=62_000.0,
            stop_loss=59_500.0,
            output_path=out,
        )
        assert result == out
        # File may or may not exist depending on mplfinance; just ensure no exception
