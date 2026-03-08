"""
Tests for bot/dashboard.py and bot/news_filter.py
"""

from __future__ import annotations

import time

import pytest

from bot.dashboard import Dashboard, TradeResult
from bot.news_filter import NewsCalendar, NewsEvent

# ── Dashboard fixtures ────────────────────────────────────────────────────────

def _make_trade(
    symbol: str = "BTC",
    side: str = "LONG",
    outcome: str = "WIN",
    pnl_pct: float = 2.5,
    timeframe: str = "5m",
    tmp_path=None,
) -> TradeResult:
    return TradeResult(
        symbol=symbol,
        side=side,
        entry_price=100.0,
        exit_price=102.5 if outcome != "OPEN" else None,
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


# ── Dashboard tests ───────────────────────────────────────────────────────────

class TestDashboard:
    @pytest.fixture(autouse=True)
    def _tmp_dashboard(self, tmp_path):
        self.db = Dashboard(log_file=str(tmp_path / "test_dashboard.json"))

    def test_empty_win_rate(self):
        assert self.db.win_rate() == 0.0

    def test_win_rate_all_wins(self):
        for _ in range(3):
            self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        assert self.db.win_rate() == pytest.approx(100.0)

    def test_win_rate_mixed(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        assert self.db.win_rate() == pytest.approx(50.0)

    def test_win_rate_by_timeframe(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0, timeframe="5m"))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0, timeframe="15m"))
        assert self.db.win_rate("5m") == pytest.approx(100.0)
        assert self.db.win_rate("15m") == pytest.approx(0.0)

    def test_profit_factor_no_loss(self):
        """Profit factor returns 0.0 when there are no losing trades (avoid division by zero)."""
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=3.0))
        assert self.db.profit_factor() == 0.0

    def test_profit_factor_calculated(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=3.0))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        # Gross profit = 3.0, gross loss = 1.0 → PF = 3.0
        assert self.db.profit_factor() == pytest.approx(3.0)

    def test_current_open_pnl_sums_open_trades(self):
        self.db.record_result(_make_trade(outcome="OPEN", pnl_pct=1.5))
        self.db.record_result(_make_trade(outcome="OPEN", pnl_pct=-0.5))
        assert self.db.current_open_pnl() == pytest.approx(1.0)

    def test_open_trades_excluded_from_win_rate(self):
        self.db.record_result(_make_trade(outcome="OPEN", pnl_pct=1.5))
        assert self.db.win_rate() == 0.0

    def test_update_open_pnl(self):
        self.db.record_result(_make_trade(symbol="ETH", outcome="OPEN", pnl_pct=0.0))
        # Long trade: current_price 105 vs entry 100 → +5 %
        self.db.update_open_pnl("ETH", current_price=105.0)
        open_trades = [r for r in self.db._results if r.symbol == "ETH"]
        assert open_trades[0].pnl_pct == pytest.approx(5.0, rel=1e-4)

    def test_total_trades_excludes_open(self):
        self.db.record_result(_make_trade(outcome="WIN"))
        self.db.record_result(_make_trade(outcome="OPEN"))
        assert self.db.total_trades() == 1

    def test_persistence_across_instances(self, tmp_path):
        """Records saved to disk should reload correctly."""
        log_file = str(tmp_path / "persist.json")
        db1 = Dashboard(log_file=log_file)
        db1.record_result(_make_trade(outcome="WIN", pnl_pct=2.5))

        db2 = Dashboard(log_file=log_file)
        assert db2.total_trades() == 1
        assert db2.win_rate() == pytest.approx(100.0)

    def test_summary_contains_key_sections(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        summary = self.db.summary()
        assert "Win Rate" in summary
        assert "Profit Factor" in summary
        assert "Open PnL" in summary

    def test_sharpe_requires_at_least_3_trades(self):
        """Sharpe ratio should return 0.0 for fewer than 3 closed trades."""
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        assert self.db.sharpe_ratio() == 0.0

    def test_sharpe_uses_bessels_correction(self):
        """
        Sharpe ratio must use sample variance (n-1) not population variance (n).
        For returns [2.0, -1.0, 1.5]:
          mean = 2.5/3 ≈ 0.8333
          sample variance = sum((r - mean)^2) / (3-1)
          NOT population variance = sum((r - mean)^2) / 3
        """
        import math
        returns = [2.0, -1.0, 1.5]
        for r in returns:
            outcome = "WIN" if r > 0 else "LOSS"
            self.db.record_result(_make_trade(outcome=outcome, pnl_pct=r))

        mean_r = sum(returns) / len(returns)
        sample_var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        expected_sharpe = round(mean_r / math.sqrt(sample_var), 4)

        assert self.db.sharpe_ratio() == pytest.approx(expected_sharpe, rel=1e-4)

    def test_sharpe_differs_from_biased_estimate_with_few_samples(self):
        """Sample variance (n-1) > population variance (n), so Sharpe is LOWER with correction."""
        import math
        returns = [3.0, -1.0, 2.0]  # n=3
        for r in returns:
            outcome = "WIN" if r > 0 else "LOSS"
            self.db.record_result(_make_trade(outcome=outcome, pnl_pct=r))

        sharpe_actual = self.db.sharpe_ratio()

        # Compute the old (biased) Sharpe for comparison
        mean_r = sum(returns) / len(returns)
        pop_var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        biased_sharpe = mean_r / math.sqrt(pop_var)

        # With Bessel's correction, std is larger → Sharpe is smaller
        assert sharpe_actual < biased_sharpe


class TestProtectedWinRate:
    """Tests for Dashboard.protected_win_rate() — counts BE as a win."""

    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        self.db = Dashboard(log_file=str(tmp_path / "db.json"))

    def test_empty_returns_zero(self):
        assert self.db.protected_win_rate() == 0.0

    def test_be_counted_as_win(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="BE", pnl_pct=0.0))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        # 2 out of 3 (WIN + BE) = 66.67%
        assert self.db.protected_win_rate() == pytest.approx(66.67, rel=1e-2)

    def test_strict_win_rate_excludes_be(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="BE", pnl_pct=0.0))
        self.db.record_result(_make_trade(outcome="LOSS", pnl_pct=-1.0))
        # strict: only 1 WIN out of 3 = 33.33%
        assert self.db.win_rate() == pytest.approx(33.33, rel=1e-2)

    def test_protected_win_rate_higher_or_equal_to_strict(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        self.db.record_result(_make_trade(outcome="BE", pnl_pct=0.0))
        assert self.db.protected_win_rate() >= self.db.win_rate()

    def test_all_wins_same_as_strict(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=1.0))
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        assert self.db.protected_win_rate() == self.db.win_rate()


