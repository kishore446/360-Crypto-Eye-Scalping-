"""
Tests for bot/insights/daily_performance.py — Daily Performance Recap (CH5E).
"""
from __future__ import annotations

import time

import pytest

from bot.dashboard import Dashboard, TradeResult
from bot.insights.daily_performance import format_daily_performance


def _make_trade(
    symbol: str = "BTC",
    side: str = "LONG",
    outcome: str = "WIN",
    pnl_pct: float = 2.0,
    timeframe: str = "5m",
) -> TradeResult:
    return TradeResult(
        symbol=symbol,
        side=side,
        entry_price=100.0,
        exit_price=102.0 if outcome != "OPEN" else None,
        stop_loss=95.0,
        tp1=107.5,
        tp2=112.5,
        tp3=120.0,
        opened_at=time.time() - 3600,
        closed_at=time.time() if outcome != "OPEN" else None,
        outcome=outcome,
        pnl_pct=pnl_pct,
        timeframe=timeframe,
    )


class TestFormatDailyPerformanceZeroTrades:
    """Edge case: no trades recorded."""

    def setup_method(self, tmp_path=None):
        import os
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.db = Dashboard(log_file=os.path.join(self._tmpdir, "dash.json"))

    def test_no_crash_on_empty_dashboard(self):
        msg = format_daily_performance(self.db)
        assert msg is not None
        assert isinstance(msg, str)

    def test_contains_date(self):
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        msg = format_daily_performance(self.db)
        assert today in msg

    def test_contains_header(self):
        msg = format_daily_performance(self.db)
        assert "DAILY PERFORMANCE RECAP" in msg

    def test_contains_total_trades_zero(self):
        msg = format_daily_performance(self.db)
        assert "0" in msg


class TestFormatDailyPerformanceMixedResults:
    """Mixed win/loss results."""

    def setup_method(self, tmp_path=None):
        import os
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.db = Dashboard(log_file=os.path.join(self._tmpdir, "dash.json"))

    def test_win_rate_reflected(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=1.5))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        msg = format_daily_performance(self.db)
        # 2/3 wins = 66.67% — check that the win rate is present in some form
        assert self.db.win_rate() == pytest.approx(66.67, rel=0.01)
        assert "Win Rate" in msg or "%" in msg

    def test_best_signal_shown(self):
        self.db.record_result(_make_trade(symbol="SOL", outcome="WIN", pnl_pct=2.5))
        self.db.record_result(_make_trade(symbol="DOGE", outcome="LOSS", pnl_pct=-1.0))
        msg = format_daily_performance(self.db)
        assert "SOL" in msg

    def test_worst_signal_shown(self):
        self.db.record_result(_make_trade(symbol="SOL", outcome="WIN", pnl_pct=2.5))
        self.db.record_result(_make_trade(symbol="DOGE", outcome="LOSS", pnl_pct=-1.0))
        msg = format_daily_performance(self.db)
        assert "DOGE" in msg

    def test_streak_win_shown(self):
        for _ in range(3):
            self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        msg = format_daily_performance(self.db)
        assert "3" in msg


class TestFormatDailyPerformanceStreak:
    """Streak calculation."""

    def setup_method(self, tmp_path=None):
        import os
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.db = Dashboard(log_file=os.path.join(self._tmpdir, "dash.json"))

    def test_win_streak_label(self):
        for _ in range(5):
            self.db.record_result(_make_trade(outcome="WIN", pnl_pct=1.0))
        msg = format_daily_performance(self.db)
        assert "Win Streak" in msg or "win" in msg.lower()

    def test_loss_streak_label(self):
        for _ in range(2):
            self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        msg = format_daily_performance(self.db)
        assert "Loss Streak" in msg or "loss" in msg.lower()
