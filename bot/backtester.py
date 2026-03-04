"""
bot/backtester.py — Core Backtesting Engine for 360 Crypto Eye Scalping
=========================================================================
Walk-forward backtester that replays historical candle data through the live
confluence engine (bot/signal_engine.py) and simulates the full signal
lifecycle: BE triggers, trailing SL, stale closes, and TP hits.

Design principles
-----------------
* Zero divergence: calls the exact same functions from bot/signal_engine.py.
* Conservative simulation: if SL and TP hit on same candle → SL wins.
* Sliding windows: feeds the engine the same window sizes the live bot sees.
* Compounding equity: each trade risks ``risk_per_trade`` of *current* equity.
"""

from __future__ import annotations

import bisect
import csv
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import ccxt

from bot.signal_engine import (
    CandleData,
    Side,
    run_confluence_check,
)


# ── Internal OHLCV row with timestamp ────────────────────────────────────────

@dataclass
class _OHLCVRow:
    """Internal candle representation that carries a Unix timestamp."""

    timestamp: float  # seconds since epoch
    candle: CandleData


# ── Historical Data Fetcher ───────────────────────────────────────────────────

class HistoricalDataFetcher:
    """Download historical candles from Binance Futures via CCXT."""

    _BINANCE_LIMIT = 1000   # max candles per API request
    _RATE_LIMIT_SLEEP = 0.5  # seconds between pagination requests

    def __init__(self) -> None:
        self._exchange = ccxt.binance({"options": {"defaultType": "future"}})

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> list[_OHLCVRow]:
        """
        Paginate through Binance API to fetch complete historical OHLCV data.

        Binance returns max 1000 candles per request.  This method loops with
        the ``since`` parameter advancing after each batch until ``end_date``.

        Parameters
        ----------
        symbol:
            CCXT Binance Futures symbol, e.g. ``"BTC/USDT:USDT"``.
        timeframe:
            Candle size string understood by CCXT, e.g. ``"5m"``, ``"4h"``,
            ``"1d"``.
        start_date / end_date:
            Inclusive date range in ``"YYYY-MM-DD"`` format (UTC).
        """
        start_ts_ms = int(
            datetime.strptime(start_date, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
            * 1000
        )
        end_ts_ms = int(
            datetime.strptime(end_date, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
            * 1000
        )

        rows: list[_OHLCVRow] = []
        since = start_ts_ms

        while since < end_ts_ms:
            batch = self._exchange.fetch_ohlcv(
                symbol, timeframe, since=since, limit=self._BINANCE_LIMIT
            )
            if not batch:
                break

            for raw in batch:
                if raw[0] > end_ts_ms:
                    break
                rows.append(
                    _OHLCVRow(
                        timestamp=raw[0] / 1000.0,
                        candle=CandleData(
                            open=float(raw[1]),
                            high=float(raw[2]),
                            low=float(raw[3]),
                            close=float(raw[4]),
                            volume=float(raw[5]),
                        ),
                    )
                )

            last_ts_ms = batch[-1][0]
            if last_ts_ms >= end_ts_ms or len(batch) < self._BINANCE_LIMIT:
                break
            since = last_ts_ms + 1
            time.sleep(self._RATE_LIMIT_SLEEP)

        return rows


# ── Simulated Trade ───────────────────────────────────────────────────────────

@dataclass
class SimulatedTrade:
    """Represents a single simulated trade produced by the backtester."""

    signal_id: str
    symbol: str
    side: str              # "LONG" / "SHORT"
    confidence: str
    entry_price: float     # midpoint of entry zone
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: float       # Unix timestamp (seconds)
    closed_at: Optional[float] = None
    close_reason: Optional[str] = None  # "TP1","TP2","TP3","SL","BE","STALE"
    pnl_pct: float = 0.0   # price-based signed % return
    be_triggered: bool = False
    max_favorable_excursion: float = 0.0   # best unrealized PnL % during trade
    max_adverse_excursion: float = 0.0     # worst unrealized PnL % during trade
    bars_held: int = 0


# ── BacktestResult ────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """Aggregated performance report produced by :class:`Backtester`."""

    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float

    # Core metrics
    total_trades: int
    wins: int
    losses: int
    break_evens: int
    stale_closes: int
    win_rate: float           # wins / total as percentage
    profit_factor: float      # gross_profit / gross_loss

    # Risk metrics
    sharpe_ratio: float       # annualized
    max_drawdown_pct: float   # peak-to-trough as percentage
    max_drawdown_duration: str
    calmar_ratio: float       # annualized_return / max_drawdown

    # Trade analysis
    avg_win_pct: float
    avg_loss_pct: float
    largest_win_pct: float
    largest_loss_pct: float
    avg_holding_time: str
    max_consecutive_wins: int
    max_consecutive_losses: int

    # Excursion analysis
    avg_max_favorable_excursion: float
    avg_max_adverse_excursion: float

    # Capital curve
    equity_curve: list[dict] = field(default_factory=list)
    monthly_returns: dict = field(default_factory=dict)

    # Per-side breakdown
    long_trades: int = 0
    long_win_rate: float = 0.0
    short_trades: int = 0
    short_win_rate: float = 0.0

    # Trade log
    trades: list[SimulatedTrade] = field(default_factory=list)

    # ── Output helpers ────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Return a concise multi-line summary suitable for Telegram or console."""
        net_pct = (self.final_capital - self.initial_capital) / self.initial_capital * 100
        lines = [
            f"📊 *Backtest — {self.symbol}*",
            f"Period  : {self.start_date} → {self.end_date}",
            f"Capital : ${self.initial_capital:,.2f} → ${self.final_capital:,.2f} "
            f"({net_pct:+.2f}%)",
            "",
            f"Trades  : {self.total_trades}  "
            f"(W {self.wins} / L {self.losses} / BE {self.break_evens} / Stale {self.stale_closes})",
            f"Win Rate: {self.win_rate:.1f}%",
            f"PF      : {self.profit_factor:.2f}",
            f"Sharpe  : {self.sharpe_ratio:.2f}",
            f"Max DD  : {self.max_drawdown_pct:.1f}%  ({self.max_drawdown_duration})",
            f"Calmar  : {self.calmar_ratio:.2f}",
            "",
            f"Avg Win : +{self.avg_win_pct:.2f}%  |  Avg Loss: {self.avg_loss_pct:.2f}%",
            f"Best    : +{self.largest_win_pct:.2f}%  |  Worst : {self.largest_loss_pct:.2f}%",
            f"Avg Hold: {self.avg_holding_time}",
            f"Streaks : {self.max_consecutive_wins}W / {self.max_consecutive_losses}L",
        ]
        return "\n".join(lines)

    def to_csv(self, filepath: str) -> None:
        """Export all trades to a CSV file for external analysis."""
        fieldnames = [
            "signal_id", "symbol", "side", "confidence",
            "entry_price", "stop_loss", "tp1", "tp2", "tp3",
            "opened_at", "closed_at", "close_reason",
            "pnl_pct", "be_triggered",
            "max_favorable_excursion", "max_adverse_excursion",
            "bars_held",
        ]
        with open(filepath, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for t in self.trades:
                writer.writerow(
                    {
                        "signal_id": t.signal_id,
                        "symbol": t.symbol,
                        "side": t.side,
                        "confidence": t.confidence,
                        "entry_price": t.entry_price,
                        "stop_loss": t.stop_loss,
                        "tp1": t.tp1,
                        "tp2": t.tp2,
                        "tp3": t.tp3,
                        "opened_at": t.opened_at,
                        "closed_at": t.closed_at,
                        "close_reason": t.close_reason,
                        "pnl_pct": t.pnl_pct,
                        "be_triggered": t.be_triggered,
                        "max_favorable_excursion": t.max_favorable_excursion,
                        "max_adverse_excursion": t.max_adverse_excursion,
                        "bars_held": t.bars_held,
                    }
                )

    def print_report(self) -> None:
        """Print a full institutional-grade report to the console."""
        sep = "─" * 60
        print(sep)
        print(f" BACKTEST REPORT — {self.symbol}")
        print(f" {self.start_date}  →  {self.end_date}")
        print(sep)
        net_pct = (self.final_capital - self.initial_capital) / self.initial_capital * 100
        print(f"  Initial Capital  : ${self.initial_capital:>12,.2f}")
        print(f"  Final Capital    : ${self.final_capital:>12,.2f}  ({net_pct:+.2f}%)")
        print(sep)
        print("  TRADE STATISTICS")
        print(f"  Total Trades     : {self.total_trades}")
        print(f"  Wins             : {self.wins}")
        print(f"  Losses           : {self.losses}")
        print(f"  Break-Evens      : {self.break_evens}")
        print(f"  Stale Closes     : {self.stale_closes}")
        print(f"  Win Rate         : {self.win_rate:.1f}%")
        print(f"  Profit Factor    : {self.profit_factor:.2f}")
        print(sep)
        print("  RISK METRICS")
        print(f"  Sharpe Ratio     : {self.sharpe_ratio:.2f}")
        print(f"  Max Drawdown     : {self.max_drawdown_pct:.1f}%  ({self.max_drawdown_duration})")
        print(f"  Calmar Ratio     : {self.calmar_ratio:.2f}")
        print(sep)
        print("  TRADE ANALYSIS")
        print(f"  Avg Win          : +{self.avg_win_pct:.2f}%")
        print(f"  Avg Loss         :  {self.avg_loss_pct:.2f}%")
        print(f"  Largest Win      : +{self.largest_win_pct:.2f}%")
        print(f"  Largest Loss     :  {self.largest_loss_pct:.2f}%")
        print(f"  Avg Holding Time : {self.avg_holding_time}")
        print(f"  Max Consec. Wins : {self.max_consecutive_wins}")
        print(f"  Max Consec. Loss : {self.max_consecutive_losses}")
        print(sep)
        print("  EXCURSION")
        print(f"  Avg MFE          : +{self.avg_max_favorable_excursion:.2f}%")
        print(f"  Avg MAE          :  {self.avg_max_adverse_excursion:.2f}%")
        print(sep)
        print("  PER-SIDE BREAKDOWN")
        print(f"  LONG  trades     : {self.long_trades}  (win rate {self.long_win_rate:.1f}%)")
        print(f"  SHORT trades     : {self.short_trades}  (win rate {self.short_win_rate:.1f}%)")
        print(sep)
        if self.monthly_returns:
            print("  MONTHLY RETURNS")
            for month, ret in sorted(self.monthly_returns.items()):
                bar = "+" if ret >= 0 else ""
                print(f"  {month}  {bar}{ret:.2f}%")
            print(sep)
        print("  GO-LIVE THRESHOLDS")
        ok = "\u2705"
        fail = "\u274c"
        print(f"  Win Rate > 55%   : {ok if self.win_rate > 55 else fail}  ({self.win_rate:.1f}%)")
        print(f"  PF > 1.5         : {ok if self.profit_factor > 1.5 else fail}  ({self.profit_factor:.2f})")
        print(f"  Max DD < 15%     : {ok if self.max_drawdown_pct < 15 else fail}  ({self.max_drawdown_pct:.1f}%)")
        print(f"  Sharpe > 1.0     : {ok if self.sharpe_ratio > 1.0 else fail}  ({self.sharpe_ratio:.2f})")
        print(sep)


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    """
    Walk-forward backtester that replays historical 5m candles through the
    live confluence engine without divergence.
    """

    # Sliding-window sizes (mirror the live bot)
    _DAILY_WINDOW = 25
    _4H_WINDOW = 15
    _5M_WINDOW = 50
    _RECENT_4H = 10   # 4H candles used to derive range
    _RECENT_5M = 10   # 5m candles used to derive key level

    def __init__(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        be_trigger_fraction: float = 0.50,
        stale_hours: int = 4,
        max_same_side: int = 3,
        tp1_rr: float = 1.5,
        tp2_rr: float = 2.5,
        tp3_rr: float = 4.0,
        check_fvg: bool = True,
        check_order_block: bool = True,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
    ) -> None:
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.be_trigger_fraction = be_trigger_fraction
        self.stale_hours = stale_hours
        self.max_same_side = max_same_side
        self.tp1_rr = tp1_rr
        self.tp2_rr = tp2_rr
        self.tp3_rr = tp3_rr
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """
        Main backtest loop.

        1. Fetch historical data for all 3 timeframes (1D, 4H, 5m).
        2. Iterate through 5m candles chronologically.
        3. For each candle:
           a. Update all active trades (check exits).
           b. If capacity permits, run run_confluence_check() for LONG + SHORT.
           c. Open a SimulatedTrade when a signal is returned.
        4. Force-close any open trades at the final candle.
        5. Compute and return BacktestResult.
        """
        fetcher = HistoricalDataFetcher()
        all_1d = fetcher.fetch_historical(self.symbol, "1d", self.start_date, self.end_date)
        all_4h = fetcher.fetch_historical(self.symbol, "4h", self.start_date, self.end_date)
        all_5m = fetcher.fetch_historical(self.symbol, "5m", self.start_date, self.end_date)

        if not all_5m:
            raise ValueError(f"No 5m historical data returned for {self.symbol!r}.")

        symbol_name = self.symbol.split("/")[0]

        # Pre-build sorted timestamp lists for fast window extraction
        ts_1d = [r.timestamp for r in all_1d]
        ts_4h = [r.timestamp for r in all_4h]

        active_trades: list[SimulatedTrade] = []
        closed_trades: list[SimulatedTrade] = []
        equity = float(self.initial_capital)
        peak_equity = equity
        equity_curve: list[dict] = [
            {"timestamp": all_5m[0].timestamp, "equity": equity, "drawdown": 0.0}
        ]
        trade_counter = 0

        for i, row_5m in enumerate(all_5m):
            current_ts = row_5m.timestamp
            candle_5m = row_5m.candle

            # Build sliding windows for this 5m bar
            daily_window = self._window(all_1d, ts_1d, current_ts, self._DAILY_WINDOW)
            four_h_window = self._window(all_4h, ts_4h, current_ts, self._4H_WINDOW)
            five_m_window = [r.candle for r in all_5m[max(0, i - self._5M_WINDOW + 1): i + 1]]

            # ── a. Update open trades ─────────────────────────────────────
            for trade in list(active_trades):
                closed = self._simulate_trade_update(trade, candle_5m, current_ts)
                if closed:
                    equity = self._apply_trade_pnl(equity, trade)
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (
                        (peak_equity - equity) / peak_equity * 100
                        if peak_equity > 0
                        else 0.0
                    )
                    equity_curve.append(
                        {"timestamp": current_ts, "equity": equity, "drawdown": drawdown}
                    )
                    active_trades.remove(trade)
                    closed_trades.append(trade)

            # ── b–d. Scan for new signals ─────────────────────────────────
            if len(daily_window) < 20 or len(four_h_window) < 2 or len(five_m_window) < 3:
                continue

            for side in (Side.LONG, Side.SHORT):
                same_side = sum(1 for t in active_trades if t.side == side.value)
                if same_side >= self.max_same_side:
                    continue

                # Derive market context — same logic as _fetch_binance_candles()
                recent_4h = (
                    four_h_window[-self._RECENT_4H :]
                    if len(four_h_window) >= self._RECENT_4H
                    else four_h_window
                )
                range_low = min(c.low for c in recent_4h)
                range_high = max(c.high for c in recent_4h)

                recent_5m = (
                    five_m_window[-self._RECENT_5M :]
                    if len(five_m_window) >= self._RECENT_5M
                    else five_m_window
                )
                if side == Side.LONG:
                    key_level = min(c.low for c in recent_5m)
                else:
                    key_level = max(c.high for c in recent_5m)

                atr_proxy = (range_high - range_low) * 0.01
                stop_loss = (
                    key_level - atr_proxy
                    if side == Side.LONG
                    else key_level + atr_proxy
                )

                signal = run_confluence_check(
                    symbol=symbol_name,
                    current_price=candle_5m.close,
                    side=side,
                    range_low=range_low,
                    range_high=range_high,
                    key_liquidity_level=key_level,
                    five_min_candles=five_m_window,
                    daily_candles=daily_window,
                    four_hour_candles=four_h_window,
                    news_in_window=False,
                    stop_loss=stop_loss,
                )

                if signal is not None:
                    trade_counter += 1
                    entry_price = (signal.entry_low + signal.entry_high) / 2
                    active_trades.append(
                        SimulatedTrade(
                            signal_id=f"{symbol_name}_{side.value}_{trade_counter}",
                            symbol=symbol_name,
                            side=side.value,
                            confidence=signal.confidence.value,
                            entry_price=entry_price,
                            stop_loss=signal.stop_loss,
                            tp1=signal.tp1,
                            tp2=signal.tp2,
                            tp3=signal.tp3,
                            opened_at=current_ts,
                        )
                    )

        # 4. Force-close remaining open trades at last candle's close price
        if all_5m:
            last_row = all_5m[-1]
            last_close = last_row.candle.close
            last_ts = last_row.timestamp
            for trade in active_trades:
                if trade.side == "LONG":
                    trade.pnl_pct = (last_close - trade.entry_price) / trade.entry_price * 100
                else:
                    trade.pnl_pct = (trade.entry_price - last_close) / trade.entry_price * 100
                trade.close_reason = "STALE"
                trade.closed_at = last_ts
                closed_trades.append(trade)

        return _compute_result(
            symbol=self.symbol,
            start_date=self.start_date,
            end_date=self.end_date,
            initial_capital=self.initial_capital,
            final_capital=equity,
            trades=closed_trades,
            equity_curve=equity_curve,
            risk_per_trade=self.risk_per_trade,
        )

    # ── Trade update ──────────────────────────────────────────────────────────

    def _simulate_trade_update(
        self,
        trade: SimulatedTrade,
        candle: CandleData,
        candle_ts: float,
    ) -> bool:
        """
        Check whether *candle* triggers any exit for *trade*.

        Exit priority (conservative):
        1. SL hit first — worst-case assumption when both SL and TP hit same bar.
        2. TP3 hit
        3. TP2 hit
        4. TP1 hit
        5. BE trigger (move SL to entry, checked before price tests)
        6. Stale (time-based)

        Returns True when the trade was closed.
        """
        trade.bars_held += 1

        # Track excursion
        if trade.side == "LONG":
            mfe = (candle.high - trade.entry_price) / trade.entry_price * 100
            mae = (trade.entry_price - candle.low) / trade.entry_price * 100
        else:
            mfe = (trade.entry_price - candle.low) / trade.entry_price * 100
            mae = (candle.high - trade.entry_price) / trade.entry_price * 100

        if mfe > 0:
            trade.max_favorable_excursion = max(trade.max_favorable_excursion, mfe)
        if mae > 0:
            trade.max_adverse_excursion = max(trade.max_adverse_excursion, mae)

        current_sl = trade.stop_loss  # may already be at entry if BE triggered previously

        # Evaluate price tests with current stop-loss
        if trade.side == "LONG":
            sl_hit = candle.low <= current_sl
            tp1_hit = candle.high >= trade.tp1
            tp2_hit = candle.high >= trade.tp2
            tp3_hit = candle.high >= trade.tp3
        else:
            sl_hit = candle.high >= current_sl
            tp1_hit = candle.low <= trade.tp1
            tp2_hit = candle.low <= trade.tp2
            tp3_hit = candle.low <= trade.tp3

        # 1. SL takes priority (conservative worst-case when SL and TP hit same bar)
        if sl_hit:
            exit_price = current_sl
            if trade.side == "LONG":
                trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100
            else:
                trade.pnl_pct = (trade.entry_price - exit_price) / trade.entry_price * 100
            trade.close_reason = "BE" if trade.be_triggered else "SL"
            trade.closed_at = candle_ts
            return True

        # 2–4. TP levels (best-case intra-bar order assumed)
        if tp3_hit:
            trade.pnl_pct = self._tp_pnl(trade, trade.tp3)
            trade.close_reason = "TP3"
            trade.closed_at = candle_ts
            return True

        if tp2_hit:
            trade.pnl_pct = self._tp_pnl(trade, trade.tp2)
            trade.close_reason = "TP2"
            trade.closed_at = candle_ts
            return True

        if tp1_hit:
            trade.pnl_pct = self._tp_pnl(trade, trade.tp1)
            trade.close_reason = "TP1"
            trade.closed_at = candle_ts
            return True

        # 5. BE trigger: update stop-loss for *future* candles (does not close this bar)
        if not trade.be_triggered:
            if trade.side == "LONG":
                be_threshold = trade.entry_price + (
                    trade.tp1 - trade.entry_price
                ) * self.be_trigger_fraction
                if candle.high >= be_threshold:
                    trade.be_triggered = True
                    trade.stop_loss = trade.entry_price
            else:
                be_threshold = trade.entry_price - (
                    trade.entry_price - trade.tp1
                ) * self.be_trigger_fraction
                if candle.low <= be_threshold:
                    trade.be_triggered = True
                    trade.stop_loss = trade.entry_price

        # 6. Stale: trade open longer than stale_hours without hitting any target
        if candle_ts - trade.opened_at > self.stale_hours * 3600:
            if trade.side == "LONG":
                trade.pnl_pct = (candle.close - trade.entry_price) / trade.entry_price * 100
            else:
                trade.pnl_pct = (trade.entry_price - candle.close) / trade.entry_price * 100
            trade.close_reason = "STALE"
            trade.closed_at = candle_ts
            return True

        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _tp_pnl(trade: SimulatedTrade, tp_price: float) -> float:
        if trade.side == "LONG":
            return (tp_price - trade.entry_price) / trade.entry_price * 100
        return (trade.entry_price - tp_price) / trade.entry_price * 100

    def _apply_trade_pnl(self, equity: float, trade: SimulatedTrade) -> float:
        """
        Update equity using risk-based position sizing (compounding).

        With risk_per_trade = 1%, an SL hit always costs exactly 1 % of
        current equity regardless of SL distance.
        """
        sl_dist = abs(trade.entry_price - trade.stop_loss)
        if sl_dist <= 0 or trade.entry_price <= 0:
            return equity
        sl_frac = sl_dist / trade.entry_price
        equity_delta = equity * self.risk_per_trade * (trade.pnl_pct / 100) / sl_frac
        return max(equity + equity_delta, 0.0)

    @staticmethod
    def _window(
        rows: list[_OHLCVRow],
        timestamps: list[float],
        current_ts: float,
        size: int,
    ) -> list[CandleData]:
        """
        Return the last *size* candles whose timestamp is <= *current_ts*.
        Uses binary search for O(log n) lookup.
        """
        idx = bisect.bisect_right(timestamps, current_ts)
        return [r.candle for r in rows[max(0, idx - size): idx]]


# ── Metrics computation ───────────────────────────────────────────────────────

def _compute_result(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    final_capital: float,
    trades: list[SimulatedTrade],
    equity_curve: list[dict],
    risk_per_trade: float,
) -> BacktestResult:
    """Build a :class:`BacktestResult` from a closed-trade list."""

    total = len(trades)

    wins_list = [t for t in trades if t.close_reason in ("TP1", "TP2", "TP3")]
    losses_list = [t for t in trades if t.close_reason == "SL"]
    be_list = [t for t in trades if t.close_reason == "BE"]
    stale_list = [t for t in trades if t.close_reason == "STALE"]

    wins = len(wins_list)
    losses = len(losses_list)
    break_evens = len(be_list)
    stale_closes = len(stale_list)
    win_rate = wins / total * 100 if total else 0.0

    # Profit factor
    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Sharpe ratio (annualized, per-trade returns)
    pnl_list = [t.pnl_pct for t in trades]
    sharpe = 0.0
    if len(pnl_list) >= 2:
        mean_r = statistics.mean(pnl_list)
        std_r = statistics.stdev(pnl_list)
        if std_r > 0:
            # Annualise: assume ~250 trading days, estimate trades per year
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            trading_days = max((end_dt - start_dt).days, 1)
            trades_per_year = total / trading_days * 252
            sharpe = (mean_r / std_r) * math.sqrt(trades_per_year)

    # Max drawdown + duration
    max_dd = max((e["drawdown"] for e in equity_curve), default=0.0)
    max_dd_dur = _max_drawdown_duration(equity_curve)

    # Calmar ratio
    calmar = 0.0
    if max_dd > 0 and initial_capital > 0:
        start_dt2 = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt2 = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        years = max((end_dt2 - start_dt2).days / 365.25, 1 / 365.25)
        total_return = (final_capital - initial_capital) / initial_capital
        annualized_return = (1 + total_return) ** (1 / years) - 1
        calmar = annualized_return * 100 / max_dd

    # Per-trade stats
    avg_win = statistics.mean(t.pnl_pct for t in wins_list) if wins_list else 0.0
    avg_loss = statistics.mean(t.pnl_pct for t in losses_list) if losses_list else 0.0
    largest_win = max((t.pnl_pct for t in trades), default=0.0)
    largest_loss = min((t.pnl_pct for t in trades), default=0.0)

    # Average holding time
    hold_secs = [
        (t.closed_at - t.opened_at)
        for t in trades
        if t.closed_at is not None
    ]
    avg_hold = _format_duration(statistics.mean(hold_secs)) if hold_secs else "n/a"

    # Consecutive streak counts
    max_wins, max_losses = _streak_counts(trades)

    # Excursion averages
    avg_mfe = statistics.mean(t.max_favorable_excursion for t in trades) if trades else 0.0
    avg_mae = statistics.mean(t.max_adverse_excursion for t in trades) if trades else 0.0

    # Monthly returns
    monthly = _monthly_returns(trades, equity_curve, initial_capital)

    # Per-side breakdown
    long_tr = [t for t in trades if t.side == "LONG"]
    short_tr = [t for t in trades if t.side == "SHORT"]
    long_wins = sum(1 for t in long_tr if t.close_reason in ("TP1", "TP2", "TP3"))
    short_wins = sum(1 for t in short_tr if t.close_reason in ("TP1", "TP2", "TP3"))
    long_wr = long_wins / len(long_tr) * 100 if long_tr else 0.0
    short_wr = short_wins / len(short_tr) * 100 if short_tr else 0.0

    return BacktestResult(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_trades=total,
        wins=wins,
        losses=losses,
        break_evens=break_evens,
        stale_closes=stale_closes,
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
        avg_holding_time=avg_hold,
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        avg_max_favorable_excursion=avg_mfe,
        avg_max_adverse_excursion=avg_mae,
        equity_curve=equity_curve,
        monthly_returns=monthly,
        long_trades=len(long_tr),
        long_win_rate=long_wr,
        short_trades=len(short_tr),
        short_win_rate=short_wr,
        trades=trades,
    )


def _max_drawdown_duration(equity_curve: list[dict]) -> str:
    """Return a human-readable string for the longest drawdown period."""
    if not equity_curve:
        return "n/a"

    max_dur_seconds = 0.0
    dd_start: Optional[float] = None
    peak = equity_curve[0]["equity"]

    for point in equity_curve:
        eq = point["equity"]
        ts = point["timestamp"]
        if eq >= peak:
            if dd_start is not None:
                dur = ts - dd_start
                max_dur_seconds = max(max_dur_seconds, dur)
            peak = eq
            dd_start = None
        else:
            if dd_start is None:
                dd_start = ts

    # If still in drawdown at end
    if dd_start is not None:
        dur = equity_curve[-1]["timestamp"] - dd_start
        max_dur_seconds = max(max_dur_seconds, dur)

    return _format_duration(max_dur_seconds)


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"
    days = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{days}d {h}h"


def _streak_counts(trades: list[SimulatedTrade]) -> tuple[int, int]:
    """Return (max_consecutive_wins, max_consecutive_losses)."""
    max_w = max_l = cur_w = cur_l = 0
    for t in trades:
        if t.close_reason in ("TP1", "TP2", "TP3"):
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif t.close_reason == "SL":
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0
    return max_w, max_l


def _monthly_returns(
    trades: list[SimulatedTrade],
    equity_curve: list[dict],
    initial_capital: float,
) -> dict[str, float]:
    """
    Compute calendar-month returns as the sum of price-based PnL percentages
    per month. Risk-per-trade weighting is not applied here — this gives a
    simple monthly aggregation suitable for reporting.
    """
    monthly: dict[str, float] = {}
    for t in trades:
        if t.closed_at is None:
            continue
        month = datetime.fromtimestamp(t.closed_at, tz=timezone.utc).strftime("%Y-%m")
        monthly[month] = monthly.get(month, 0.0) + t.pnl_pct
    return monthly