class TestAvgRiskReward:
    """Tests for Dashboard.avg_risk_reward()."""

    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        self.db = Dashboard(log_file=str(tmp_path / "db.json"))

    def test_empty_returns_zero(self):
        assert self.db.avg_risk_reward() == 0.0

    def test_calculates_rr(self):
        # entry=100, sl=98 → sl_dist=2%, pnl=4% → R = 4/2 = 2.0
        r = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=104.0,
            stop_loss=98.0, tp1=104.0, tp2=106.0, tp3=108.0,
            opened_at=time.time() - 3600, closed_at=time.time(),
            outcome="WIN", pnl_pct=4.0, timeframe="5m",
        )
        self.db.record_result(r)
        assert self.db.avg_risk_reward() == pytest.approx(2.0, rel=1e-3)

    def test_open_trades_excluded(self):
        r = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=None,
            stop_loss=98.0, tp1=104.0, tp2=106.0, tp3=108.0,
            opened_at=time.time(), closed_at=None,
            outcome="OPEN", pnl_pct=0.0, timeframe="5m",
        )
        self.db.record_result(r)
        assert self.db.avg_risk_reward() == 0.0

    def test_zero_sl_distance_excluded(self):
        r = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=102.0,
            stop_loss=100.0,  # same as entry → sl_dist = 0
            tp1=102.0, tp2=104.0, tp3=106.0,
            opened_at=time.time() - 3600, closed_at=time.time(),
            outcome="WIN", pnl_pct=2.0, timeframe="5m",
        )
        self.db.record_result(r)
        assert self.db.avg_risk_reward() == 0.0


