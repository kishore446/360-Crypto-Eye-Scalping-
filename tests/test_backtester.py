"""
Tests for bot/backtester.py
============================
Covers the full signal lifecycle, metric calculations, and edge cases.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from bot.backtester import (
    Backtester,
    BacktestResult,
    HistoricalDataFetcher,
    SimulatedTrade,
    _calculate_max_drawdown,
    _compute_monthly_returns,
    _compute_result,
    _max_consecutive,
    _to_candle,
)
from bot.signal_engine import CandleData, Confidence, Side, SignalResult


# ── Fixtures & helpers ─────────────────────────────────────────────────────────

BASE_TS = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC in ms
_5M = 300_000                 # 5 minutes in ms
_4H = 14_400_000              # 4 hours in ms
_1D = 86_400_000              # 1 day in ms


def _row_5m(i: int, close: float, high_extra: float = 0.1, low_extra: float = 0.1) -> list:
    """Build a single 5m OHLCV row."""
    return [
        BASE_TS + i * _5M,
        close - 0.05,
        close + high_extra,
        close - low_extra,
        close,
        1000.0,
    ]


def _make_5m_rows(n: int = 80, base: float = 100.0) -> list[list]:
    """Return *n* generic rising 5m rows."""
    return [_row_5m(i, base + i * 0.01) for i in range(n)]


def _make_4h_rows(n: int = 20, base: float = 100.0) -> list[list]:
    # Start 30 days before BASE_TS so all rows are available at bar index 50
    start = BASE_TS - 30 * _1D
    rows = []
    for i in range(n):
        close = base + i * 0.5
        rows.append([start + i * _4H, close - 0.2, close + 0.3, close - 0.3, close, 5000.0])
    return rows


def _make_1d_rows(n: int = 30, base: float = 100.0) -> list[list]:
    # Start 30 days before BASE_TS so all rows are available at bar index 50
    start = BASE_TS - 30 * _1D
    rows = []
    for i in range(n):
        close = base + i * 1.0
        rows.append([start + i * _1D, close - 0.5, close + 1.0, close - 1.0, close, 50_000.0])
    return rows


def _make_signal(
    side: Side = Side.LONG,
    entry: float = 100.0,
    sl: float = 90.0,
) -> SignalResult:
    """Build a minimal SignalResult for mocking run_confluence_check."""
    risk = abs(entry - sl)
    direction = 1 if side == Side.LONG else -1
    tp1 = entry + direction * risk * 1.5
    tp2 = entry + direction * risk * 2.5
    tp3 = entry + direction * risk * 4.0
    return SignalResult(
        symbol="BTC",
        side=side,
        confidence=Confidence.HIGH,
        entry_low=entry - 0.1,
        entry_high=entry + 0.1,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        stop_loss=sl,
        structure_note="mock",
        context_note="mock",
        leverage_min=10,
        leverage_max=20,
        signal_id="mock_001",
    )


def _make_completed_trade(
    side: Side = Side.LONG,
    pnl_pct: float = 1.0,
    close_reason: str = "TP1",
    bars_held: int = 10,
    be_triggered: bool = False,
    opened_at: int = BASE_TS,
) -> SimulatedTrade:
    return SimulatedTrade(
        signal_id="t1",
        symbol="BTC",
        side=side,
        confidence="High",
        entry_price=100.0,
        stop_loss=90.0,
        tp1=115.0,
        tp2=125.0,
        tp3=140.0,
        opened_at=opened_at,
        closed_at=opened_at + bars_held * _5M,
        close_reason=close_reason,
        pnl_pct=pnl_pct,
        be_triggered=be_triggered,
        bars_held=bars_held,
    )


# ── _to_candle ─────────────────────────────────────────────────────────────────

def test_to_candle_basic():
    row = [1_000_000, 10.0, 12.0, 9.0, 11.0, 500.0]
    c = _to_candle(row)
    assert c.open == 10.0
    assert c.high == 12.0
    assert c.low == 9.0
    assert c.close == 11.0
    assert c.volume == 500.0


# ── Backtester — SL hits ───────────────────────────────────────────────────────

def _run_with_signal_and_bars(
    signal: SignalResult,
    exit_bars: list[list],
) -> BacktestResult:
    """
    Run Backtester with a mocked confluence check that fires once (returns
    *signal* when called with the matching side), followed by *exit_bars*
    that determine the trade outcome.
    """
    # 51 setup bars: signal fires at i=50, exit bars processed at i=51+
    five_m = _make_5m_rows(51)
    ts_after = five_m[-1][0]
    for i, bar in enumerate(exit_bars):
        bar[0] = ts_after + (i + 1) * _5M         # ensure ascending timestamps
    five_m = five_m + exit_bars

    four_h = _make_4h_rows(20)
    daily = _make_1d_rows(30)

    first_hit = [True]

    def _side_aware_mock(*args, **kwargs):
        if kwargs.get("side") == signal.side and first_hit[0]:
            first_hit[0] = False
            return signal
        return None

    with patch("bot.backtester.run_confluence_check", side_effect=_side_aware_mock):
        bt = Backtester(initial_capital=10_000.0, risk_per_trade=0.01)
        return bt.run("BTC", five_m, four_h, daily)


def test_sl_hit_long():
    """LONG trade: candle whose low <= SL closes the trade as SL."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    # Candle with low=89.0 — below SL of 90.0
    sl_bar = [0, 99.0, 100.0, 89.0, 91.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [sl_bar])
    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade.close_reason == "SL"
    assert trade.pnl_pct < 0


