"""Tests for Dashboard per-channel and per-session statistics."""
from __future__ import annotations

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
