"""
Backtester — 360 Crypto Eye Scalping Backtesting Framework
===========================================================
Replays historical candle data through the existing 7-gate confluence engine
(``bot/signal_engine.py``) and simulates the full signal lifecycle, producing
institutional-grade performance reports.

Design principles
-----------------
- Zero divergence: calls the *real* ``run_confluence_check()`` from
  ``bot/signal_engine.py`` with no modifications.
- Conservative simulation: when SL and TP are both touched on the same candle,
  the SL (worst-case) wins.
- Sliding windows: same sizes as the live engine (50 × 5m, 15 × 4H, 25 × 1D).
- Compounding capital: risk % is applied to *current* equity, not initial.
- Rate limiting: small sleep between Binance pagination requests.
"""

from __future__ import annotations

import csv
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import ccxt

from bot.signal_engine import (
    CandleData,
    Side,
    run_confluence_check,
)

# ── Constants ─────────────────────────────────────────────────────────────────

# Window sizes that match the live engine's candle requirements
_5M_WINDOW = 50
_4H_WINDOW = 15
_1D_WINDOW = 25

# Minimum candles needed in each timeframe to run the engine
_MIN_5M = 50
_MIN_4H = 15
_MIN_1D = 25

# Default backtest parameters
DEFAULT_BE_TRIGGER_FRACTION: float = 0.50
DEFAULT_STALE_HOURS: float = 4.0
DEFAULT_TP1_RR: float = 1.5
DEFAULT_TP2_RR: float = 2.5
DEFAULT_TP3_RR: float = 4.0
DEFAULT_INITIAL_CAPITAL: float = 10_000.0
DEFAULT_RISK_PER_TRADE: float = 0.01  # 1 % of equity

# Duration of one 5m bar in seconds (used to convert bar indices to datetimes)
_5M_SECONDS: int = 300

# Synthetic epoch for bar-index-to-datetime conversion
_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _bar_to_dt(bar_idx: int) -> datetime:
    """Convert a bar index (0-based 5m candle position) to a UTC datetime."""
    return _EPOCH + timedelta(seconds=bar_idx * _5M_SECONDS)


def _htf_window_tail(bar_5m_idx: int, bars_per_htf_candle: int, total_htf: int) -> int:
    """
    Return the tail index into a higher-timeframe candle array that
    approximately corresponds to *bar_5m_idx* in the 5m array.

    Parameters
    ----------
    bar_5m_idx:
        Current position in the 5m array.
    bars_per_htf_candle:
        Number of 5m bars equivalent to one HTF candle (e.g. 48 for 4H).
    total_htf:
        Length of the HTF candle array (upper bound).
    """
    tail = bar_5m_idx // bars_per_htf_candle
    return min(tail, total_htf)


# ── Historical Data Fetcher ───────────────────────────────────────────────────


