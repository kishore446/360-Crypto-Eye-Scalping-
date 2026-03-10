"""Tests for bot/weekly_report.py"""
from __future__ import annotations

import time

import pytest

from bot.dashboard import Dashboard, TradeResult
from bot.weekly_report import generate_weekly_report


def _make_result(
    symbol: str = "BTC",
    side: str = "LONG",
    outcome: str = "WIN",
    pnl_pct: float = 2.0,
    channel_tier: str = "CH1_SCALPING",
    days_ago: float = 1.0,
) -> TradeResult:
    ts = time.time() - days_ago * 86400
    return TradeResult(
        symbol=symbol,
        side=side,
        entry_price=100.0,
        exit_price=100.0 * (1 + pnl_pct / 100),
        stop_loss=98.0,
        tp1=102.0,
        tp2=104.0,
        tp3=106.0,
        opened_at=ts,
        closed_at=ts + 3600,
        outcome=outcome,
        pnl_pct=pnl_pct,
        timeframe="5m",
        channel_tier=channel_tier,
        session="LONDON",
    )


class TestGenerateWeeklyReport:
    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        self.db = Dashboard(log_file=str(tmp_path / "db.json"))

    def test_empty_dashboard_returns_report(self):
        report = generate_weekly_report(self.db)
        assert "WEEKLY PERFORMANCE REPORT" in report
        assert "Total Signals" in report

    def test_report_shows_correct_win_rate(self):
        self.db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_result(outcome="LOSS", pnl_pct=-1.0))
        report = generate_weekly_report(self.db)
        assert "50.0%" in report  # 1 WIN out of 2 = 50%

    def test_report_excludes_old_trades(self):
        # 10-day-old trade should NOT appear in 7-day report
        self.db.record_result(_make_result(outcome="WIN", pnl_pct=2.0, days_ago=10.0))
        report = generate_weekly_report(self.db, days=7)
        # 0 signals this week
        assert "Total Signals  : 0" in report

    def test_report_includes_channel_breakdown(self):
        self.db.record_result(_make_result(outcome="WIN", channel_tier="CH1_SCALPING"))
        report = generate_weekly_report(self.db)
        assert "CH1" in report

    def test_report_includes_30d_rolling(self):
        report = generate_weekly_report(self.db)
        assert "30-DAY ROLLING" in report

    def test_report_shows_protected_win_rate_label(self):
        self.db.record_result(_make_result(outcome="BE", pnl_pct=0.0))
        report = generate_weekly_report(self.db)
        assert "Protected WR" in report
