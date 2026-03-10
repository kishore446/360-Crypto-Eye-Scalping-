"""Tests for Dashboard per-channel and per-session statistics."""
from __future__ import annotations

import math
import time

import pytest

from bot.dashboard import Dashboard, TradeResult


def _make_result(
    symbol: str = "BTC",
    outcome: str = "WIN",
    pnl_pct: float = 2.0,
    channel_tier: str = "CH1_HARD",
    session: str = "LONDON",
    side: str = "LONG",
    timeframe: str = "5m",
    entry_price: float = 100.0,
    opened_at: float | None = None,
) -> TradeResult:
    ts = opened_at if opened_at is not None else time.time() - 3600
    return TradeResult(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        exit_price=entry_price * (1 + pnl_pct / 100),
        stop_loss=entry_price * 0.98,
        tp1=entry_price * 1.02,
        tp2=entry_price * 1.04,
        tp3=entry_price * 1.06,
        opened_at=ts,
        closed_at=ts + 3600,
        outcome=outcome,
        pnl_pct=pnl_pct,
        timeframe=timeframe,
        channel_tier=channel_tier,
        session=session,
    )


@pytest.fixture()
def db(tmp_path):
    return Dashboard(log_file=str(tmp_path / "dashboard.json"))


# ── TradeResult channel_tier and session fields ──────────────────────────────

class TestTradeResultFields:
    def test_default_channel_tier(self):
        r = _make_result()
        # TradeResult with explicit channel_tier
        assert r.channel_tier == "CH1_HARD"

    def test_default_session(self):
        r = _make_result(session="NYC")
        assert r.session == "NYC"

    def test_to_dict_includes_channel_tier(self):
        r = _make_result(channel_tier="CH2_MEDIUM", session="OVERLAP")
        d = r.to_dict()
        assert d["channel_tier"] == "CH2_MEDIUM"
        assert d["session"] == "OVERLAP"

    def test_from_dict_round_trips(self):
        r = _make_result(channel_tier="CH3_EASY", session="ASIA")
        r2 = TradeResult.from_dict(r.to_dict())
        assert r2.channel_tier == "CH3_EASY"
        assert r2.session == "ASIA"


# ── per_channel_stats ─────────────────────────────────────────────────────────

class TestPerChannelStats:
    def test_empty_dashboard(self, db):
        stats = db.per_channel_stats()
        assert "CH1_HARD" in stats
        assert stats["CH1_HARD"]["total_signals"] == 0
        assert stats["CH1_HARD"]["win_rate"] == 0.0

    def test_single_win(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0))
        stats = db.per_channel_stats()
        assert stats["CH1_HARD"]["total_signals"] == 1
        assert stats["CH1_HARD"]["win_rate"] == 100.0
        assert stats["CH1_HARD"]["wins"] == 1

    def test_multiple_channels(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=3.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="LOSS", pnl_pct=-1.0))
        db.record_result(_make_result(channel_tier="CH2_MEDIUM", outcome="WIN", pnl_pct=1.5))
        stats = db.per_channel_stats()
        assert stats["CH1_HARD"]["total_signals"] == 2
        assert stats["CH1_HARD"]["win_rate"] == 50.0
        assert stats["CH2_MEDIUM"]["total_signals"] == 1
        assert stats["CH2_MEDIUM"]["win_rate"] == 100.0

    def test_all_tiers_present(self, db):
        stats = db.per_channel_stats()
        for tier in ("CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"):
            assert tier in stats

    def test_best_and_worst_trade(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=5.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="LOSS", pnl_pct=-2.0))
        stats = db.per_channel_stats()
        assert stats["CH1_HARD"]["best_trade"] == 5.0
        assert stats["CH1_HARD"]["worst_trade"] == -2.0

    def test_open_trades_excluded(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="OPEN", pnl_pct=1.0))
        stats = db.per_channel_stats()
        assert stats["CH1_HARD"]["total_signals"] == 0


# ── per_session_stats ─────────────────────────────────────────────────────────

