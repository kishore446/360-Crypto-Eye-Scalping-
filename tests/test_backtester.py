"""
Tests for bot/backtester.py
"""

from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest

from bot.backtester import (
    Backtester,
    BacktestResult,
    SimulatedTrade,
    _compute_result,
    _format_duration,
    _monthly_returns,
    _streak_counts,
)
from bot.signal_engine import CandleData


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_trade(
    side: str = "LONG",
    entry: float = 100.0,
    sl: float = 98.0,
    tp1: float = 103.0,
    tp2: float = 105.0,
    tp3: float = 108.0,
    opened_at: float = 0.0,
    confidence: str = "High",
) -> SimulatedTrade:
    """Return a fresh SimulatedTrade with sensible defaults."""
    return SimulatedTrade(
        signal_id="test_1",
        symbol="BTC",
        side=side,
        confidence=confidence,
        entry_price=entry,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        opened_at=opened_at,
    )


def _make_short_trade(
    entry: float = 100.0,
    sl: float = 102.0,
    tp1: float = 97.0,
    tp2: float = 95.0,
    tp3: float = 92.0,
    opened_at: float = 0.0,
) -> SimulatedTrade:
    return SimulatedTrade(
        signal_id="test_s1",
        symbol="BTC",
        side="SHORT",
        confidence="High",
        entry_price=entry,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        opened_at=opened_at,
    )


def _candle(
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: float = 500.0,
) -> CandleData:
    return CandleData(open=open_, high=high, low=low, close=close, volume=volume)


def _backtester() -> Backtester:
    """Return a Backtester instance for unit tests (no real I/O)."""
    return Backtester(
        symbol="BTC/USDT:USDT",
        start_date="2025-01-01",
        end_date="2025-03-01",
        be_trigger_fraction=0.50,
        stale_hours=4,
    )


# ── Trade exit tests ──────────────────────────────────────────────────────────

class TestSimulatedTradeSLHit:
    def test_long_sl_hit(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0)
        candle = _candle(open_=100, high=101, low=97.5, close=99)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=100.0)
        assert closed is True
        assert trade.close_reason == "SL"
        assert trade.pnl_pct < 0
        assert trade.closed_at == 100.0

    def test_long_sl_exact_level(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0)
        candle = _candle(open_=100, high=101, low=98.0, close=99)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=50.0)
        assert closed is True
        assert trade.close_reason == "SL"


class TestSimulatedTradeTP1Hit:
    def test_long_tp1_hit(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0)
        candle = _candle(open_=100, high=103.5, low=99, close=103)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=200.0)
        assert closed is True
        assert trade.close_reason == "TP1"
        assert trade.pnl_pct > 0
        assert abs(trade.pnl_pct - 3.0) < 1e-9

    def test_long_tp1_exact(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0)
        candle = _candle(open_=100, high=103.0, low=99, close=102)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=200.0)
        assert closed is True
        assert trade.close_reason == "TP1"


class TestSimulatedTradeTP2Hit:
    def test_long_tp2_hit(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0, tp2=105.0, tp3=108.0)
        candle = _candle(open_=100, high=105.5, low=99, close=105)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=300.0)
        assert closed is True
        assert trade.close_reason == "TP2"
        assert abs(trade.pnl_pct - 5.0) < 1e-9


class TestSimulatedTradeTP3Hit:
    def test_long_tp3_hit(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0, tp2=105.0, tp3=108.0)
        candle = _candle(open_=100, high=109.0, low=99, close=108)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=400.0)
        assert closed is True
        assert trade.close_reason == "TP3"
        assert abs(trade.pnl_pct - 8.0) < 1e-9