def test_sl_hit_short():
    """SHORT trade: candle whose high >= SL closes the trade as SL."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    # Candle with high=111.0 — above SL of 110.0
    sl_bar = [0, 101.0, 111.0, 99.0, 101.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [sl_bar])
    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade.close_reason == "SL"
    assert trade.pnl_pct < 0


def test_tp1_hit_long():
    """LONG trade: candle whose high >= TP1 closes the trade as TP1."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    tp1 = signal.tp1  # 115.0
    # low=100.5 > entry=100 ensures BE-SL is not hit; high reaches TP1
    tp1_bar = [0, 100.0, tp1 + 0.1, 100.5, 114.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp1_bar])
    assert result.total_trades == 1
    assert result.trades[0].close_reason == "TP1"
    assert result.trades[0].pnl_pct > 0


def test_tp1_hit_short():
    """SHORT trade: candle whose low <= TP1 closes the trade as TP1."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    tp1 = signal.tp1  # 85.0 for SHORT with 10-point risk × 1.5
    # high=99.5 < entry=100 ensures BE-SL is not hit; low reaches TP1
    tp1_bar = [0, 99.0, 99.5, tp1 - 0.1, 86.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp1_bar])
    assert result.total_trades == 1
    assert result.trades[0].close_reason == "TP1"
    assert result.trades[0].pnl_pct > 0


def test_tp2_hit_long():
    """LONG trade: candle reaching TP2 (but not TP3) → close as TP2."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    tp2 = signal.tp2  # 125.0
    # low=100.5 > entry ensures no BE-SL; high reaches TP2 but not TP3=140
    tp2_bar = [0, 124.0, tp2 + 0.1, 100.5, 124.5, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp2_bar])
    assert result.trades[0].close_reason == "TP2"
    assert result.trades[0].pnl_pct > 0


