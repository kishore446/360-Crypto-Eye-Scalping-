"""
Tests for bot/performance_watermark.py
"""
from __future__ import annotations

import time

import pytest

from bot.dashboard import Dashboard, TradeResult
from bot.performance_watermark import (
    _compute_sharpe,
    get_channel_watermark,
    get_watermark_line,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_dashboard_with_results(
    outcomes: list[str],
    pnl_values: list[float],
    channel_tier: str = "CH1_HARD",
    opened_at_offset: int = 0,
) -> Dashboard:
    """Create an in-memory Dashboard populated with fake closed trades."""
    dash = Dashboard.__new__(Dashboard)
    dash._log_file = None  # type: ignore[assignment]
    dash._results = []
    now = time.time()
    for outcome, pnl in zip(outcomes, pnl_values):
        dash._results.append(
            TradeResult(
                symbol="BTC",
                side="LONG",
                entry_price=60_000.0,
                exit_price=61_000.0,
                stop_loss=59_000.0,
                tp1=61_000.0,
                tp2=62_000.0,
                tp3=64_000.0,
                opened_at=now - opened_at_offset,
                closed_at=now,
                outcome=outcome,
                pnl_pct=pnl,
                timeframe="5m",
                channel_tier=channel_tier,
            )
        )
    return dash


class TestComputeSharpe:
    def test_returns_zero_for_fewer_than_3_values(self) -> None:
        assert _compute_sharpe([1.0, 2.0]) == 0.0
        assert _compute_sharpe([]) == 0.0

    def test_returns_zero_when_std_is_zero(self) -> None:
        assert _compute_sharpe([1.0, 1.0, 1.0]) == 0.0

    def test_positive_sharpe_for_consistent_gains(self) -> None:
        result = _compute_sharpe([2.0, 2.5, 3.0, 1.5, 2.0])
        assert result > 0

    def test_negative_sharpe_for_losses(self) -> None:
        result = _compute_sharpe([-2.0, -2.5, -1.5, -3.0, -2.0])
        assert result < 0


class TestGetChannelWatermark:
    def test_returns_none_when_fewer_than_3_results(self) -> None:
        dash = _make_dashboard_with_results(["WIN", "LOSS"], [1.0, -1.0])
        result = get_channel_watermark(dash, "CH1_HARD")
        assert result is None

    def test_returns_formatted_badge_with_enough_data(self) -> None:
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN", "LOSS"],
            [2.0, 1.5, 3.0, -1.0],
        )
        badge = get_channel_watermark(dash, "CH1_HARD")
        assert badge is not None
        assert "CH1" in badge
        assert "WR" in badge
        assert "Sharpe" in badge

    def test_win_rate_reflects_wins(self) -> None:
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN", "LOSS"],
            [2.0, 1.5, 3.0, -1.0],
        )
        badge = get_channel_watermark(dash, "CH1_HARD")
        assert badge is not None
        assert "75.0% WR" in badge

    def test_only_counts_matching_channel_tier(self) -> None:
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN"],
            [1.0, 1.0, 1.0],
            channel_tier="CH2_MEDIUM",
        )
        result = get_channel_watermark(dash, "CH1_HARD")
        assert result is None  # No CH1 trades

    def test_respects_lookback_window(self) -> None:
        # All trades older than 30 days
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN"],
            [1.0, 1.0, 1.0],
            opened_at_offset=40 * 86_400,  # 40 days ago
        )
        result = get_channel_watermark(dash, "CH1_HARD", days=30)
        assert result is None

    def test_signal_count_in_badge(self) -> None:
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN", "WIN", "LOSS"],
            [1.0, 1.0, 1.0, 1.0, -1.0],
        )
        badge = get_channel_watermark(dash, "CH1_HARD")
        assert badge is not None
        assert "(5 signals)" in badge


class TestGetWatermarkLine:
    def test_returns_empty_string_when_no_data(self) -> None:
        dash = _make_dashboard_with_results([], [])
        result = get_watermark_line(dash, "CH1_HARD")
        assert result == ""

    def test_returns_badge_when_data_available(self) -> None:
        dash = _make_dashboard_with_results(
            ["WIN", "WIN", "WIN"],
            [2.0, 1.5, 1.0],
        )
        result = get_watermark_line(dash, "CH1_HARD")
        assert result != ""
        assert "CH1" in result