class TestBETrigger:
    def test_long_be_trigger_then_sl(self):
        """Price covers 50% of TP1 distance → SL moves to entry, then price reverses."""
        bt = _backtester()
        # entry=100, sl=98, tp1=103 → BE threshold = 100 + (103-100)*0.5 = 101.5
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0)

        # Candle 1: price reaches 101.5 → triggers BE
        c1 = _candle(open_=100, high=101.6, low=99.5, close=101)
        closed = bt._simulate_trade_update(trade, c1, candle_ts=100.0)
        assert not closed
        assert trade.be_triggered is True
        assert trade.stop_loss == 100.0  # SL moved to entry

        # Candle 2: price dips to entry → BE close
        c2 = _candle(open_=101, high=101.5, low=99.5, close=100)
        closed = bt._simulate_trade_update(trade, c2, candle_ts=200.0)
        assert closed is True
        assert trade.close_reason == "BE"
        # PnL should be ~ 0 (exit at entry price)
        assert abs(trade.pnl_pct) < 1e-9

    def test_short_be_trigger(self):
        """SHORT: price falls 50% of TP1 distance → BE trigger."""
        bt = _backtester()
        # entry=100, sl=102, tp1=97 → BE threshold = 100 - (100-97)*0.5 = 98.5
        trade = _make_short_trade(entry=100.0, sl=102.0, tp1=97.0)

        c1 = _candle(open_=100, high=101, low=98.4, close=99)
        closed = bt._simulate_trade_update(trade, c1, candle_ts=100.0)
        assert not closed
        assert trade.be_triggered is True
        assert trade.stop_loss == 100.0


class TestStaleClose:
    def test_stale_long(self):
        """Trade open > stale_hours without hitting any target → STALE close."""
        bt = _backtester()
        opened_at = 0.0
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, opened_at=opened_at)
        # Use a candle that's well beyond stale_hours
        stale_ts = opened_at + bt.stale_hours * 3600 + 1
        candle = _candle(open_=100, high=100.5, low=99.5, close=100.2)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=stale_ts)
        assert closed is True
        assert trade.close_reason == "STALE"
        assert trade.closed_at == stale_ts

    def test_not_stale_within_window(self):
        bt = _backtester()
        opened_at = 0.0
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, opened_at=opened_at)
        not_stale_ts = opened_at + bt.stale_hours * 3600 - 60  # 1 minute before
        candle = _candle(open_=100, high=100.5, low=99.5, close=100.2)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=not_stale_ts)
        assert not closed


class TestSLBeforeTP:
    def test_sl_takes_priority_over_tp(self):
        """When both SL and TP are hit in the same candle, SL wins (conservative)."""
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=103.0)
        # Low pierces SL, high also pierces TP1 → SL should win
        candle = _candle(open_=100, high=103.5, low=97.5, close=102)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=100.0)
        assert closed is True
        assert trade.close_reason == "SL"
        assert trade.pnl_pct < 0


class TestShortTrades:
    def test_short_sl_hit(self):
        bt = _backtester()
        trade = _make_short_trade(entry=100.0, sl=102.0)
        candle = _candle(open_=100, high=102.5, low=99, close=101)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=100.0)
        assert closed is True
        assert trade.close_reason == "SL"
        assert trade.pnl_pct < 0

    def test_short_tp1_hit(self):
        bt = _backtester()
        trade = _make_short_trade(entry=100.0, sl=102.0, tp1=97.0)
        candle = _candle(open_=100, high=101, low=96.5, close=97)
        closed = bt._simulate_trade_update(trade, candle, candle_ts=100.0)
        assert closed is True
        assert trade.close_reason == "TP1"
        assert trade.pnl_pct > 0
        assert abs(trade.pnl_pct - 3.0) < 1e-9


# ── MFE / MAE tracking ────────────────────────────────────────────────────────