def test_tp2_hit_short():
    """SHORT trade: candle whose low <= TP2 → close as TP2."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    tp2 = signal.tp2  # 75.0
    # high=99.5 < entry ensures no BE-SL; low reaches TP2 but not TP3=60
    tp2_bar = [0, 76.0, 99.5, tp2 - 0.1, 76.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp2_bar])
    assert result.trades[0].close_reason == "TP2"
    assert result.trades[0].pnl_pct > 0


def test_tp3_hit_long():
    """LONG trade: candle reaching TP3 → close as TP3."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    tp3 = signal.tp3  # 140.0
    # low=100.5 > entry; high reaches TP3
    tp3_bar = [0, 139.0, tp3 + 0.1, 100.5, 139.5, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp3_bar])
    assert result.trades[0].close_reason == "TP3"
    assert result.trades[0].pnl_pct > 0


def test_tp3_hit_short():
    """SHORT trade: candle whose low <= TP3 → close as TP3."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    tp3 = signal.tp3  # 60.0
    # high=99.5 < entry; low reaches TP3
    tp3_bar = [0, 61.0, 99.5, tp3 - 0.1, 61.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp3_bar])
    assert result.trades[0].close_reason == "TP3"
    assert result.trades[0].pnl_pct > 0


# ── BE trigger sequence ────────────────────────────────────────────────────────

def test_be_trigger_then_sl_long():
    """
    LONG: after BE is triggered (price reached 50% of TP1 distance),
    a subsequent candle dropping to entry closes the trade as BE.
    """
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    # TP1 = 115.0, be_trigger at 50% → 107.5
    # Bar 1: triggers BE (high=108.0 >= 107.5), but no TP/SL exit
    be_bar = [0, 100.0, 108.0, 100.5, 107.0, 1000.0]   # low=100.5 > entry=100, no SL
    # Bar 2: price drops to entry (SL now = 100.0 after BE), low=99.8 <= 100.0
    sl_bar = [0, 100.0, 100.5, 99.8, 99.9, 1000.0]
    result = _run_with_signal_and_bars(signal, [be_bar, sl_bar])
    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade.be_triggered is True
    assert trade.close_reason == "BE"
    # PnL should be ~0 (closed at entry)
    assert abs(trade.pnl_pct) < 0.5


def test_be_trigger_then_sl_short():
    """
    SHORT: after BE triggered, price rising to entry → closes as BE.
    """
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    # TP1 = 85.0, be_trigger at 50% of distance → 92.5
    # Bar 1: triggers BE (low=92.0 <= 92.5), high=93.5 < sl=110 → no SL
    be_bar = [0, 93.0, 93.5, 92.0, 92.5, 1000.0]   # triggers BE
    # Bar 2: price rises to entry (sl now = 100.0), high=100.2 >= 100.0
    sl_bar = [0, 99.0, 100.2, 98.5, 100.1, 1000.0]
    result = _run_with_signal_and_bars(signal, [be_bar, sl_bar])
    trade = result.trades[0]
    assert trade.be_triggered is True
    assert trade.close_reason == "BE"
    assert abs(trade.pnl_pct) < 0.5


# ── SL checked before TP on same bar ─────────────────────────────────────────

def test_sl_before_tp_same_bar_long():
    """
    When a LONG candle's low is below SL AND high is above TP1 on the same
    bar, SL wins (conservative worst-case).
    """
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    # Same bar: low=89 (SL hit) AND high=116 (TP1 hit)
    both_bar = [0, 100.0, 116.0, 89.0, 100.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [both_bar])
    assert result.trades[0].close_reason == "SL"
    assert result.trades[0].pnl_pct < 0


def test_sl_before_tp_same_bar_short():
    """SHORT: same-bar SL+TP3 → SL wins."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    tp3 = signal.tp3  # 60.0
    # Same bar: high=111 (SL hit at 110) AND low=59 (TP3 hit)
    both_bar = [0, 100.0, 111.0, 59.0, 100.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [both_bar])
    assert result.trades[0].close_reason == "SL"
    assert result.trades[0].pnl_pct < 0


# ── Stale close ────────────────────────────────────────────────────────────────