class TestPerSessionStats:
    def test_empty_dashboard(self, db):
        stats = db.per_session_stats()
        assert "LONDON" in stats
        assert "NYC" in stats
        assert stats["LONDON"]["total_signals"] == 0

    def test_london_session(self, db):
        db.record_result(_make_result(session="LONDON", outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(session="LONDON", outcome="WIN", pnl_pct=1.5))
        db.record_result(_make_result(session="NYC", outcome="LOSS", pnl_pct=-1.0))
        stats = db.per_session_stats()
        assert stats["LONDON"]["total_signals"] == 2
        assert stats["LONDON"]["win_rate"] == 100.0
        assert stats["NYC"]["total_signals"] == 1
        assert stats["NYC"]["win_rate"] == 0.0

    def test_all_sessions_present(self, db):
        stats = db.per_session_stats()
        for session in ("LONDON", "NYC", "ASIA", "OVERLAP", "UNKNOWN"):
            assert session in stats


# ── format_per_channel_report ─────────────────────────────────────────────────

class TestFormatPerChannelReport:
    def test_report_contains_channel_labels(self, db):
        report = db.format_per_channel_report()
        assert "CH1 Hard Scalp" in report
        assert "CH2 Medium" in report
        assert "CH3 Easy Breakout" in report
        assert "CH4 Spot" in report

    def test_report_with_data(self, db):
        now = time.time()
        for _ in range(3):
            db.record_result(
                _make_result(
                    channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0,
                    opened_at=now - 86400,
                )
            )
        db.record_result(
            _make_result(
                channel_tier="CH1_HARD", outcome="LOSS", pnl_pct=-1.0,
                opened_at=now - 86400,
            )
        )
        report = db.format_per_channel_report(days=30)
        assert "75.0%" in report

    def test_report_respects_days_window(self, db):
        old_ts = time.time() - 40 * 86400  # 40 days ago
        db.record_result(
            _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=5.0, opened_at=old_ts)
        )
        report = db.format_per_channel_report(days=30)
        # Old trade should not appear in 30d report
        assert "CH1 Hard Scalp:" in report

    def test_report_header_includes_days(self, db):
        report = db.format_per_channel_report(days=30)
        assert "30d" in report


# ── Bug 1: Rolling win rate uses closed_at ────────────────────────────────────

class TestRollingWinRateUsesClosedAt:
    """win_rate_rolling() and format_per_channel_report() must use closed_at, not opened_at."""

    def test_win_rate_rolling_uses_closed_at(self, db):
        now = time.time()
        # Trade opened 10 days ago (outside 7d window) but closed 3 days ago (inside)
        r = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0, opened_at=now - 10 * 86400)
        # Override closed_at to be inside the 7d window
        r = TradeResult(
            **{**r.to_dict(), "closed_at": now - 3 * 86400}
        )
        db.record_result(r)
        # With closed_at filter, this trade should be included
        wr = db.win_rate_rolling(days=7)
        assert wr == pytest.approx(100.0)

    def test_win_rate_rolling_excludes_trade_closed_outside_window(self, db):
        now = time.time()
        r = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0, opened_at=now - 3 * 86400)
        # Override closed_at to be outside window
        r = TradeResult(
            **{**r.to_dict(), "closed_at": now - 10 * 86400}
        )
        db.record_result(r)
        wr = db.win_rate_rolling(days=7)
        assert wr == pytest.approx(0.0)

    def test_format_per_channel_report_uses_closed_at(self, db):
        now = time.time()
        # Trade opened 40 days ago but closed 5 days ago — should appear in 30d report
        r = _make_result(
            channel_tier="CH1_HARD", outcome="WIN", pnl_pct=3.0,
            opened_at=now - 40 * 86400,
        )
        r = TradeResult(**{**r.to_dict(), "closed_at": now - 5 * 86400})
        db.record_result(r)
        report = db.format_per_channel_report(days=30)
        assert "100.0%" in report


# ── Bug 4 / Part K: STALE tracking ───────────────────────────────────────────