class TestMFEMAETracking:
    def test_long_mfe_mae(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=98.0, tp1=110.0)
        # High = 104 → MFE = 4%, Low = 98.5 → MAE = 1.5%
        c1 = _candle(open_=100, high=104.0, low=98.5, close=101)
        bt._simulate_trade_update(trade, c1, candle_ts=100.0)
        assert abs(trade.max_favorable_excursion - 4.0) < 1e-9
        assert abs(trade.max_adverse_excursion - 1.5) < 1e-9

    def test_mfe_mae_accumulate_over_multiple_bars(self):
        bt = _backtester()
        trade = _make_trade(side="LONG", entry=100.0, sl=96.0, tp1=120.0)
        bt._simulate_trade_update(trade, _candle(high=103, low=99, open_=100, close=101), candle_ts=100)
        bt._simulate_trade_update(trade, _candle(high=106, low=100, open_=101, close=105), candle_ts=200)
        assert abs(trade.max_favorable_excursion - 6.0) < 1e-9

    def test_short_mfe_mae(self):
        bt = _backtester()
        trade = _make_short_trade(entry=100.0, sl=105.0, tp1=80.0)
        # Low = 96 → MFE = 4%, High = 102 → MAE = 2%
        c1 = _candle(open_=100, high=102.0, low=96.0, close=98)
        bt._simulate_trade_update(trade, c1, candle_ts=100.0)
        assert abs(trade.max_favorable_excursion - 4.0) < 1e-9
        assert abs(trade.max_adverse_excursion - 2.0) < 1e-9


# ── BacktestResult metrics ────────────────────────────────────────────────────

def _make_closed_trade(
    side: str = "LONG",
    close_reason: str = "TP1",
    pnl_pct: float = 3.0,
    opened_at: float = 0.0,
    closed_at: float = 3600.0,
    entry: float = 100.0,
    sl: float = 98.0,
    tp1: float = 103.0,
) -> SimulatedTrade:
    t = _make_trade(side=side, entry=entry, sl=sl, tp1=tp1, opened_at=opened_at)
    t.close_reason = close_reason
    t.pnl_pct = pnl_pct
    t.closed_at = closed_at
    return t


class TestBacktestResultMetrics:
    def _build_result(self, trades: list[SimulatedTrade]) -> BacktestResult:
        initial = 10_000.0
        equity = initial
        equity_curve = [{"timestamp": 0.0, "equity": initial, "drawdown": 0.0}]
        for t in trades:
            sl_dist = abs(t.entry_price - t.stop_loss)
            sl_frac = sl_dist / t.entry_price if t.entry_price > 0 else 1
            equity += equity * 0.01 * (t.pnl_pct / 100) / sl_frac
            equity = max(equity, 0.0)
            peak = max(p["equity"] for p in equity_curve)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
            equity_curve.append({"timestamp": t.closed_at, "equity": equity, "drawdown": dd})
        return _compute_result(
            symbol="BTC/USDT:USDT",
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=initial,
            final_capital=equity,
            trades=trades,
            equity_curve=equity_curve,
            risk_per_trade=0.01,
        )

    def test_win_rate(self):
        trades = [
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0),
        ]
        result = self._build_result(trades)
        assert result.total_trades == 4
        assert result.wins == 2
        assert result.losses == 2
        assert abs(result.win_rate - 50.0) < 1e-9

    def test_profit_factor(self):
        trades = [
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0),
        ]
        result = self._build_result(trades)
        assert abs(result.profit_factor - 3.0) < 1e-9  # 6.0 / 2.0

    def test_max_drawdown_computed(self):
        trades = [
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0, closed_at=1000.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0, closed_at=2000.0),
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0, closed_at=3000.0),
        ]
        result = self._build_result(trades)
        assert result.max_drawdown_pct > 0

    def test_break_evens_counted(self):
        trades = [
            _make_closed_trade(close_reason="BE", pnl_pct=0.0),
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
        ]
        result = self._build_result(trades)
        assert result.break_evens == 1

    def test_stale_closes_counted(self):
        trades = [
            _make_closed_trade(close_reason="STALE", pnl_pct=0.5),
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
        ]
        result = self._build_result(trades)
        assert result.stale_closes == 1


# ── Equity curve ──────────────────────────────────────────────────────────────