def test_stale_close():
    """Trade that never hits SL or TP closes as STALE after stale_bars."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    # 2 stale hours = 24 bars; use 30 neutral bars (no SL/TP touch)
    neutral_bars = [
        [0, 100.0, 100.2, 99.8, 100.1, 1000.0]
        for _ in range(30)
    ]
    # 51 setup bars: signal fires at i=50, neutral bars at i=51+
    five_m = _make_5m_rows(51)
    ts_after = five_m[-1][0]
    for i, bar in enumerate(neutral_bars):
        bar[0] = ts_after + (i + 1) * _5M
    five_m = five_m + neutral_bars

    first_hit = [True]

    def _once_long(*a, **kw):
        if kw.get("side") == Side.LONG and first_hit[0]:
            first_hit[0] = False
            return signal
        return None

    with patch("bot.backtester.run_confluence_check", side_effect=_once_long):
        bt = Backtester(stale_hours=2.0, initial_capital=10_000.0, risk_per_trade=0.01)
        result = bt.run("BTC", five_m, _make_4h_rows(), _make_1d_rows())

    assert result.total_trades == 1
    assert result.trades[0].close_reason == "STALE"
    assert result.stale_closes == 1


# ── BacktestResult metric calculations ─────────────────────────────────────────

def test_win_rate_calculation():
    trades = [
        _make_completed_trade(pnl_pct=2.0, close_reason="TP1"),
        _make_completed_trade(pnl_pct=3.0, close_reason="TP2"),
        _make_completed_trade(pnl_pct=-1.0, close_reason="SL"),
    ]
    result = _compute_result("BTC", trades, [10000, 10200, 10500, 10400], 10000.0)
    assert result.total_trades == 3
    assert result.wins == 2
    assert result.losses == 1
    assert abs(result.win_rate - 2 / 3) < 1e-9


def test_profit_factor_calculation():
    trades = [
        _make_completed_trade(pnl_pct=4.0, close_reason="TP2"),
        _make_completed_trade(pnl_pct=-1.0, close_reason="SL"),
        _make_completed_trade(pnl_pct=-1.0, close_reason="SL"),
    ]
    result = _compute_result("BTC", trades, [10000, 10400, 10300, 10200], 10000.0)
    # PF = 4 / 2 = 2.0
    assert abs(result.profit_factor - 2.0) < 1e-9


def test_profit_factor_infinite_when_no_losses():
    trades = [
        _make_completed_trade(pnl_pct=1.0, close_reason="TP1"),
        _make_completed_trade(pnl_pct=2.0, close_reason="TP2"),
    ]
    result = _compute_result("BTC", trades, [10000, 10100, 10300], 10000.0)
    assert result.profit_factor == float("inf")


def test_sharpe_ratio_positive_for_winning_trades():
    trades = [_make_completed_trade(pnl_pct=float(i)) for i in range(1, 11)]
    equity = [10000.0 + i * 100 for i in range(11)]
    result = _compute_result("BTC", trades, equity, 10000.0)
    assert result.sharpe_ratio > 0


def test_empty_result():
    result = _compute_result("BTC", [], [10000.0], 10000.0)
    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.profit_factor == 0.0
    assert result.sharpe_ratio == 0.0
    assert result.max_drawdown_pct == 0.0


# ── Equity curve and drawdown ─────────────────────────────────────────────────

def test_equity_curve_grows_with_wins():
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    tp3_bar = [0, 139.0, 141.0, 100.5, 139.5, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp3_bar])
    assert result.equity_curve[-1] > result.equity_curve[0]


def test_equity_curve_shrinks_with_loss():
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    sl_bar = [0, 99.0, 100.0, 89.0, 91.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [sl_bar])
    assert result.equity_curve[-1] < result.equity_curve[0]


def test_max_drawdown_basic():
    equity = [10000.0, 11000.0, 9500.0, 10000.0]
    dd_pct, dd_dur = _calculate_max_drawdown(equity)
    # From peak 11000 to 9500 → (11000-9500)/11000 * 100 ≈ 13.6%
    assert abs(dd_pct - (11000 - 9500) / 11000 * 100) < 1e-6
    assert dd_dur == 2  # 2 bars below peak


def test_max_drawdown_empty():
    assert _calculate_max_drawdown([]) == (0.0, 0)
    assert _calculate_max_drawdown([10000.0]) == (0.0, 0)


# ── Consecutive wins/losses ───────────────────────────────────────────────────

def test_max_consecutive_wins():
    trades = [
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=-1.0),
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=1.0),
    ]
    assert _max_consecutive(trades, positive=True) == 3


def test_max_consecutive_losses():
    trades = [
        _make_completed_trade(pnl_pct=-1.0),
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=-1.0),
        _make_completed_trade(pnl_pct=-1.0),
        _make_completed_trade(pnl_pct=-1.0),
    ]
    assert _max_consecutive(trades, positive=False) == 3


def test_max_consecutive_via_compute_result():
    trades = [
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=1.0),
        _make_completed_trade(pnl_pct=-1.0),
        _make_completed_trade(pnl_pct=1.0),
    ]
    result = _compute_result("BTC", trades, [10000.0] * 5, 10000.0)
    assert result.max_consecutive_wins == 2
    assert result.max_consecutive_losses == 1


# ── Monthly returns ────────────────────────────────────────────────────────────

def test_monthly_returns():
    jan_ms = 1_704_067_200_000  # 2024-01-01
    feb_ms = 1_706_745_600_000  # 2024-02-01
    trades = [
        _make_completed_trade(pnl_pct=2.0, opened_at=jan_ms),
        _make_completed_trade(pnl_pct=3.0, opened_at=jan_ms),
        _make_completed_trade(pnl_pct=-1.0, opened_at=feb_ms),
    ]
    monthly = _compute_monthly_returns(trades)
    assert "2024-01" in monthly
    assert "2024-02" in monthly
    assert abs(monthly["2024-01"] - 5.0) < 1e-9
    assert abs(monthly["2024-02"] - (-1.0)) < 1e-9


# ── CSV export ─────────────────────────────────────────────────────────────────

def test_csv_export():
    trades = [
        _make_completed_trade(pnl_pct=2.0, close_reason="TP2"),
        _make_completed_trade(pnl_pct=-1.0, close_reason="SL"),
    ]
    result = _compute_result("BTC", trades, [10000.0, 10200.0, 10100.0], 10000.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_out.csv")
        result.to_csv(path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        assert len(lines) == 3  # header + 2 trade rows
        assert "signal_id" in lines[0]
        assert "TP2" in lines[1]
        assert "SL" in lines[2]


# ── Position sizing & equity compounding ─────────────────────────────────────

def test_position_sizing_sl_loses_risk_amount():
    """Losing trade at SL should reduce equity by approximately risk_per_trade."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    sl_bar = [0, 99.0, 100.0, 89.0, 91.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [sl_bar])
    initial = result.equity_curve[0]
    final = result.equity_curve[-1]
    loss_frac = (initial - final) / initial
    # Should be close to risk_per_trade (1%)
    assert 0.005 < loss_frac < 0.03