class HistoricalDataFetcher:
    """
    Paginate through Binance OHLCV history via CCXT.

    Binance caps responses at 1 000 candles per request; this class
    accumulates pages until the full ``start``–``end`` window is covered.

    Parameters
    ----------
    exchange:
        Optional pre-built ``ccxt.Exchange`` instance (useful for tests).
        When ``None`` a Binance Futures exchange is created automatically.
    sleep_seconds:
        Pause between pagination requests to respect rate limits.
    """

    def __init__(
        self,
        exchange: Optional[ccxt.Exchange] = None,
        sleep_seconds: float = 0.5,
    ) -> None:
        if exchange is None:
            self._exchange: ccxt.Exchange = ccxt.binance(
                {"options": {"defaultType": "future"}}
            )
        else:
            self._exchange = exchange
        self._sleep = sleep_seconds

    # ------------------------------------------------------------------
    def fetch(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> list[CandleData]:
        """
        Fetch all candles for *symbol* / *timeframe* in [since_ms, until_ms].

        Parameters
        ----------
        symbol:
            CCXT symbol, e.g. ``"BTC/USDT:USDT"``.
        timeframe:
            CCXT timeframe string, e.g. ``"5m"``, ``"4h"``, ``"1d"``.
        since_ms:
            Start of the window as a Unix millisecond timestamp.
        until_ms:
            End of the window as a Unix millisecond timestamp (exclusive).

        Returns
        -------
        list[CandleData]
            Candles sorted oldest-first.
        """
        candles: list[CandleData] = []
        cursor = since_ms

        while cursor < until_ms:
            batch = self._exchange.fetch_ohlcv(
                symbol, timeframe, since=cursor, limit=1000
            )
            if not batch:
                break
            for row in batch:
                ts = row[0]
                if ts >= until_ms:
                    break
                if ts >= since_ms:
                    candles.append(
                        CandleData(
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                        )
                    )
            last_ts = batch[-1][0]
            if last_ts <= cursor:
                break  # guard against infinite loops
            cursor = last_ts + 1
            if len(batch) < 1000:
                break  # no more data
            time.sleep(self._sleep)

        return candles


# ── SimulatedTrade dataclass ──────────────────────────────────────────────────


@dataclass
class SimulatedTrade:
    """
    A single simulated trade produced by the backtester.

    Attributes
    ----------
    signal_id:
        Identifier from the underlying ``SignalResult``.
    symbol:
        Trading pair base symbol, e.g. ``"BTC"``.
    side:
        ``Side.LONG`` or ``Side.SHORT``.
    confidence:
        Confidence level from the confluence engine.
    entry_price:
        Mid-point of the entry zone at signal time.
    stop_loss:
        Structural stop-loss price.
    tp1, tp2, tp3:
        Take-profit levels (R:R multiples of risk).
    opened_at:
        UTC timestamp when the signal was confirmed (5m bar close).
    closed_at:
        UTC timestamp when the trade was resolved.
    close_reason:
        One of ``"TP1"``, ``"TP2"``, ``"TP3"``, ``"SL"``, ``"BE"``, ``"STALE"``.
    pnl_pct:
        Percentage profit/loss vs entry price (signed, e.g. +2.5 or -1.0).
    be_triggered:
        Whether the break-even level was reached before close.
    max_favorable_excursion:
        Maximum favourable price move (% from entry) during the trade.
    max_adverse_excursion:
        Maximum adverse price move (% from entry) during the trade.
    bars_held:
        Number of 5m bars the trade was open.
    """

    signal_id: str
    symbol: str
    side: Side
    confidence: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: datetime
    closed_at: datetime
    close_reason: str  # "TP1" | "TP2" | "TP3" | "SL" | "BE" | "STALE"
    pnl_pct: float
    be_triggered: bool
    max_favorable_excursion: float
    max_adverse_excursion: float
    bars_held: int


# ── BacktestResult dataclass ──────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """
    Aggregated performance metrics for a completed backtest run.

    Attributes
    ----------
    symbol:
        Symbol that was backtested.
    start:
        Start of the backtest window (UTC).
    end:
        End of the backtest window (UTC).
    total_trades:
        Total number of closed trades.
    wins:
        Trades that hit TP1, TP2, or TP3.
    losses:
        Trades that hit SL.
    break_evens:
        Trades closed at break-even.
    stale_closes:
        Trades closed as stale (no activity for *stale_hours*).
    win_rate:
        Fraction of wins (wins / total_trades), or 0.0 if no trades.
    profit_factor:
        Gross profit / gross loss, or 0.0 if no losing trades.
    sharpe_ratio:
        Risk-adjusted return (mean / stdev of per-trade PnL × √252),
        or 0.0 if insufficient data.
    max_drawdown_pct:
        Largest peak-to-trough equity decline as a percentage.
    max_drawdown_duration:
        Number of trades spent in drawdown during the worst drawdown.
    calmar_ratio:
        Annualised return / max_drawdown_pct, or 0.0.
    avg_win_pct:
        Average PnL percentage of winning trades.
    avg_loss_pct:
        Average PnL percentage of losing trades (negative).
    largest_win_pct:
        Largest single winning trade (%).
    largest_loss_pct:
        Largest single losing trade (%).
    avg_holding_time:
        Average number of 5m bars held per trade.
    max_consecutive_wins:
        Longest consecutive winning streak.
    max_consecutive_losses:
        Longest consecutive losing streak.
    equity_curve:
        List of equity values after each trade.
    monthly_returns:
        Dict mapping ``"YYYY-MM"`` → cumulative PnL % for that month.
    long_trades:
        Number of LONG trades taken.
    short_trades:
        Number of SHORT trades taken.
    long_win_rate:
        Win rate for LONG trades.
    short_win_rate:
        Win rate for SHORT trades.
    trades:
        The raw list of :class:`SimulatedTrade` objects.
    initial_capital:
        Starting equity used for this run.
    final_equity:
        Ending equity after all trades.
    """

    symbol: str
    start: datetime
    end: datetime
    total_trades: int
    wins: int
    losses: int
    break_evens: int
    stale_closes: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration: int
    calmar_ratio: float
    avg_win_pct: float
    avg_loss_pct: float
    largest_win_pct: float
    largest_loss_pct: float
    avg_holding_time: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    equity_curve: list[float] = field(default_factory=list)
    monthly_returns: dict[str, float] = field(default_factory=dict)
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    trades: list[SimulatedTrade] = field(default_factory=list)
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    final_equity: float = DEFAULT_INITIAL_CAPITAL

    # ── Go-live thresholds (§11) ──────────────────────────────────────
    _GOLIVE_MIN_TRADES = 30
    _GOLIVE_MIN_WIN_RATE = 0.50
    _GOLIVE_MIN_PROFIT_FACTOR = 1.5
    _GOLIVE_MAX_DRAWDOWN = 20.0
    _GOLIVE_MIN_SHARPE = 1.0

    def summary(self) -> str:
        """Return a one-line text summary of key metrics."""
        return (
            f"{self.symbol} | {self.total_trades} trades | "
            f"WR={self.win_rate:.1%} | PF={self.profit_factor:.2f} | "
            f"Sharpe={self.sharpe_ratio:.2f} | MaxDD={self.max_drawdown_pct:.1f}% | "
            f"Equity={self.final_equity:,.2f}"
        )

    def print_report(self) -> None:
        """Print a formatted performance report to stdout."""
        divider = "─" * 60
        print(divider)
        print(f"  360 Eye Backtesting Report — {self.symbol}")
        print(divider)
        print(f"  Period          : {self.start.date()} → {self.end.date()}")
        print(f"  Initial capital : {self.initial_capital:>12,.2f} USDT")
        print(f"  Final equity    : {self.final_equity:>12,.2f} USDT")
        print(divider)
        print(f"  Total trades    : {self.total_trades}")
        print(f"    Wins          : {self.wins}")
        print(f"    Losses        : {self.losses}")
        print(f"    Break-evens   : {self.break_evens}")
        print(f"    Stale closes  : {self.stale_closes}")
        print(f"  Win rate        : {self.win_rate:.1%}")
        print(f"  Profit factor   : {self.profit_factor:.2f}")
        print(f"  Sharpe ratio    : {self.sharpe_ratio:.2f}")
        print(f"  Max drawdown    : {self.max_drawdown_pct:.1f}%")
        print(f"  Calmar ratio    : {self.calmar_ratio:.2f}")
        print(divider)
        print(f"  Avg win         : {self.avg_win_pct:+.2f}%")
        print(f"  Avg loss        : {self.avg_loss_pct:+.2f}%")
        print(f"  Largest win     : {self.largest_win_pct:+.2f}%")
        print(f"  Largest loss    : {self.largest_loss_pct:+.2f}%")
        print(f"  Avg bars held   : {self.avg_holding_time:.1f}")
        print(f"  Max consec. W   : {self.max_consecutive_wins}")
        print(f"  Max consec. L   : {self.max_consecutive_losses}")
        print(divider)
        print(f"  LONG  trades    : {self.long_trades}  (WR={self.long_win_rate:.1%})")
        print(f"  SHORT trades    : {self.short_trades}  (WR={self.short_win_rate:.1%})")
        print(divider)
        # Go-live threshold indicators
        checks = [
            ("Trades ≥ 30", self.total_trades >= self._GOLIVE_MIN_TRADES),
            ("Win rate ≥ 50%", self.win_rate >= self._GOLIVE_MIN_WIN_RATE),
            ("Profit factor ≥ 1.5", self.profit_factor >= self._GOLIVE_MIN_PROFIT_FACTOR),
            ("Max DD ≤ 20%", self.max_drawdown_pct <= self._GOLIVE_MAX_DRAWDOWN),
            ("Sharpe ≥ 1.0", self.sharpe_ratio >= self._GOLIVE_MIN_SHARPE),
        ]
        print("  Go-live checks:")
        for name, passed in checks:
            icon = "✅" if passed else "❌"
            print(f"    {icon} {name}")
        all_pass = all(v for _, v in checks)
        verdict = "✅ READY FOR LIVE DEPLOYMENT" if all_pass else "❌ NOT READY — review metrics"
        print(f"\n  Verdict: {verdict}")
        print(divider)

    def to_csv(self, filepath: str) -> None:
        """
        Export all trades to a CSV file at *filepath*.

        Parameters
        ----------
        filepath:
            Destination path, e.g. ``"backtest_results.csv"``.
        """
        if not self.trades:
            return
        fieldnames = [
            "signal_id", "symbol", "side", "confidence",
            "entry_price", "stop_loss", "tp1", "tp2", "tp3",
            "opened_at", "closed_at", "close_reason", "pnl_pct",
            "be_triggered", "max_favorable_excursion", "max_adverse_excursion",
            "bars_held",
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for t in self.trades:
                writer.writerow({
                    "signal_id": t.signal_id,
                    "symbol": t.symbol,
                    "side": t.side.value,
                    "confidence": t.confidence,
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "tp1": t.tp1,
                    "tp2": t.tp2,
                    "tp3": t.tp3,
                    "opened_at": t.opened_at.isoformat(),
                    "closed_at": t.closed_at.isoformat(),
                    "close_reason": t.close_reason,
                    "pnl_pct": t.pnl_pct,
                    "be_triggered": t.be_triggered,
                    "max_favorable_excursion": t.max_favorable_excursion,
                    "max_adverse_excursion": t.max_adverse_excursion,
                    "bars_held": t.bars_held,
                })


# ── Backtester class ──────────────────────────────────────────────────────────


class Backtester:
    """
    Walk-forward backtester for the 360 Eye confluence engine.

    The backtester steps through every 5m candle in the historical data,
    maintaining rolling windows for each timeframe.  On every step it calls
    the *real* ``run_confluence_check()`` from ``bot/signal_engine.py`` for
    both LONG and SHORT sides.  When a signal is generated it tracks the
    simulated trade until one of the exit conditions is met.

    Exit priority (conservative simulation)
    ----------------------------------------
    1. Stop-loss (worst-case — if SL and TP are both touched on the same
       candle the SL wins).
    2. TP3 → TP2 → TP1 (checked after SL is clear).
    3. Break-even trigger (price covers *be_trigger_fraction* of TP1
       distance → SL is moved to entry).
    4. Stale close (trade open for longer than *stale_hours*).

    Parameters
    ----------
    symbol:
        CCXT symbol string, e.g. ``"BTC/USDT:USDT"``.
    five_min_candles:
        All 5m candles for the backtest period.
    four_hour_candles:
        All 4H candles for the backtest period.
    daily_candles:
        All 1D candles for the backtest period.
    be_trigger_fraction:
        Fraction of the TP1 distance that triggers BE (default 0.5).
    stale_hours:
        Hours without exit before a trade is force-closed as stale.
    tp1_rr / tp2_rr / tp3_rr:
        Risk-reward ratios passed to the confluence engine.
    initial_capital:
        Starting equity in USDT.
    risk_per_trade:
        Fraction of current equity risked per trade (default 0.01 = 1 %).
    check_fvg:
        Whether to enable the optional FVG gate (Gate ⑥).
    check_order_block:
        Whether to enable the optional Order Block gate (Gate ⑦).
    """

    def __init__(
        self,
        symbol: str,
        five_min_candles: list[CandleData],
        four_hour_candles: list[CandleData],
        daily_candles: list[CandleData],
        be_trigger_fraction: float = DEFAULT_BE_TRIGGER_FRACTION,
        stale_hours: float = DEFAULT_STALE_HOURS,
        tp1_rr: float = DEFAULT_TP1_RR,
        tp2_rr: float = DEFAULT_TP2_RR,
        tp3_rr: float = DEFAULT_TP3_RR,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
        check_fvg: bool = False,
        check_order_block: bool = False,
    ) -> None:
        self.symbol = symbol
        self._5m = five_min_candles
        self._4h = four_hour_candles
        self._1d = daily_candles
        self.be_trigger_fraction = be_trigger_fraction
        self.stale_hours = stale_hours
        self.tp1_rr = tp1_rr
        self.tp2_rr = tp2_rr
        self.tp3_rr = tp3_rr
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.check_fvg = check_fvg
        self.check_order_block = check_order_block

        # Derive base symbol (e.g. "BTC" from "BTC/USDT:USDT")
        self._base = symbol.split("/")[0] if "/" in symbol else symbol

    # ------------------------------------------------------------------
    def run(self) -> BacktestResult:
        """
        Execute the walk-forward backtest and return a :class:`BacktestResult`.

        Returns
        -------
        BacktestResult
            Populated with all metrics, equity curve, and raw trades.
        """
        trades: list[SimulatedTrade] = []
        equity = self.initial_capital
        equity_curve: list[float] = [equity]

        open_trade: Optional[_OpenTrade] = None

        n5m = len(self._5m)
        n4h = len(self._4h)
        n1d = len(self._1d)

        for idx in range(_MIN_5M, n5m):
            # ── Compute HTF window tails proportionally ──────────────
            # Map the current 5m position to the same relative position
            # in the independently-fetched 4H and 1D arrays.
            progress = idx / n5m
            i4h = min(int(progress * n4h), n4h)
            i1d = min(int(progress * n1d), n1d)

            # Build sliding windows
            win_5m = self._5m[max(0, idx - _5M_WINDOW): idx]
            win_4h = self._4h[max(0, i4h - _4H_WINDOW): i4h]
            win_1d = self._1d[max(0, i1d - _1D_WINDOW): i1d]

            if len(win_5m) < _MIN_5M or len(win_4h) < 2 or len(win_1d) < 20:
                continue

            current_candle = self._5m[idx]
            current_price = current_candle.close

            # ── Manage the open trade first ───────────────────────────
            if open_trade is not None:
                result = _advance_trade(
                    open_trade, current_candle, self.be_trigger_fraction, self.stale_hours
                )
                if result is not None:
                    pnl_fraction = result.pnl_pct / 100.0
                    risk_amount = equity * self.risk_per_trade
                    sl_dist = abs(open_trade.entry - open_trade.stop_loss)
                    if sl_dist > 0 and open_trade.entry > 0:
                        # Scale PnL by actual risk taken
                        pnl_usdt = risk_amount * (result.pnl_pct / (sl_dist / open_trade.entry * 100))
                    else:
                        pnl_usdt = risk_amount * pnl_fraction
                    equity += pnl_usdt
                    equity = max(equity, 0.0)
                    equity_curve.append(equity)
                    trades.append(result)
                    open_trade = None

            # ── Look for a new signal when no trade is open ──────────
            if open_trade is None:
                for side in (Side.LONG, Side.SHORT):
                    # Range from 4H candles — matches live _fetch_binance_candles()
                    if win_4h:
                        range_low = min(c.low for c in win_4h)
                        range_high = max(c.high for c in win_4h)
                    else:
                        range_low = min(c.low for c in win_5m)
                        range_high = max(c.high for c in win_5m)
                    # key_level from last 10 5m candles — matches live bot
                    recent_5m = win_5m[-10:]
                    if side == Side.LONG:
                        key_level = min(c.low for c in recent_5m)
                    else:
                        key_level = max(c.high for c in recent_5m)

                    atr_proxy = (range_high - range_low) * 0.01
                    stop_loss = (
                        key_level - atr_proxy if side == Side.LONG else key_level + atr_proxy
                    )

                    signal = run_confluence_check(
                        symbol=self._base,
                        current_price=current_price,
                        side=side,
                        range_low=range_low,
                        range_high=range_high,
                        key_liquidity_level=key_level,
                        five_min_candles=win_5m,
                        daily_candles=win_1d,
                        four_hour_candles=win_4h,
                        news_in_window=False,  # no live news in backtest
                        stop_loss=stop_loss,
                        tp1_rr=self.tp1_rr,
                        tp2_rr=self.tp2_rr,
                        tp3_rr=self.tp3_rr,
                        check_fvg=self.check_fvg,
                        check_order_block=self.check_order_block,
                    )

                    if signal is not None:
                        entry_price = (signal.entry_low + signal.entry_high) / 2
                        opened_at = _bar_to_dt(idx)
                        open_trade = _OpenTrade(
                            signal_id=signal.signal_id,
                            symbol=self._base,
                            side=side,
                            confidence=signal.confidence.value,
                            entry=entry_price,
                            stop_loss=signal.stop_loss,
                            tp1=signal.tp1,
                            tp2=signal.tp2,
                            tp3=signal.tp3,
                            opened_at=opened_at,
                            opened_at_bar=idx,
                            bars_held=0,
                            be_triggered=False,
                            max_fav=0.0,
                            max_adv=0.0,
                        )
                        break  # one trade at a time

        # ── Force-close any still-open trade as STALE at end of data ─
        if open_trade is not None:
            closed_at = _bar_to_dt(open_trade.opened_at_bar + open_trade.bars_held)
            trade = _close_trade(open_trade, closed_at, "STALE", 0.0)
            equity_curve.append(equity)
            trades.append(trade)

        start_dt = _bar_to_dt(0)
        end_dt = _bar_to_dt(n5m)

        return _build_result(
            symbol=self._base,
            start=start_dt,
            end=end_dt,
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=self.initial_capital,
        )


# ── Internal helpers ──────────────────────────────────────────────────────────


@dataclass
class _OpenTrade:
    """Mutable state for a trade in progress."""

    signal_id: str
    symbol: str
    side: Side
    confidence: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: datetime
    opened_at_bar: int  # 5m bar index when the trade was opened
    bars_held: int
    be_triggered: bool
    max_fav: float
    max_adv: float


def _advance_trade(
    trade: _OpenTrade,
    candle: CandleData,
    be_trigger_fraction: float,
    stale_hours: float,
) -> Optional[SimulatedTrade]:
    """
    Advance an open trade by one 5m candle.

    Returns a closed :class:`SimulatedTrade` when an exit condition is met,
    or ``None`` when the trade remains open.

    Exit priority
    -------------
    1. SL (worst-case — if SL and TP both touched same candle, SL wins).
    2. TP3 → TP2 → TP1.
    3. BE trigger → update ``trade.be_triggered``; continues as open trade.
    4. Stale close after *stale_hours* × 12 bars.
    """
    trade.bars_held += 1
    side = trade.side
    high = candle.high
    low = candle.low

    # ── Excursion tracking ────────────────────────────────────────────
    if side == Side.LONG:
        fav = (high - trade.entry) / trade.entry * 100
        adv = (trade.entry - low) / trade.entry * 100
    else:
        fav = (trade.entry - low) / trade.entry * 100
        adv = (high - trade.entry) / trade.entry * 100

    trade.max_fav = max(trade.max_fav, fav)
    trade.max_adv = max(trade.max_adv, adv)

    # ── SL check (worst-case) ─────────────────────────────────────────
    sl_hit = (side == Side.LONG and low <= trade.stop_loss) or (
        side == Side.SHORT and high >= trade.stop_loss
    )
    if sl_hit:
        # If BE was already triggered, SL is at entry → PnL ≈ 0
        sl_price = trade.entry if trade.be_triggered else trade.stop_loss
        pnl = _calc_pnl(trade.entry, sl_price, side)
        closed_at = _bar_to_dt(trade.opened_at_bar + trade.bars_held)
        return _close_trade(trade, closed_at, "BE" if trade.be_triggered else "SL", pnl)

    # ── TP checks ────────────────────────────────────────────────────
    for tp, label in ((trade.tp3, "TP3"), (trade.tp2, "TP2"), (trade.tp1, "TP1")):
        tp_hit = (side == Side.LONG and high >= tp) or (side == Side.SHORT and low <= tp)
        if tp_hit:
            pnl = _calc_pnl(trade.entry, tp, side)
            closed_at = _bar_to_dt(trade.opened_at_bar + trade.bars_held)
            return _close_trade(trade, closed_at, label, pnl)

    # ── BE trigger check ─────────────────────────────────────────────
    if not trade.be_triggered:
        dist_tp1 = abs(trade.tp1 - trade.entry)
        if dist_tp1 > 0:
            trigger = (
                trade.entry + be_trigger_fraction * dist_tp1
                if side == Side.LONG
                else trade.entry - be_trigger_fraction * dist_tp1
            )
            be_hit = (side == Side.LONG and high >= trigger) or (
                side == Side.SHORT and low <= trigger
            )
            if be_hit:
                trade.be_triggered = True

    # ── Stale check ──────────────────────────────────────────────────
    stale_bars = int(stale_hours * 12)  # 12 × 5m bars per hour
    if trade.bars_held >= stale_bars:
        close_price = candle.close
        pnl = _calc_pnl(trade.entry, close_price, side)
        closed_at = _bar_to_dt(trade.opened_at_bar + trade.bars_held)
        return _close_trade(trade, closed_at, "STALE", pnl)

    return None


def _calc_pnl(entry: float, exit_price: float, side: Side) -> float:
    """Return signed PnL percentage."""
    if entry == 0:
        return 0.0
    if side == Side.LONG:
        return (exit_price - entry) / entry * 100
    else:
        return (entry - exit_price) / entry * 100


def _close_trade(
    trade: _OpenTrade, closed_at: datetime, reason: str, pnl: float
) -> SimulatedTrade:
    """Convert an ``_OpenTrade`` into a closed ``SimulatedTrade``."""
    return SimulatedTrade(
        signal_id=trade.signal_id,
        symbol=trade.symbol,
        side=trade.side,
        confidence=trade.confidence,
        entry_price=trade.entry,
        stop_loss=trade.stop_loss,
        tp1=trade.tp1,
        tp2=trade.tp2,
        tp3=trade.tp3,
        opened_at=trade.opened_at,
        closed_at=closed_at,
        close_reason=reason,
        pnl_pct=round(pnl, 4),
        be_triggered=trade.be_triggered,
        max_favorable_excursion=round(trade.max_fav, 4),
        max_adverse_excursion=round(trade.max_adv, 4),
        bars_held=trade.bars_held,
    )


def _max_consecutive(sequence: list[bool], target: bool) -> int:
    """Return the maximum consecutive run of *target* in *sequence*."""
    best = 0
    current = 0
    for v in sequence:
        if v == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _build_result(
    symbol: str,
    start: datetime,
    end: datetime,
    trades: list[SimulatedTrade],
    equity_curve: list[float],
    initial_capital: float,
) -> BacktestResult:
    """Aggregate raw trades into a :class:`BacktestResult`."""
    total = len(trades)
    wins = sum(1 for t in trades if t.close_reason in ("TP1", "TP2", "TP3"))
    losses = sum(1 for t in trades if t.close_reason == "SL")
    bes = sum(1 for t in trades if t.close_reason == "BE")
    stales = sum(1 for t in trades if t.close_reason == "STALE")

    win_rate = wins / total if total > 0 else 0.0

    win_pnls = [t.pnl_pct for t in trades if t.close_reason in ("TP1", "TP2", "TP3")]
    loss_pnls = [t.pnl_pct for t in trades if t.close_reason == "SL"]

    gross_profit = sum(p for p in win_pnls if p > 0)
    gross_loss = abs(sum(p for p in loss_pnls if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    pnl_series = [t.pnl_pct for t in trades]
    if len(pnl_series) >= 2:
        try:
            mean_pnl = statistics.mean(pnl_series)
            stdev_pnl = statistics.stdev(pnl_series)
            sharpe = (mean_pnl / stdev_pnl) * math.sqrt(252) if stdev_pnl > 0 else 0.0
        except statistics.StatisticsError:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Max drawdown
    max_dd = 0.0
    max_dd_dur = 0
    peak = equity_curve[0] if equity_curve else initial_capital
    dd_start = 0
    for i, eq in enumerate(equity_curve):
        if eq > peak:
            peak = eq
            dd_start = i
        dd = (peak - eq) / peak * 100
        dur = i - dd_start
        if dd > max_dd:
            max_dd = dd
            max_dd_dur = dur

    final_equity = equity_curve[-1] if equity_curve else initial_capital
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100
    calmar = total_return_pct / max_dd if max_dd > 0 else 0.0

    avg_win = statistics.mean(win_pnls) if win_pnls else 0.0
    avg_loss = statistics.mean(loss_pnls) if loss_pnls else 0.0
    largest_win = max(win_pnls, default=0.0)
    largest_loss = min(loss_pnls, default=0.0)
    avg_bars = statistics.mean([t.bars_held for t in trades]) if trades else 0.0

    is_win = [t.close_reason in ("TP1", "TP2", "TP3") for t in trades]
    max_cons_wins = _max_consecutive(is_win, True)
    max_cons_losses = _max_consecutive(is_win, False)

    # Monthly returns (keyed by bar index placeholder)
    monthly: dict[str, float] = {}
    for t in trades:
        key = t.opened_at.strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0.0) + t.pnl_pct

    long_trades_list = [t for t in trades if t.side == Side.LONG]
    short_trades_list = [t for t in trades if t.side == Side.SHORT]
    long_wins = sum(1 for t in long_trades_list if t.close_reason in ("TP1", "TP2", "TP3"))
    short_wins = sum(1 for t in short_trades_list if t.close_reason in ("TP1", "TP2", "TP3"))

    return BacktestResult(
        symbol=symbol,
        start=start,
        end=end,
        total_trades=total,
        wins=wins,
        losses=losses,
        break_evens=bes,
        stale_closes=stales,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        max_drawdown_duration=max_dd_dur,
        calmar_ratio=calmar,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        largest_win_pct=largest_win,
        largest_loss_pct=largest_loss,
        avg_holding_time=avg_bars,
        max_consecutive_wins=max_cons_wins,
        max_consecutive_losses=max_cons_losses,
        equity_curve=equity_curve,
        monthly_returns=monthly,
        long_trades=len(long_trades_list),
        short_trades=len(short_trades_list),
        long_win_rate=long_wins / len(long_trades_list) if long_trades_list else 0.0,
        short_win_rate=short_wins / len(short_trades_list) if short_trades_list else 0.0,
        trades=trades,
        initial_capital=initial_capital,
        final_equity=final_equity,
    )