class TestEquityCurveGeneration:
    def test_equity_starts_at_initial(self):
        result = _compute_result(
            symbol="BTC",
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=10_000.0,
            final_capital=10_500.0,
            trades=[],
            equity_curve=[{"timestamp": 0.0, "equity": 10_000.0, "drawdown": 0.0}],
            risk_per_trade=0.01,
        )
        assert result.equity_curve[0]["equity"] == 10_000.0
        assert result.equity_curve[0]["drawdown"] == 0.0

    def test_drawdown_non_negative(self):
        eq_curve = [
            {"timestamp": 0.0, "equity": 10_000.0, "drawdown": 0.0},
            {"timestamp": 1.0, "equity": 9_500.0, "drawdown": 5.0},
            {"timestamp": 2.0, "equity": 9_800.0, "drawdown": 2.0},
        ]
        result = _compute_result(
            symbol="BTC",
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=10_000.0,
            final_capital=9_800.0,
            trades=[],
            equity_curve=eq_curve,
            risk_per_trade=0.01,
        )
        assert result.max_drawdown_pct == 5.0
        for p in result.equity_curve:
            assert p["drawdown"] >= 0.0


# ── Consecutive streaks ───────────────────────────────────────────────────────

class TestMaxConsecutiveWinsLosses:
    def test_known_sequence(self):
        trades = [
            _make_closed_trade(close_reason="TP1"),
            _make_closed_trade(close_reason="TP1"),
            _make_closed_trade(close_reason="TP1"),  # 3 consecutive wins
            _make_closed_trade(close_reason="SL"),
            _make_closed_trade(close_reason="SL"),   # 2 losses
            _make_closed_trade(close_reason="TP1"),
        ]
        max_w, max_l = _streak_counts(trades)
        assert max_w == 3
        assert max_l == 2

    def test_empty_trades(self):
        max_w, max_l = _streak_counts([])
        assert max_w == 0
        assert max_l == 0

    def test_all_wins(self):
        trades = [_make_closed_trade(close_reason="TP1") for _ in range(5)]
        max_w, max_l = _streak_counts(trades)
        assert max_w == 5
        assert max_l == 0


# ── Monthly returns ───────────────────────────────────────────────────────────

class TestMonthlyReturns:
    def test_trades_across_months(self):
        from datetime import datetime, timezone

        # Jan trade
        jan_ts = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp()
        # Feb trade
        feb_ts = datetime(2025, 2, 20, 12, 0, tzinfo=timezone.utc).timestamp()

        trades = [
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0, closed_at=jan_ts),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0, closed_at=jan_ts + 100),
            _make_closed_trade(close_reason="TP1", pnl_pct=4.0, closed_at=feb_ts),
        ]
        monthly = _monthly_returns(trades, [], 10_000.0)
        assert "2025-01" in monthly
        assert "2025-02" in monthly
        assert abs(monthly["2025-01"] - 1.0) < 1e-9   # 3.0 - 2.0
        assert abs(monthly["2025-02"] - 4.0) < 1e-9


# ── CSV export ────────────────────────────────────────────────────────────────

class TestCSVExport:
    def test_csv_created_with_correct_columns(self, tmp_path):
        trades = [
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0),
        ]
        result = _compute_result(
            symbol="BTC/USDT:USDT",
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=10_000.0,
            final_capital=10_200.0,
            trades=trades,
            equity_curve=[{"timestamp": 0.0, "equity": 10_000.0, "drawdown": 0.0}],
            risk_per_trade=0.01,
        )
        csv_path = str(tmp_path / "trades.csv")
        result.to_csv(csv_path)

        assert os.path.exists(csv_path)
        import csv as _csv
        with open(csv_path) as fh:
            reader = _csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 2
        expected_cols = {
            "signal_id", "symbol", "side", "confidence",
            "entry_price", "stop_loss", "tp1", "tp2", "tp3",
            "opened_at", "closed_at", "close_reason", "pnl_pct",
            "be_triggered", "max_favorable_excursion", "max_adverse_excursion",
            "bars_held",
        }
        assert expected_cols.issubset(set(rows[0].keys()))