class TestWinRateRolling:
    """Tests for Dashboard.win_rate_rolling()."""

    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        self.db = Dashboard(log_file=str(tmp_path / "db.json"))

    def test_empty_returns_zero(self):
        assert self.db.win_rate_rolling(days=7) == 0.0

    def test_recent_trade_included(self):
        self.db.record_result(_make_trade(outcome="WIN", pnl_pct=2.0))
        assert self.db.win_rate_rolling(days=7) == 100.0

    def test_old_trade_excluded(self):
        # Add an old (8-day-old) WIN — should not count in 7-day window
        old_result = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=102.0,
            stop_loss=98.0, tp1=102.0, tp2=104.0, tp3=106.0,
            opened_at=time.time() - 8 * 86400,  # 8 days ago
            closed_at=time.time() - 8 * 86400 + 3600,
            outcome="WIN", pnl_pct=2.0, timeframe="5m",
        )
        self.db.record_result(old_result)
        assert self.db.win_rate_rolling(days=7) == 0.0

    def test_30_day_includes_old(self):
        old_result = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=102.0,
            stop_loss=98.0, tp1=102.0, tp2=104.0, tp3=106.0,
            opened_at=time.time() - 8 * 86400,
            closed_at=time.time() - 8 * 86400 + 3600,
            outcome="WIN", pnl_pct=2.0, timeframe="5m",
        )
        self.db.record_result(old_result)
        assert self.db.win_rate_rolling(days=30) == 100.0


# ── NewsCalendar tests ────────────────────────────────────────────────────────

class TestNewsCalendar:
    def setup_method(self):
        self.cal = NewsCalendar(skip_window_minutes=60)

    def test_no_events_returns_false(self):
        assert self.cal.is_high_impact_imminent() is False

    def test_high_impact_event_within_window(self):
        event = NewsEvent(
            title="FOMC",
            timestamp=time.time() + 1800,  # 30 min from now
            impact="HIGH",
            currency="USD",
        )
        self.cal.add_event(event)
        assert self.cal.is_high_impact_imminent() is True

    def test_high_impact_event_outside_window(self):
        event = NewsEvent(
            title="FOMC",
            timestamp=time.time() + 7200,  # 2 hours from now
            impact="HIGH",
            currency="USD",
        )
        self.cal.add_event(event)
        assert self.cal.is_high_impact_imminent() is False

    def test_medium_impact_event_not_counted(self):
        event = NewsEvent(
            title="Retail Sales",
            timestamp=time.time() + 1800,
            impact="MEDIUM",
            currency="USD",
        )
        self.cal.add_event(event)
        assert self.cal.is_high_impact_imminent() is False

    def test_past_event_not_counted(self):
        event = NewsEvent(
            title="CPI",
            timestamp=time.time() - 3600,  # 1 hour ago
            impact="HIGH",
            currency="USD",
        )
        self.cal.add_event(event)
        assert self.cal.is_high_impact_imminent() is False

    def test_clear_removes_all_events(self):
        self.cal.add_event(
            NewsEvent("FOMC", time.time() + 1800, "HIGH", "USD")
        )
        self.cal.clear()
        assert self.cal.is_high_impact_imminent() is False

    def test_upcoming_high_impact_sorted(self):
        now = time.time()
        self.cal.load_events([
            NewsEvent("CPI", now + 3000, "HIGH", "USD"),
            NewsEvent("FOMC", now + 1000, "HIGH", "USD"),
        ])
        upcoming = self.cal.upcoming_high_impact()
        assert upcoming[0].title == "FOMC"
        assert upcoming[1].title == "CPI"

    def test_format_caution_message_no_events(self):
        msg = self.cal.format_caution_message()
        assert "No high-impact" in msg

    def test_format_caution_message_with_events(self):
        self.cal.add_event(
            NewsEvent("FOMC Rate Decision", time.time() + 1800, "HIGH", "USD")
        )
        msg = self.cal.format_caution_message()
        assert "FOMC" in msg
        assert "FROZEN" in msg

    def test_from_dict(self):
        event = NewsEvent.from_dict({
            "title": "CPI",
            "timestamp": 1700000000.0,
            "impact": "high",
            "currency": "usd",
        })
        assert event.impact == "HIGH"
        assert event.currency == "USD"
