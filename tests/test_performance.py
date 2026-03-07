"""
Tests for bot/performance.py — public performance metrics API.
"""
from __future__ import annotations

import time

import pytest

from bot.performance import (
    compare_vs_btc,
    format_performance_summary,
    max_drawdown,
    rolling_profit_factor,
    rolling_win_rate,
    sharpe_ratio,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

class _Trade:
    """Minimal trade-like object compatible with performance functions."""

    def __init__(self, outcome: str, pnl_pct: float, days_ago: float = 1.0):
        self.outcome = outcome
        self.pnl_pct = pnl_pct
        now = time.time()
        self.closed_at = now - days_ago * 86400


def _trades(specs: list[tuple[str, float, float]]) -> list[_Trade]:
    """Build list of _Trade from (outcome, pnl_pct, days_ago) tuples."""
    return [_Trade(*s) for s in specs]


# ── Rolling Win Rate ──────────────────────────────────────────────────────────

class TestRollingWinRate:
    def test_all_wins(self):
        trades = _trades([("WIN", 1.5, 1), ("WIN", 2.0, 2), ("WIN", 1.0, 3)])
        assert rolling_win_rate(trades, days=7) == pytest.approx(100.0)

    def test_all_losses(self):
        trades = _trades([("LOSS", -1.0, 1), ("LOSS", -0.5, 2)])
        assert rolling_win_rate(trades, days=7) == pytest.approx(0.0)

    def test_mixed(self):
        trades = _trades([("WIN", 2.0, 1), ("LOSS", -1.0, 2), ("WIN", 1.5, 3), ("LOSS", -0.5, 4)])
        assert rolling_win_rate(trades, days=7) == pytest.approx(50.0)

    def test_empty_returns_zero(self):
        assert rolling_win_rate([], days=7) == 0.0

    def test_outside_window_excluded(self):
        # Only 1 trade within 7 days, 2 trades older
        trades = _trades([("WIN", 2.0, 1), ("LOSS", -1.0, 10), ("LOSS", -1.0, 20)])
        assert rolling_win_rate(trades, days=7) == pytest.approx(100.0)

    def test_open_trades_excluded(self):
        trades = _trades([("WIN", 1.0, 1), ("OPEN", 0.5, 1)])
        assert rolling_win_rate(trades, days=7) == pytest.approx(100.0)


# ── Rolling Profit Factor ─────────────────────────────────────────────────────

class TestRollingProfitFactor:
    def test_basic(self):
        trades = _trades([("WIN", 3.0, 1), ("LOSS", -1.0, 2)])
        assert rolling_profit_factor(trades, days=30) == pytest.approx(3.0)

    def test_no_losses_returns_zero(self):
        trades = _trades([("WIN", 2.0, 1)])
        assert rolling_profit_factor(trades, days=30) == 0.0

    def test_empty_returns_zero(self):
        assert rolling_profit_factor([], days=30) == 0.0


# ── Sharpe Ratio ──────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_fewer_than_3_trades_returns_zero(self):
        trades = _trades([("WIN", 1.0, 1), ("WIN", 2.0, 2)])
        assert sharpe_ratio(trades) == 0.0

    def test_zero_std_returns_zero(self):
        # All same returns → std = 0
        trades = _trades([("WIN", 1.0, 1), ("WIN", 1.0, 2), ("WIN", 1.0, 3)])
        assert sharpe_ratio(trades) == 0.0

    def test_positive_mean_positive_sharpe(self):
        trades = _trades([("WIN", 2.0, 1), ("WIN", 1.0, 2), ("LOSS", -0.5, 3)])
        result = sharpe_ratio(trades)
        assert result > 0

    def test_returns_float(self):
        trades = _trades([("WIN", 2.0, 1), ("LOSS", -1.0, 2), ("WIN", 1.5, 3)])
        assert isinstance(sharpe_ratio(trades), float)


# ── Max Drawdown ──────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_empty_returns_zero(self):
        assert max_drawdown([]) == 0.0

    def test_no_drawdown_all_wins(self):
        trades = _trades([("WIN", 1.0, 3), ("WIN", 2.0, 2), ("WIN", 1.5, 1)])
        assert max_drawdown(trades) == 0.0

    def test_simple_drawdown(self):
        # Equity: +2, +2, -3 → peak=4, trough=1 → DD=3
        trades = _trades([("WIN", 2.0, 3), ("WIN", 2.0, 2), ("LOSS", -3.0, 1)])
        assert max_drawdown(trades) == pytest.approx(3.0)

    def test_open_trades_excluded(self):
        trades = _trades([("WIN", 2.0, 2), ("OPEN", 10.0, 1)])
        # OPEN should not count
        assert max_drawdown(trades) == 0.0


# ── Compare vs BTC ────────────────────────────────────────────────────────────

class TestCompareVsBtc:
    def test_with_btc_return(self):
        trades = _trades([("WIN", 5.0, 1), ("LOSS", -1.0, 5)])
        result = compare_vs_btc(trades, btc_return_pct=3.0, days=30)
        assert result["bot_return_pct"] == pytest.approx(4.0)
        assert result["btc_return_pct"] == pytest.approx(3.0)
        assert result["alpha_pct"] == pytest.approx(1.0)

    def test_without_btc_return(self):
        trades = _trades([("WIN", 2.0, 1)])
        result = compare_vs_btc(trades, btc_return_pct=None, days=30)
        assert result["btc_return_pct"] is None
        assert result["alpha_pct"] is None

    def test_trade_count(self):
        trades = _trades([("WIN", 1.0, 1), ("LOSS", -0.5, 2), ("WIN", 2.0, 3)])
        result = compare_vs_btc(trades, days=30)
        assert result["trade_count"] == 3

    def test_outside_window_excluded(self):
        trades = _trades([("WIN", 10.0, 60), ("LOSS", -2.0, 1)])
        result = compare_vs_btc(trades, days=30)
        assert result["trade_count"] == 1
        assert result["bot_return_pct"] == pytest.approx(-2.0)


# ── Format Performance Summary ────────────────────────────────────────────────

class TestFormatPerformanceSummary:
    def test_contains_key_labels(self):
        trades = _trades([("WIN", 2.0, 1), ("LOSS", -1.0, 2), ("WIN", 1.5, 3)])
        summary = format_performance_summary(trades)
        assert "Win Rate" in summary
        assert "Profit Factor" in summary
        assert "Sharpe" in summary
        assert "Drawdown" in summary

    def test_btc_comparison_included_when_provided(self):
        trades = _trades([("WIN", 2.0, 1)])
        summary = format_performance_summary(trades, btc_return_pct=5.0)
        assert "BTC" in summary
        assert "Alpha" in summary

    def test_btc_comparison_absent_when_none(self):
        trades = _trades([("WIN", 2.0, 1)])
        summary = format_performance_summary(trades, btc_return_pct=None)
        assert "BTC" not in summary

    def test_returns_string(self):
        assert isinstance(format_performance_summary([]), str)