def test_position_sizing_tp3_gains_more_than_risk():
    """Winning TP3 trade should return a multiple of the risk amount."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    tp3_bar = [0, 139.0, 141.0, 138.5, 139.5, 1000.0]
    result = _run_with_signal_and_bars(signal, [tp3_bar])
    initial = result.equity_curve[0]
    final = result.equity_curve[-1]
    gain_frac = (final - initial) / initial
    # TP3 = 4R; risk=1%; gain should be ~4%
    assert gain_frac > 0.02


# ── MFE / MAE tracking ────────────────────────────────────────────────────────

def test_mfe_tracking_long():
    """MFE must reflect the highest point reached during the trade."""
    signal = _make_signal(Side.LONG, entry=100.0, sl=90.0)
    # Bar 1: favorable move to 110 (MFE=10%), then bar 2: SL hit
    high_bar = [0, 100.0, 110.0, 100.5, 108.0, 1000.0]   # high=110, low=100.5
    sl_bar = [0, 99.0, 100.0, 89.0, 91.0, 1000.0]
    result = _run_with_signal_and_bars(signal, [high_bar, sl_bar])
    trade = result.trades[0]
    # MFE from bar 1: (110-100)/100*100 = 10%
    assert trade.max_favorable_excursion >= 9.9
    assert trade.max_adverse_excursion > 0


def test_mae_tracking_short():
    """MAE for SHORT must reflect the highest candle high during the trade."""
    signal = _make_signal(Side.SHORT, entry=100.0, sl=110.0)
    # Bar 1: adverse move (high=105 → MAE=5%), no exit
    adv_bar = [0, 100.0, 105.0, 84.0, 84.5, 1000.0]   # high=105 (adverse), low=84 < tp1=85
    result = _run_with_signal_and_bars(signal, [adv_bar])
    trade = result.trades[0]
    # MAE: (105 - 100) / 100 * 100 = 5%
    assert trade.max_adverse_excursion >= 4.9


# ── BacktestResult.summary() ──────────────────────────────────────────────────

def test_summary_contains_key_fields():
    trades = [_make_completed_trade(pnl_pct=1.0), _make_completed_trade(pnl_pct=-1.0)]
    result = _compute_result("BTC", trades, [10000.0, 10100.0, 10000.0], 10000.0)
    s = result.summary()
    assert "BTC" in s
    assert "Trades" in s
    assert "Win Rate" in s
    assert "PF" in s
    assert "Sharpe" in s
    assert "MaxDD" in s


# ── Long / short breakdown ─────────────────────────────────────────────────────

def test_long_short_breakdown():
    trades = [
        _make_completed_trade(side=Side.LONG, pnl_pct=1.0),
        _make_completed_trade(side=Side.LONG, pnl_pct=-1.0),
        _make_completed_trade(side=Side.SHORT, pnl_pct=2.0),
    ]
    result = _compute_result("BTC", trades, [10000.0] * 4, 10000.0)
    assert result.long_trades == 2
    assert result.short_trades == 1
    assert result.long_wins == 1
    assert result.short_wins == 1


# ── HistoricalDataFetcher ─────────────────────────────────────────────────────

def test_historical_data_fetcher_paginates():
    """HistoricalDataFetcher should concatenate multiple exchange.fetch_ohlcv calls."""
    mock_exchange = MagicMock()
    page1 = [[i * _5M, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(3)]
    page2 = [[3 * _5M + i * _5M, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(2)]
    # Third call returns empty → stop pagination
    mock_exchange.fetch_ohlcv.side_effect = [page1, page2, []]

    fetcher = HistoricalDataFetcher(mock_exchange)
    rows = fetcher.fetch("BTC/USDT:USDT", "5m", 0, 10 * _5M)

    assert len(rows) == 5
    assert mock_exchange.fetch_ohlcv.call_count >= 2


def test_historical_data_fetcher_deduplicates():
    """Duplicate timestamps should be removed."""
    mock_exchange = MagicMock()
    dup_rows = [
        [BASE_TS, 100.0, 101.0, 99.0, 100.0, 1000.0],
        [BASE_TS, 100.0, 101.0, 99.0, 100.0, 1000.0],  # duplicate
        [BASE_TS + _5M, 101.0, 102.0, 100.0, 101.0, 1000.0],
    ]
    mock_exchange.fetch_ohlcv.side_effect = [dup_rows, []]

    fetcher = HistoricalDataFetcher(mock_exchange)
    rows = fetcher.fetch("BTC/USDT:USDT", "5m", BASE_TS, BASE_TS + _5M)
    assert len(rows) == 2  # duplicates removed