class TestStaleTracking:
    def test_stale_count_zero_initially(self, db):
        assert db.stale_count() == 0

    def test_stale_count_increments(self, db):
        db.record_result(_make_result(outcome="STALE", pnl_pct=0.0))
        assert db.stale_count() == 1

    def test_stale_included_in_total_trades(self, db):
        db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(outcome="STALE", pnl_pct=0.0))
        assert db.total_trades() == 2

    def test_stale_not_included_in_win_rate_denominator(self, db):
        db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(outcome="STALE", pnl_pct=0.0))
        # WR should be 100% (2 wins out of 2 WIN/LOSS/BE trades)
        assert db.win_rate() == pytest.approx(100.0)

    def test_stale_count_in_channel_stats(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="STALE", pnl_pct=0.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0))
        stats = db.per_channel_stats()
        assert stats["CH1_HARD"]["stale_count"] == 1
        # WIN/LOSS/BE total should be 1
        assert stats["CH1_HARD"]["total_signals"] == 1

    def test_summary_includes_stale_count(self, db):
        db.record_result(_make_result(outcome="STALE", pnl_pct=0.0))
        summary = db.summary()
        assert "Stale" in summary


# ── Part C: Per-channel rolling stats ────────────────────────────────────────

class TestPerChannelRollingStats:
    def test_empty_returns_all_tiers(self, db):
        stats = db.per_channel_rolling_stats(days=7)
        for tier in ("CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"):
            assert tier in stats

    def test_rolling_includes_recent_trades(self, db):
        now = time.time()
        r = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0,
                         opened_at=now - 3 * 86400)
        r = TradeResult(**{**r.to_dict(), "closed_at": now - 3 * 86400})
        db.record_result(r)
        stats = db.per_channel_rolling_stats(days=7)
        assert stats["CH1_HARD"]["total_signals"] == 1

    def test_rolling_excludes_old_trades(self, db):
        now = time.time()
        r = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0,
                         opened_at=now - 14 * 86400)
        r = TradeResult(**{**r.to_dict(), "closed_at": now - 14 * 86400})
        db.record_result(r)
        stats = db.per_channel_rolling_stats(days=7)
        assert stats["CH1_HARD"]["total_signals"] == 0


class TestPerChannelProfitFactor:
    def test_empty_returns_zero(self, db):
        pf = db.per_channel_profit_factor()
        assert pf["CH1_HARD"] == pytest.approx(0.0)

    def test_all_wins_returns_inf_no_loss(self, db):
        """When there are only winning trades, profit factor is infinite (perfect record)."""
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0))
        pf = db.per_channel_profit_factor()
        assert math.isinf(pf["CH1_HARD"])

    def test_wins_and_losses(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=4.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="LOSS", pnl_pct=-2.0))
        pf = db.per_channel_profit_factor()
        assert pf["CH1_HARD"] == pytest.approx(2.0)


class TestPerChannelTpDistribution:
    def test_empty_returns_zeros(self, db):
        dist = db.per_channel_tp_distribution()
        assert dist["CH1_HARD"]["WIN"] == 0
        assert dist["CH1_HARD"]["LOSS"] == 0
        assert dist["CH1_HARD"]["STALE"] == 0

    def test_distribution_counts(self, db):
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=3.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="LOSS", pnl_pct=-1.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="BE", pnl_pct=0.0))
        db.record_result(_make_result(channel_tier="CH1_HARD", outcome="STALE", pnl_pct=0.0))
        dist = db.per_channel_tp_distribution()
        assert dist["CH1_HARD"]["WIN"] == 2
        assert dist["CH1_HARD"]["LOSS"] == 1
        assert dist["CH1_HARD"]["BE"] == 1
        assert dist["CH1_HARD"]["STALE"] == 1
        assert dist["CH1_HARD"]["total"] == 5


class TestPerChannelEquityCurve:
    def test_empty_curve(self, db):
        curves = db.per_channel_equity_curve()
        assert curves["CH1_HARD"] == []

    def test_curve_cumulative(self, db):
        now = time.time()
        r1 = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=2.0, opened_at=now - 2 * 3600)
        r1 = TradeResult(**{**r1.to_dict(), "closed_at": now - 2 * 3600})
        r2 = _make_result(channel_tier="CH1_HARD", outcome="WIN", pnl_pct=3.0, opened_at=now - 1 * 3600)
        r2 = TradeResult(**{**r2.to_dict(), "closed_at": now - 1 * 3600})
        db.record_result(r1)
        db.record_result(r2)
        curves = db.per_channel_equity_curve()
        assert len(curves["CH1_HARD"]) == 2
        assert curves["CH1_HARD"][0] == pytest.approx(2.0)
        assert curves["CH1_HARD"][1] == pytest.approx(5.0)