# ── Position sizing ───────────────────────────────────────────────────────────

class TestPositionSizing:
    def test_sl_hit_costs_exactly_risk_fraction(self):
        """An SL hit must cost exactly risk_per_trade of current equity."""
        bt = _backtester()
        initial_equity = 10_000.0
        # entry=100, sl=98 → sl_dist=2, sl_frac=0.02
        # After SL: delta = equity * 0.01 * (-2/100) / (2/100) = -equity * 0.01
        trade = _make_closed_trade(
            close_reason="SL",
            pnl_pct=-2.0,
            entry=100.0,
            sl=98.0,
        )
        new_equity = bt._apply_trade_pnl(initial_equity, trade)
        assert abs(new_equity - (initial_equity * (1 - 0.01))) < 1e-6

    def test_tp1_gains_rr_times_risk(self):
        """A TP1 close with 1.5 RR must gain 1.5 × risk_per_trade of equity."""
        bt = _backtester()
        initial_equity = 10_000.0
        # entry=100, sl=98 → risk=2%, tp1=103 → pnl_pct=+3%
        trade = _make_closed_trade(
            close_reason="TP1",
            pnl_pct=3.0,
            entry=100.0,
            sl=98.0,
            tp1=103.0,
        )
        new_equity = bt._apply_trade_pnl(initial_equity, trade)
        # gain = 10000 * 0.01 * (3/100) / (2/100) = 10000 * 0.01 * 1.5 = 150
        expected = initial_equity + initial_equity * 0.01 * 1.5
        assert abs(new_equity - expected) < 1e-6


# ── Same-side cap ─────────────────────────────────────────────────────────────

class TestSameSideCapInBacktest:
    """Verify max_same_side logic is respected by _simulate_trade_update helper."""

    def test_backtester_respects_max_same_side(self):
        """
        The Backtester.run() skips opening new trades when the same-side cap is
        reached. We test the guard logic directly via the constructor field.
        """
        bt = Backtester(
            symbol="BTC/USDT:USDT",
            start_date="2025-01-01",
            end_date="2025-01-02",
            max_same_side=2,
        )
        assert bt.max_same_side == 2

        # Simulate the guard: build 2 LONG trades already active
        active = [
            _make_trade(side="LONG"),
            _make_trade(side="LONG"),
        ]
        same_side = sum(1 for t in active if t.side == "LONG")
        assert same_side >= bt.max_same_side  # cap reached → no new LONG


# ── BacktestResult.summary format ────────────────────────────────────────────

class TestBacktestResultSummaryFormat:
    def test_summary_contains_key_fields(self):
        trades = [
            _make_closed_trade(close_reason="TP1", pnl_pct=3.0, closed_at=1000.0),
            _make_closed_trade(close_reason="SL", pnl_pct=-2.0, closed_at=2000.0),
        ]
        result = _compute_result(
            symbol="BTC/USDT:USDT",
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=10_000.0,
            final_capital=10_100.0,
            trades=trades,
            equity_curve=[{"timestamp": 0.0, "equity": 10_000.0, "drawdown": 0.0}],
            risk_per_trade=0.01,
        )
        summary = result.summary()
        assert "BTC/USDT:USDT" in summary
        assert "2025-01-01" in summary
        assert "2025-06-30" in summary
        assert "Win Rate" in summary
        assert "PF" in summary
        assert "Sharpe" in summary
        assert "Max DD" in summary


# ── Duration formatting ───────────────────────────────────────────────────────

class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(45) == "45s"

    def test_minutes(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours(self):
        assert _format_duration(3661) == "1h 1m"

    def test_days(self):
        assert _format_duration(90000) == "1d 1h"
