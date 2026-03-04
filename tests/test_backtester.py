"""
Tests for bot/backtester.py
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from bot.backtester import (
    DEFAULT_BE_TRIGGER_FRACTION,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_STALE_HOURS,
    DEFAULT_TP1_RR,
    DEFAULT_TP2_RR,
    DEFAULT_TP3_RR,
    Backtester,
    BacktestResult,
    HistoricalDataFetcher,
    SimulatedTrade,
    _advance_trade,
    _bar_to_dt,
    _build_result,
    _calc_pnl,
    _close_trade,
    _htf_window_tail,
    _max_consecutive,
    _OpenTrade,
)
from bot.signal_engine import CandleData, Side


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _bullish_daily(n: int = 25, base: float = 100.0) -> list[CandleData]:
    return [
        CandleData(
            open=base + i,
            high=base + i + 1,
            low=base + i - 0.5,
            close=base + i + 0.8,
            volume=1000.0,
        )
        for i in range(n)
    ]


def _bearish_daily(n: int = 25, base: float = 200.0) -> list[CandleData]:
    return [
        CandleData(
            open=base - i,
            high=base - i + 0.5,
            low=base - i - 1,
            close=base - i - 0.8,
            volume=1000.0,
        )
        for i in range(n)
    ]


def _bullish_4h(n: int = 15, base: float = 100.0) -> list[CandleData]:
    return [
        CandleData(
            open=base + i * 0.5,
            high=base + i * 0.5 + 0.5,
            low=base + i * 0.5 - 0.3,
            close=base + i * 0.5 + 0.4,
            volume=500.0,
        )
        for i in range(n)
    ]


def _bearish_4h(n: int = 15, base: float = 200.0) -> list[CandleData]:
    return [
        CandleData(
            open=base - i * 0.5,
            high=base - i * 0.5 + 0.3,
            low=base - i * 0.5 - 0.5,
            close=base - i * 0.5 - 0.4,
            volume=500.0,
        )
        for i in range(n)
    ]


def _flat_candles(n: int, price: float = 100.0) -> list[CandleData]:
    """Candles that do not trigger any confluence condition."""
    return [
        CandleData(open=price, high=price + 0.01, low=price - 0.01, close=price, volume=100.0)
        for _ in range(n)
    ]


def _make_open_trade(
    side: Side = Side.LONG,
    entry: float = 100.0,
    stop_loss: float = 98.0,
    tp1: float = 103.0,
    tp2: float = 105.0,
    tp3: float = 108.0,
) -> _OpenTrade:
    return _OpenTrade(
        signal_id="SIG-TEST",
        symbol="BTC",
        side=side,
        confidence="High",
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        opened_at_bar=0,
        bars_held=0,
        be_triggered=False,
        max_fav=0.0,
        max_adv=0.0,
    )


# ── Helper function tests ─────────────────────────────────────────────────────


class TestBarToDt:
    def test_bar_zero_is_epoch(self) -> None:
        from bot.backtester import _EPOCH
        assert _bar_to_dt(0) == _EPOCH

    def test_bar_one_is_5m_after_epoch(self) -> None:
        from bot.backtester import _EPOCH
        from datetime import timedelta
        assert _bar_to_dt(1) == _EPOCH + timedelta(seconds=300)

    def test_large_bar_index_does_not_overflow(self) -> None:
        """A 1-year backtest has ~105 120 5m bars — must not raise."""
        dt = _bar_to_dt(105_120)
        assert dt >= datetime(2000, 1, 1, tzinfo=timezone.utc)


class TestHtfWindowTail:
    def test_zero_returns_zero(self) -> None:
        assert _htf_window_tail(0, 48, 100) == 0

    def test_capped_at_total(self) -> None:
        assert _htf_window_tail(10_000, 48, 50) == 50

    def test_proportional_advance(self) -> None:
        # After 96 5m bars (2 × 4H candles), tail should be 2
        assert _htf_window_tail(96, 48, 100) == 2


# ── HistoricalDataFetcher tests ───────────────────────────────────────────────


class TestHistoricalDataFetcher:
    def test_fetch_single_page(self) -> None:
        """Fetch returns CandleData when exchange returns one page."""
        raw = [[1_000_000, 1.0, 2.0, 0.5, 1.8, 100.0]]
        mock_ex = MagicMock()
        mock_ex.fetch_ohlcv.return_value = raw
        fetcher = HistoricalDataFetcher(exchange=mock_ex, sleep_seconds=0)
        result = fetcher.fetch("BTC/USDT:USDT", "5m", 0, 2_000_000)
        assert len(result) == 1
        c = result[0]
        assert c.open == 1.0
        assert c.high == 2.0
        assert c.low == 0.5
        assert c.close == 1.8
        assert c.volume == 100.0

    def test_fetch_empty_returns_empty(self) -> None:
        """Empty exchange response returns empty list."""
        mock_ex = MagicMock()
        mock_ex.fetch_ohlcv.return_value = []
        fetcher = HistoricalDataFetcher(exchange=mock_ex, sleep_seconds=0)
        result = fetcher.fetch("BTC/USDT:USDT", "5m", 0, 1_000_000)
        assert result == []

    def test_fetch_filters_out_of_range(self) -> None:
        """Candles outside [since_ms, until_ms) are excluded."""
        raw = [
            [500, 1.0, 2.0, 0.5, 1.8, 10.0],    # before since
            [1000, 1.1, 2.1, 0.6, 1.9, 20.0],   # inside
            [2000, 1.2, 2.2, 0.7, 2.0, 30.0],   # at/after until → excluded
        ]
        mock_ex = MagicMock()
        mock_ex.fetch_ohlcv.return_value = raw
        fetcher = HistoricalDataFetcher(exchange=mock_ex, sleep_seconds=0)
        result = fetcher.fetch("BTC/USDT:USDT", "5m", 1000, 2000)
        assert len(result) == 1
        assert result[0].volume == 20.0

    def test_pagination_stops_on_short_batch(self) -> None:
        """A batch shorter than 1 000 means no more data — stop paginating."""
        raw = [[i * 100, 1.0, 2.0, 0.5, 1.5, float(i)] for i in range(1, 5)]
        mock_ex = MagicMock()
        mock_ex.fetch_ohlcv.return_value = raw
        fetcher = HistoricalDataFetcher(exchange=mock_ex, sleep_seconds=0)
        result = fetcher.fetch("BTC/USDT:USDT", "5m", 0, 100_000)
        # Only one call because batch < 1000
        mock_ex.fetch_ohlcv.assert_called_once()
        assert len(result) == 4

    def test_default_exchange_is_binance(self) -> None:
        """When no exchange is provided, a binance ccxt instance is created."""
        import ccxt
        fetcher = HistoricalDataFetcher(sleep_seconds=0)
        assert isinstance(fetcher._exchange, ccxt.binance)


# ── SimulatedTrade dataclass tests ────────────────────────────────────────────


class TestSimulatedTrade:
    def _make(self, reason: str = "TP1", pnl: float = 2.5) -> SimulatedTrade:
        return SimulatedTrade(
            signal_id="SIG-001",
            symbol="ETH",
            side=Side.LONG,
            confidence="High",
            entry_price=100.0,
            stop_loss=98.0,
            tp1=103.0,
            tp2=105.0,
            tp3=108.0,
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            close_reason=reason,
            pnl_pct=pnl,
            be_triggered=False,
            max_favorable_excursion=3.0,
            max_adverse_excursion=0.5,
            bars_held=10,
        )

    def test_fields_stored_correctly(self) -> None:
        t = self._make()
        assert t.symbol == "ETH"
        assert t.side == Side.LONG
        assert t.close_reason == "TP1"
        assert t.pnl_pct == 2.5

    def test_short_trade_fields(self) -> None:
        t = SimulatedTrade(
            signal_id="SIG-002",
            symbol="BTC",
            side=Side.SHORT,
            confidence="Medium",
            entry_price=200.0,
            stop_loss=202.0,
            tp1=197.0,
            tp2=195.0,
            tp3=192.0,
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            close_reason="SL",
            pnl_pct=-1.0,
            be_triggered=False,
            max_favorable_excursion=0.5,
            max_adverse_excursion=1.0,
            bars_held=5,
        )
        assert t.side == Side.SHORT
        assert t.close_reason == "SL"
        assert t.pnl_pct == -1.0


# ── _calc_pnl tests ───────────────────────────────────────────────────────────


class TestCalcPnl:
    def test_long_profit(self) -> None:
        pnl = _calc_pnl(100.0, 105.0, Side.LONG)
        assert abs(pnl - 5.0) < 1e-9

    def test_long_loss(self) -> None:
        pnl = _calc_pnl(100.0, 98.0, Side.LONG)
        assert abs(pnl - (-2.0)) < 1e-9

    def test_short_profit(self) -> None:
        pnl = _calc_pnl(100.0, 95.0, Side.SHORT)
        assert abs(pnl - 5.0) < 1e-9

    def test_short_loss(self) -> None:
        pnl = _calc_pnl(100.0, 103.0, Side.SHORT)
        assert abs(pnl - (-3.0)) < 1e-9

    def test_zero_entry_returns_zero(self) -> None:
        assert _calc_pnl(0.0, 100.0, Side.LONG) == 0.0


# ── _advance_trade tests ──────────────────────────────────────────────────────


class TestAdvanceTrade:
    def test_sl_hit_long(self) -> None:
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0)
        # Candle wicks below SL
        candle = CandleData(open=100.0, high=101.0, low=97.5, close=99.5, volume=100.0)
        result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert result is not None
        assert result.close_reason == "SL"
        assert result.pnl_pct < 0

    def test_tp1_hit_long(self) -> None:
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0, tp1=103.0)
        # Candle reaches TP1 but not TP2/TP3, and does NOT touch SL
        candle = CandleData(open=100.0, high=104.0, low=99.5, close=103.5, volume=100.0)
        result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert result is not None
        assert result.close_reason == "TP1"
        assert result.pnl_pct > 0

    def test_sl_wins_over_tp_same_candle(self) -> None:
        """Conservative: SL wins when both SL and TP are touched on same candle."""
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0, tp1=103.0)
        # Both SL and TP1 are touched
        candle = CandleData(open=100.0, high=104.0, low=97.0, close=100.0, volume=100.0)
        result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert result is not None
        assert result.close_reason == "SL"

    def test_tp3_hit_short(self) -> None:
        trade = _make_open_trade(
            side=Side.SHORT, entry=100.0, stop_loss=102.0,
            tp1=97.0, tp2=95.0, tp3=92.0,
        )
        candle = CandleData(open=100.0, high=100.5, low=91.0, close=93.0, volume=100.0)
        result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert result is not None
        assert result.close_reason == "TP3"

    def test_be_trigger_sets_flag(self) -> None:
        """Price touching 50% of TP1 distance should set be_triggered without closing."""
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0, tp1=104.0)
        # 50% of TP1 distance = entry + 0.5 × (104 - 100) = 102
        candle = CandleData(open=100.0, high=102.5, low=99.0, close=102.0, volume=100.0)
        result = _advance_trade(trade, candle, 0.5, DEFAULT_STALE_HOURS)
        assert result is None  # trade still open
        assert trade.be_triggered is True

    def test_stale_close(self) -> None:
        """Trade open longer than stale_bars should be force-closed as STALE."""
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0)
        stale_hours = 0.1  # tiny window → stale after 1.2 bars
        candle = CandleData(open=100.0, high=100.5, low=99.8, close=100.2, volume=100.0)
        # Advance enough bars to trigger stale
        result = None
        for _ in range(5):
            result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, stale_hours)
            if result is not None:
                break
        assert result is not None
        assert result.close_reason == "STALE"

    def test_excursion_tracking(self) -> None:
        """max_fav and max_adv are updated correctly."""
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=90.0, tp1=120.0)
        candle = CandleData(open=100.0, high=105.0, low=98.0, close=103.0, volume=100.0)
        _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert trade.max_fav > 0
        assert trade.max_adv > 0

    def test_be_triggered_sl_closes_at_entry(self) -> None:
        """After BE is triggered, hitting SL should close at entry (0 % PnL)."""
        trade = _make_open_trade(side=Side.LONG, entry=100.0, stop_loss=98.0, tp1=104.0)
        trade.be_triggered = True
        # SL is hit
        candle = CandleData(open=100.0, high=100.5, low=97.0, close=99.0, volume=100.0)
        result = _advance_trade(trade, candle, DEFAULT_BE_TRIGGER_FRACTION, DEFAULT_STALE_HOURS)
        assert result is not None
        assert result.close_reason == "BE"
        assert abs(result.pnl_pct) < 1e-6


# ── _max_consecutive tests ────────────────────────────────────────────────────


class TestMaxConsecutive:
    def test_all_wins(self) -> None:
        assert _max_consecutive([True, True, True], True) == 3

    def test_alternating(self) -> None:
        assert _max_consecutive([True, False, True, False], True) == 1

    def test_run_of_three_losses(self) -> None:
        assert _max_consecutive([True, False, False, False, True], False) == 3

    def test_empty(self) -> None:
        assert _max_consecutive([], True) == 0


# ── BacktestResult tests ──────────────────────────────────────────────────────


class TestBacktestResult:
    def _result_with_trades(self, trades: list[SimulatedTrade]) -> BacktestResult:
        equity = [DEFAULT_INITIAL_CAPITAL + i * 10 for i in range(len(trades) + 1)]
        return _build_result(
            symbol="BTC",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 4, 1, tzinfo=timezone.utc),
            trades=trades,
            equity_curve=equity,
            initial_capital=DEFAULT_INITIAL_CAPITAL,
        )

    def _make_trade(self, reason: str, pnl: float) -> SimulatedTrade:
        return SimulatedTrade(
            signal_id="SIG-X",
            symbol="BTC",
            side=Side.LONG,
            confidence="High",
            entry_price=100.0,
            stop_loss=98.0,
            tp1=103.0,
            tp2=105.0,
            tp3=108.0,
            opened_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 16, tzinfo=timezone.utc),
            close_reason=reason,
            pnl_pct=pnl,
            be_triggered=False,
            max_favorable_excursion=2.0,
            max_adverse_excursion=0.5,
            bars_held=12,
        )

    def test_no_trades(self) -> None:
        r = self._result_with_trades([])
        assert r.total_trades == 0
        assert r.win_rate == 0.0
        assert r.profit_factor == 0.0

    def test_win_rate_calculation(self) -> None:
        trades = [
            self._make_trade("TP1", 3.0),
            self._make_trade("TP1", 2.5),
            self._make_trade("SL", -2.0),
            self._make_trade("SL", -1.5),
        ]
        r = self._result_with_trades(trades)
        assert r.total_trades == 4
        assert r.wins == 2
        assert r.losses == 2
        assert abs(r.win_rate - 0.5) < 1e-9

    def test_profit_factor(self) -> None:
        trades = [
            self._make_trade("TP2", 5.0),
            self._make_trade("SL", -2.0),
        ]
        r = self._result_with_trades(trades)
        # PF = 5.0 / 2.0 = 2.5
        assert abs(r.profit_factor - 2.5) < 1e-6

    def test_max_drawdown(self) -> None:
        # Equity goes up then drops
        equity = [10_000, 11_000, 12_000, 10_000, 9_000, 10_500]
        trades = [self._make_trade("TP1", 1.0) for _ in range(5)]
        r = _build_result(
            symbol="BTC",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 4, 1, tzinfo=timezone.utc),
            trades=trades,
            equity_curve=equity,
            initial_capital=10_000,
        )
        # Peak = 12 000, trough = 9 000 → DD = 25 %
        assert r.max_drawdown_pct > 0

    def test_summary_contains_symbol(self) -> None:
        r = self._result_with_trades([])
        assert "BTC" in r.summary()

    def test_print_report_runs(self, capsys) -> None:
        trades = [self._make_trade("TP1", 3.0), self._make_trade("SL", -1.5)]
        r = self._result_with_trades(trades)
        r.print_report()
        captured = capsys.readouterr()
        assert "360 Eye Backtesting Report" in captured.out
        assert "Go-live checks" in captured.out

    def test_to_csv_creates_file(self, tmp_path) -> None:
        trades = [self._make_trade("TP1", 3.0)]
        r = self._result_with_trades(trades)
        csv_path = str(tmp_path / "test.csv")
        r.to_csv(csv_path)
        import csv as csv_mod
        with open(csv_path, newline="") as fh:
            rows = list(csv_mod.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["close_reason"] == "TP1"

    def test_to_csv_no_trades_no_error(self, tmp_path) -> None:
        r = self._result_with_trades([])
        csv_path = str(tmp_path / "empty.csv")
        r.to_csv(csv_path)  # Should not raise; file may not be created

    def test_long_short_breakdown(self) -> None:
        long_win = SimulatedTrade(
            signal_id="1", symbol="BTC", side=Side.LONG, confidence="High",
            entry_price=100.0, stop_loss=98.0, tp1=103.0, tp2=105.0, tp3=108.0,
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            close_reason="TP1", pnl_pct=3.0, be_triggered=False,
            max_favorable_excursion=3.0, max_adverse_excursion=0.5, bars_held=10,
        )
        short_loss = SimulatedTrade(
            signal_id="2", symbol="BTC", side=Side.SHORT, confidence="Medium",
            entry_price=100.0, stop_loss=102.0, tp1=97.0, tp2=95.0, tp3=92.0,
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            close_reason="SL", pnl_pct=-2.0, be_triggered=False,
            max_favorable_excursion=0.5, max_adverse_excursion=2.0, bars_held=6,
        )
        r = self._result_with_trades([long_win, short_loss])
        assert r.long_trades == 1
        assert r.short_trades == 1
        assert r.long_win_rate == 1.0
        assert r.short_win_rate == 0.0

    def test_consecutive_wins_losses(self) -> None:
        trades = [
            self._make_trade("TP1", 2.0),
            self._make_trade("TP1", 2.0),
            self._make_trade("TP1", 2.0),
            self._make_trade("SL", -1.5),
            self._make_trade("SL", -1.5),
        ]
        r = self._result_with_trades(trades)
        assert r.max_consecutive_wins == 3
        assert r.max_consecutive_losses == 2


# ── Backtester class tests ────────────────────────────────────────────────────


class TestBacktester:
    def _minimal_candles(self, n: int, price: float = 100.0) -> list[CandleData]:
        return _flat_candles(n, price)

    def test_returns_backtest_result(self) -> None:
        """Backtester.run() always returns a BacktestResult, even with no signals."""
        bt = Backtester(
            symbol="BTC/USDT:USDT",
            five_min_candles=self._minimal_candles(100),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
        )
        result = bt.run()
        assert isinstance(result, BacktestResult)

    def test_equity_curve_starts_at_initial_capital(self) -> None:
        bt = Backtester(
            symbol="BTC/USDT:USDT",
            five_min_candles=self._minimal_candles(100),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
            initial_capital=5_000.0,
        )
        result = bt.run()
        assert result.equity_curve[0] == pytest.approx(5_000.0)
        assert result.initial_capital == 5_000.0

    def test_no_trades_no_equity_change(self) -> None:
        """Flat candles should produce zero trades and unchanged equity."""
        bt = Backtester(
            symbol="BTC/USDT:USDT",
            five_min_candles=self._minimal_candles(100),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
        )
        result = bt.run()
        assert result.total_trades == 0
        assert result.final_equity == pytest.approx(DEFAULT_INITIAL_CAPITAL)

    def test_insufficient_candles_returns_empty_result(self) -> None:
        """With fewer candles than the window size, no trades should be taken."""
        bt = Backtester(
            symbol="ETH/USDT:USDT",
            five_min_candles=self._minimal_candles(10),
            four_hour_candles=self._minimal_candles(5),
            daily_candles=self._minimal_candles(5),
        )
        result = bt.run()
        assert result.total_trades == 0

    def test_custom_parameters_accepted(self) -> None:
        bt = Backtester(
            symbol="ETH/USDT:USDT",
            five_min_candles=self._minimal_candles(100),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
            be_trigger_fraction=0.3,
            stale_hours=2.0,
            tp1_rr=2.0,
            tp2_rr=3.0,
            tp3_rr=5.0,
            initial_capital=20_000.0,
            risk_per_trade=0.02,
            check_fvg=True,
            check_order_block=True,
        )
        result = bt.run()
        assert isinstance(result, BacktestResult)
        assert result.initial_capital == 20_000.0

    def test_base_symbol_extraction(self) -> None:
        bt = Backtester(
            symbol="SOL/USDT:USDT",
            five_min_candles=self._minimal_candles(60),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
        )
        assert bt._base == "SOL"

    def test_base_symbol_no_slash(self) -> None:
        bt = Backtester(
            symbol="SOL",
            five_min_candles=self._minimal_candles(60),
            four_hour_candles=self._minimal_candles(20),
            daily_candles=self._minimal_candles(30),
        )
        assert bt._base == "SOL"

    def test_range_derived_from_4h_candles(self) -> None:
        """run() must pass range_low/range_high from 4H candles, not 5m candles."""
        # 5m candles are tightly clustered around 100; 4H candles span 50–200.
        five_min = _flat_candles(100, price=100.0)
        four_hour = [
            CandleData(open=100.0, high=200.0, low=50.0, close=125.0, volume=1000.0)
            for _ in range(20)
        ]
        daily = _flat_candles(30, price=100.0)

        captured_calls: list[dict] = []

        def _mock_check(**kwargs):  # type: ignore[override]
            captured_calls.append(kwargs)
            return None

        with patch("bot.backtester.run_confluence_check", side_effect=_mock_check):
            bt = Backtester(
                symbol="BTC/USDT:USDT",
                five_min_candles=five_min,
                four_hour_candles=four_hour,
                daily_candles=daily,
            )
            bt.run()

        assert captured_calls, "run_confluence_check was never called"
        call = captured_calls[0]
        # Range must come from 4H candles (low=50, high=200), not 5m (≈99.99–100.01)
        assert call["range_low"] == pytest.approx(50.0)
        assert call["range_high"] == pytest.approx(200.0)


# ── _build_result tests ───────────────────────────────────────────────────────


class TestBuildResult:
    def test_empty_trades(self) -> None:
        r = _build_result(
            symbol="BTC",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 4, 1, tzinfo=timezone.utc),
            trades=[],
            equity_curve=[10_000.0],
            initial_capital=10_000.0,
        )
        assert r.total_trades == 0
        assert r.final_equity == pytest.approx(10_000.0)
        assert r.max_drawdown_pct == 0.0

    def test_sharpe_requires_variance(self) -> None:
        """Single trade → stdev is undefined → Sharpe should be 0."""
        trade = SimulatedTrade(
            signal_id="S1", symbol="BTC", side=Side.LONG, confidence="High",
            entry_price=100.0, stop_loss=98.0, tp1=103.0, tp2=105.0, tp3=108.0,
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            close_reason="TP1", pnl_pct=3.0, be_triggered=False,
            max_favorable_excursion=3.0, max_adverse_excursion=0.5, bars_held=10,
        )
        r = _build_result(
            symbol="BTC",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 4, 1, tzinfo=timezone.utc),
            trades=[trade],
            equity_curve=[10_000.0, 10_300.0],
            initial_capital=10_000.0,
        )
        assert r.sharpe_ratio == 0.0

    def test_monthly_returns_aggregated(self) -> None:
        def _t(month: int, pnl: float) -> SimulatedTrade:
            return SimulatedTrade(
                signal_id="X", symbol="BTC", side=Side.LONG, confidence="High",
                entry_price=100.0, stop_loss=98.0, tp1=103.0, tp2=105.0, tp3=108.0,
                opened_at=datetime(2024, month, 15, tzinfo=timezone.utc),
                closed_at=datetime(2024, month, 16, tzinfo=timezone.utc),
                close_reason="TP1", pnl_pct=pnl, be_triggered=False,
                max_favorable_excursion=2.0, max_adverse_excursion=0.5, bars_held=5,
            )

        trades = [_t(1, 2.0), _t(1, 1.5), _t(2, 3.0)]
        r = _build_result(
            symbol="BTC",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 3, 1, tzinfo=timezone.utc),
            trades=trades,
            equity_curve=[10_000.0 + i * 50 for i in range(4)],
            initial_capital=10_000.0,
        )
        assert abs(r.monthly_returns["2024-01"] - 3.5) < 1e-9
        assert abs(r.monthly_returns["2024-02"] - 3.0) < 1e-9
