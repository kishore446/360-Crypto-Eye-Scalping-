"""Tests for format_monthly_report()."""
from __future__ import annotations

import datetime

import pytest

from bot.dashboard import Dashboard, TradeResult
from bot.insights.monthly_report import format_monthly_report


def _make_result(
    symbol: str = "BTC",
    side: str = "LONG",
    outcome: str = "WIN",
    pnl_pct: float = 2.0,
    channel_tier: str = "CH1_HARD",
    month: int = 2,
    year: int = 2026,
) -> TradeResult:
    dt = datetime.datetime(year, month, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
    ts = dt.timestamp()
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


@pytest.fixture()
def db(tmp_path):
    return Dashboard(log_file=str(tmp_path / "dashboard.json"))


class TestFormatMonthlyReport:
    def test_header_contains_month_year(self, db):
        report = format_monthly_report(db, month=2, year=2026)
        assert "February" in report
        assert "2026" in report

    def test_empty_month_shows_zero(self, db):
        report = format_monthly_report(db, month=2, year=2026)
        assert "Total Signals: 0" in report
        assert "Win Rate: 0.0%" in report

    def test_win_rate_calculation(self, db):
        for _ in range(3):
            db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(outcome="LOSS", pnl_pct=-1.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "75.0%" in report
        assert "Total Signals: 4" in report

    def test_total_pnl_shown(self, db):
        db.record_result(_make_result(outcome="WIN", pnl_pct=5.0))
        db.record_result(_make_result(outcome="WIN", pnl_pct=3.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "+8.0" in report

    def test_best_and_worst_trade(self, db):
        db.record_result(_make_result(symbol="BTC", outcome="WIN", pnl_pct=8.4))
        db.record_result(_make_result(symbol="DOGE", outcome="LOSS", pnl_pct=-2.1))
        report = format_monthly_report(db, month=2, year=2026)
        assert "BTC" in report
        assert "DOGE" in report
        assert "+8.4%" in report
        assert "-2.1%" in report

    def test_per_channel_breakdown(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=3.0))
        db.record_result(_make_result(channel_tier="CH2_MEDIUM", outcome="WIN", pnl_pct=1.5))
        db.record_result(_make_result(channel_tier="CH2_MEDIUM", outcome="LOSS", pnl_pct=-1.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "CH1" in report
        assert "CH2" in report

    def test_excludes_other_months(self, db):
        """Signals from outside the target month should not be counted."""
        jan_result = _make_result(outcome="WIN", pnl_pct=10.0, month=1, year=2026)
        db.record_result(jan_result)
        report = format_monthly_report(db, month=2, year=2026)
        assert "Total Signals: 0" in report

    def test_sharpe_ratio_present(self, db):
        for _ in range(5):
            db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(outcome="LOSS", pnl_pct=-1.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "Sharpe" in report

    def test_profit_factor_present(self, db):
        db.record_result(_make_result(outcome="WIN", pnl_pct=3.0))
        db.record_result(_make_result(outcome="LOSS", pnl_pct=-1.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "Profit Factor" in report

    def test_max_drawdown_present(self, db):
        db.record_result(_make_result(outcome="LOSS", pnl_pct=-3.0))
        db.record_result(_make_result(outcome="LOSS", pnl_pct=-2.0))
        report = format_monthly_report(db, month=2, year=2026)
        assert "Drawdown" in report
