"""
Backtesting Framework — 360 Crypto Eye Scalping
================================================
Walk-forward replay engine that drives historical OHLCV data through the
real 7-gate confluence engine (``bot/signal_engine.py``) and simulates the
full signal lifecycle: BE trigger, trailing SL, stale close, and TP hits.

See Blueprint §11 for the full specification.
"""

from __future__ import annotations

import csv
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


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _to_candle(row: list) -> CandleData:
    """Convert a raw CCXT OHLCV row ``[ts, O, H, L, C, V]`` to CandleData."""
    return CandleData(
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def _max_consecutive(trades: list[SimulatedTrade], positive: bool) -> int:
    """Return the longest run of wins (positive=True) or losses (positive=False)."""
    max_count = 0
    count = 0
    for t in trades:
        if (positive and t.pnl_pct > 0) or (not positive and t.pnl_pct < 0):
            count += 1
            max_count = max(max_count, count)
        else:
            count = 0
    return max_count


def _calculate_max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
    """
    Return ``(max_drawdown_pct, max_drawdown_duration_bars)`` from an equity curve.

    *max_drawdown_pct* is expressed as a positive percentage (e.g. 12.5 for 12.5%).
    *max_drawdown_duration_bars* is the longest number of bars spent below the
    prior peak.
    """
    if len(equity_curve) < 2:
        return 0.0, 0
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_duration = 0
    for i, val in enumerate(equity_curve):
        if val >= peak:
            peak = val
            peak_idx = i
        else:
            dd = (peak - val) / peak * 100.0
            duration = i - peak_idx
            if dd > max_dd:
                max_dd = dd
            if duration > max_dd_duration:
                max_dd_duration = duration
    return max_dd, max_dd_duration


def _compute_monthly_returns(trades: list[SimulatedTrade]) -> dict[str, float]:
    """Aggregate raw pnl_pct by YYYY-MM using each trade's ``closed_at`` timestamp."""
    monthly: dict[str, float] = {}
    for t in trades:
        if t.closed_at > 0:
            dt = datetime.fromtimestamp(t.closed_at / 1000, tz=timezone.utc)
            key = f"{dt.year}-{dt.month:02d}"
            monthly[key] = monthly.get(key, 0.0) + t.pnl_pct
    return monthly


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SimulatedTrade:
    """Records the full lifecycle of one simulated trade."""

    signal_id: str
    symbol: str
    side: Side
    confidence: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: int              # Unix ms timestamp
    closed_at: int = 0
    close_reason: str = ""      # "TP1" | "TP2" | "TP3" | "SL" | "BE" | "STALE"
    pnl_pct: float = 0.0
    be_triggered: bool = False
    max_favorable_excursion: float = 0.0  # best unrealised %, positive
    max_adverse_excursion: float = 0.0    # worst unrealised %, positive (loss magnitude)
    bars_held: int = 0


@dataclass
class BacktestResult:
    """Aggregated performance metrics for one backtest run."""

    symbol: str
    total_trades: int
    wins: int
    losses: int
    break_evens: int
    stale_closes: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration: int   # bars
    calmar_ratio: float
    avg_win_pct: float
    avg_loss_pct: float
    largest_win_pct: float
    largest_loss_pct: float
    avg_holding_time: float      # bars
    max_consecutive_wins: int
    max_consecutive_losses: int
    equity_curve: list[float]
    monthly_returns: dict[str, float]
    long_trades: int
    short_trades: int
    long_wins: int
    short_wins: int
    trades: list[SimulatedTrade] = field(default_factory=list)

    def summary(self) -> str:
        """One-line performance summary suitable for Telegram messages."""
        return (
            f"Symbol: {self.symbol} | Trades: {self.total_trades} | "
            f"Win Rate: {self.win_rate:.1%} | PF: {self.profit_factor:.2f} | "
            f"Sharpe: {self.sharpe_ratio:.2f} | MaxDD: {self.max_drawdown_pct:.1f}%"
        )

    def to_csv(self, path: str) -> None:
        """Write per-trade data to a CSV file at *path*."""
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "signal_id", "symbol", "side", "confidence",
                "entry_price", "stop_loss", "tp1", "tp2", "tp3",
                "opened_at", "closed_at", "close_reason",
                "pnl_pct", "be_triggered", "mfe_pct", "mae_pct", "bars_held",
            ])
            for t in self.trades:
                writer.writerow([
                    t.signal_id, t.symbol, t.side.value, t.confidence,
                    t.entry_price, t.stop_loss, t.tp1, t.tp2, t.tp3,
                    t.opened_at, t.closed_at, t.close_reason,
                    round(t.pnl_pct, 6), t.be_triggered,
                    round(t.max_favorable_excursion, 6),
                    round(t.max_adverse_excursion, 6),
                    t.bars_held,
                ])

    def print_report(self) -> None:  # pragma: no cover
        """Print a human-readable performance report to stdout."""
        print(f"\n{'=' * 60}")
        print(f"  360 Crypto Eye — Backtest Report: {self.symbol}")
        print(f"{'=' * 60}")
        print(f"  Total Trades       : {self.total_trades}")
        print(f"  Wins / Losses      : {self.wins} / {self.losses}")
        print(f"  Break-Evens        : {self.break_evens}")
        print(f"  Stale Closes       : {self.stale_closes}")
        print(f"  Win Rate           : {self.win_rate:.1%}")
        print(f"  Profit Factor      : {self.profit_factor:.2f}")
        print(f"  Sharpe Ratio       : {self.sharpe_ratio:.2f}")
        print(f"  Calmar Ratio       : {self.calmar_ratio:.2f}")
        print(f"  Max Drawdown       : {self.max_drawdown_pct:.2f}%")
        print(f"  Avg Win %          : {self.avg_win_pct:.4f}%")
        print(f"  Avg Loss %         : {self.avg_loss_pct:.4f}%")
        print(f"  Largest Win %      : {self.largest_win_pct:.4f}%")
        print(f"  Largest Loss %     : {self.largest_loss_pct:.4f}%")
        print(f"  Avg Holding Time   : {self.avg_holding_time:.1f} bars")
        print(f"  Max Consec. Wins   : {self.max_consecutive_wins}")
        print(f"  Max Consec. Losses : {self.max_consecutive_losses}")
        print(f"  Long / Short       : {self.long_trades} / {self.short_trades}")
        print(f"  Long Wins          : {self.long_wins}")
        print(f"  Short Wins         : {self.short_wins}")
        if len(self.equity_curve) > 1:
            initial = self.equity_curve[0]
            final = self.equity_curve[-1]
            total_return = (final - initial) / initial * 100
            print(f"  Total Return       : {total_return:.2f}%")
            print(f"  Final Equity       : {final:.2f}")
        if self.monthly_returns:
            print(f"\n  Monthly Returns:")
            for month, ret in sorted(self.monthly_returns.items()):
                bar = "▲" if ret >= 0 else "▼"
                print(f"    {month}: {bar} {ret:+.2f}%")
        print(f"{'=' * 60}\n")


# ── Historical data fetcher ───────────────────────────────────────────────────

class HistoricalDataFetcher:
    """
    Paginate through Binance Futures OHLCV data using CCXT.

    Each request fetches up to ``CANDLES_PER_REQUEST`` candles.  A short sleep
    between requests avoids hitting Binance rate limits.
    """

    CANDLES_PER_REQUEST: int = 1000
    SLEEP_BETWEEN_REQUESTS: float = 0.2  # seconds

    def __init__(self, exchange: Optional[ccxt.Exchange] = None) -> None:
        if exchange is None:
            exchange = ccxt.binance({"options": {"defaultType": "future"}})
        self.exchange = exchange

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> list[list]:
        """
        Return all OHLCV rows for *symbol* / *timeframe* in the range
        [*since_ms*, *until_ms*] (inclusive, Unix milliseconds).

        Paginates automatically using the ``since`` parameter.
        """
        all_rows: list[list] = []
        cursor = since_ms
        while cursor < until_ms:
            rows = self.exchange.fetch_ohlcv(
                symbol,
                timeframe,
                since=cursor,
                limit=self.CANDLES_PER_REQUEST,
            )
            if not rows:
                break
            all_rows.extend(rows)
            last_ts: int = rows[-1][0]
            if last_ts <= cursor:
                break  # no forward progress — prevent infinite loop
            cursor = last_ts + 1
            if cursor >= until_ms:
                break
            time.sleep(self.SLEEP_BETWEEN_REQUESTS)

        # Deduplicate and filter to requested range
        seen: set[int] = set()
        result: list[list] = []
        for row in all_rows:
            ts: int = row[0]
            if since_ms <= ts <= until_ms and ts not in seen:
                seen.add(ts)
                result.append(row)
        result.sort(key=lambda r: r[0])
        return result


# ── Core backtesting engine ───────────────────────────────────────────────────

class Backtester:
    """
    Walk-forward replay engine for the 360 Crypto Eye Scalping system.

    Drives historical candle data through the real ``run_confluence_check()``
    function from ``bot/signal_engine.py`` — zero divergence from live engine.

    Trade exit priority (conservative):
      1. SL first (if SL and TP hit on the same bar, SL wins)
      2. TP3 → TP2 → TP1 (highest achieved TP wins)
      3. BE (SL moved to entry after TP1 distance is 50% reached)
      4. STALE close (after *stale_hours* have elapsed)

    Capital is compounded: each trade risks ``risk_per_trade`` of *current* equity.
    """

    WINDOW_5M: int = 50    # 5-minute candle lookback
    WINDOW_4H: int = 15    # 4H candle lookback
    WINDOW_1D: int = 25    # Daily candle lookback
    _5M_PER_HOUR: int = 12  # 12 × 5-minute bars = 1 hour

    def __init__(
        self,
        be_trigger_fraction: float = 0.5,
        stale_hours: float = 4.0,
        tp1_rr: float = 1.5,
        tp2_rr: float = 2.5,
        tp3_rr: float = 4.0,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
        check_fvg: bool = False,
        check_order_block: bool = False,
    ) -> None:
        self.be_trigger_fraction = be_trigger_fraction
        self.stale_bars = max(1, int(stale_hours * self._5M_PER_HOUR))
        self.tp1_rr = tp1_rr
        self.tp2_rr = tp2_rr
        self.tp3_rr = tp3_rr
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.check_fvg = check_fvg
        self.check_order_block = check_order_block

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        symbol: str,
        five_min_rows: list[list],
        four_h_rows: list[list],
        daily_rows: list[list],
    ) -> BacktestResult:
        """
        Walk-forward replay over all supplied data.

        Parameters
        ----------
        symbol:
            Short name used in signals (e.g. ``"BTC"``).
        five_min_rows / four_h_rows / daily_rows:
            Raw CCXT OHLCV rows ``[ts_ms, open, high, low, close, volume]``,
            sorted ascending by timestamp.

        Returns
        -------
        BacktestResult
            Fully populated performance report.
        """
        equity = self.initial_capital
        equity_curve: list[float] = [equity]
        trades: list[SimulatedTrade] = []
        open_trade: Optional[SimulatedTrade] = None
        trade_open_idx: int = 0

        for i in range(self.WINDOW_5M, len(five_min_rows)):
            current_row = five_min_rows[i]
            ts_now: int = current_row[0]
            current_candle = _to_candle(current_row)

            if open_trade is not None:
                # ── Advance open trade one bar ────────────────────────────
                bars_since_open = i - trade_open_idx

                # Update MFE / MAE
                if open_trade.side == Side.LONG:
                    fav = (current_candle.high - open_trade.entry_price) / open_trade.entry_price * 100
                    adv = (open_trade.entry_price - current_candle.low) / open_trade.entry_price * 100
                else:
                    fav = (open_trade.entry_price - current_candle.low) / open_trade.entry_price * 100
                    adv = (current_candle.high - open_trade.entry_price) / open_trade.entry_price * 100
                open_trade.max_favorable_excursion = max(
                    open_trade.max_favorable_excursion, max(0.0, fav)
                )
                open_trade.max_adverse_excursion = max(
                    open_trade.max_adverse_excursion, max(0.0, adv)
                )

                # Current stop-loss reflects be_triggered state at START of this bar
                current_sl = (
                    open_trade.entry_price if open_trade.be_triggered
                    else open_trade.stop_loss
                )

                # Exit condition checks — SL takes priority over TP on same bar
                close_reason: Optional[str] = None
                close_price: float = 0.0

                if open_trade.side == Side.LONG:
                    sl_hit = current_candle.low <= current_sl
                    tp3_hit = current_candle.high >= open_trade.tp3
                    tp2_hit = current_candle.high >= open_trade.tp2
                    tp1_hit = current_candle.high >= open_trade.tp1
                else:
                    sl_hit = current_candle.high >= current_sl
                    tp3_hit = current_candle.low <= open_trade.tp3
                    tp2_hit = current_candle.low <= open_trade.tp2
                    tp1_hit = current_candle.low <= open_trade.tp1

                if sl_hit:
                    close_reason = "BE" if open_trade.be_triggered else "SL"
                    close_price = current_sl
                elif tp3_hit:
                    close_reason = "TP3"
                    close_price = open_trade.tp3
                elif tp2_hit:
                    close_reason = "TP2"
                    close_price = open_trade.tp2
                elif tp1_hit:
                    close_reason = "TP1"
                    close_price = open_trade.tp1
                elif bars_since_open >= self.stale_bars:
                    close_reason = "STALE"
                    close_price = current_candle.close

                # BE trigger check — only fires when no exit this bar.
                # Marks be_triggered so NEXT bar uses entry_price as SL.
                if close_reason is None and not open_trade.be_triggered:
                    if open_trade.side == Side.LONG:
                        be_price = open_trade.entry_price + (
                            open_trade.tp1 - open_trade.entry_price
                        ) * self.be_trigger_fraction
                        if current_candle.high >= be_price:
                            open_trade.be_triggered = True
                    else:
                        be_price = open_trade.entry_price - (
                            open_trade.entry_price - open_trade.tp1
                        ) * self.be_trigger_fraction
                        if current_candle.low <= be_price:
                            open_trade.be_triggered = True

                if close_reason is not None:
                    direction = 1 if open_trade.side == Side.LONG else -1
                    pnl_pct = (
                        direction
                        * (close_price - open_trade.entry_price)
                        / open_trade.entry_price
                        * 100
                    )
                    open_trade.closed_at = ts_now
                    open_trade.close_reason = close_reason
                    open_trade.pnl_pct = pnl_pct
                    open_trade.bars_held = bars_since_open

                    # Compound equity: risk_per_trade of current equity
                    risk_pct = (
                        abs(open_trade.entry_price - open_trade.stop_loss)
                        / open_trade.entry_price
                    )
                    if risk_pct > 0:
                        implied_leverage = self.risk_per_trade / risk_pct
                        equity_change = equity * implied_leverage * (pnl_pct / 100)
                        equity = max(0.0, equity + equity_change)

                    equity_curve.append(equity)
                    trades.append(open_trade)
                    open_trade = None
                    trade_open_idx = 0

            else:
                # ── Try to open a new trade ───────────────────────────────
                five_m_ctx = [
                    _to_candle(r)
                    for r in five_min_rows[i - self.WINDOW_5M: i + 1]
                ]

                # 4H context: all rows up to ts_now, take the last WINDOW_4H
                four_h_before = [r for r in four_h_rows if r[0] <= ts_now]
                if len(four_h_before) < 2:
                    continue
                four_h_ctx = [_to_candle(r) for r in four_h_before[-self.WINDOW_4H:]]

                # 1D context: all rows up to ts_now, take the last WINDOW_1D
                daily_before = [r for r in daily_rows if r[0] <= ts_now]
                if len(daily_before) < 20:
                    continue
                daily_ctx = [_to_candle(r) for r in daily_before[-self.WINDOW_1D:]]

                current_price = five_m_ctx[-1].close

                # Derive range and key levels using same logic as live bot
                recent_4h = four_h_ctx[-10:] if len(four_h_ctx) >= 10 else four_h_ctx
                range_low = min(c.low for c in recent_4h)
                range_high = max(c.high for c in recent_4h)
                recent_5m_10 = five_m_ctx[-10:]
                atr_proxy = (range_high - range_low) * 0.01

                for side in (Side.LONG, Side.SHORT):
                    if side == Side.LONG:
                        key_level = min(c.low for c in recent_5m_10)
                        stop_loss = key_level - atr_proxy
                    else:
                        key_level = max(c.high for c in recent_5m_10)
                        stop_loss = key_level + atr_proxy

                    try:
                        result = run_confluence_check(
                            symbol=symbol,
                            current_price=current_price,
                            side=side,
                            range_low=range_low,
                            range_high=range_high,
                            key_liquidity_level=key_level,
                            five_min_candles=five_m_ctx,
                            daily_candles=daily_ctx,
                            four_hour_candles=four_h_ctx,
                            news_in_window=False,
                            stop_loss=stop_loss,
                            tp1_rr=self.tp1_rr,
                            tp2_rr=self.tp2_rr,
                            tp3_rr=self.tp3_rr,
                            check_fvg=self.check_fvg,
                            check_order_block=self.check_order_block,
                        )
                    except Exception:
                        result = None

                    if result is not None:
                        entry_price = (result.entry_low + result.entry_high) / 2
                        open_trade = SimulatedTrade(
                            signal_id=result.signal_id,
                            symbol=symbol,
                            side=side,
                            confidence=result.confidence.value,
                            entry_price=entry_price,
                            stop_loss=result.stop_loss,
                            tp1=result.tp1,
                            tp2=result.tp2,
                            tp3=result.tp3,
                            opened_at=ts_now,
                        )
                        trade_open_idx = i
                        break  # Only one open trade at a time per symbol

        # Close any trade still open at end of data (conservative STALE)
        if open_trade is not None and five_min_rows:
            last_row = five_min_rows[-1]
            last_candle = _to_candle(last_row)
            direction = 1 if open_trade.side == Side.LONG else -1
            close_price = last_candle.close
            pnl_pct = (
                direction
                * (close_price - open_trade.entry_price)
                / open_trade.entry_price
                * 100
            )
            open_trade.closed_at = last_row[0]
            open_trade.close_reason = "STALE"
            open_trade.pnl_pct = pnl_pct
            open_trade.bars_held = len(five_min_rows) - 1 - trade_open_idx
            risk_pct = (
                abs(open_trade.entry_price - open_trade.stop_loss)
                / open_trade.entry_price
            )
            if risk_pct > 0:
                implied_leverage = self.risk_per_trade / risk_pct
                equity_change = equity * implied_leverage * (pnl_pct / 100)
                equity = max(0.0, equity + equity_change)
            equity_curve.append(equity)
            trades.append(open_trade)

        return _compute_result(symbol, trades, equity_curve, self.initial_capital)


# ── Metrics computation ───────────────────────────────────────────────────────

def _compute_result(
    symbol: str,
    trades: list[SimulatedTrade],
    equity_curve: list[float],
    initial_capital: float,
) -> BacktestResult:
    """Compute ``BacktestResult`` from a list of completed ``SimulatedTrade`` objects."""
    total_trades = len(trades)

    if total_trades == 0:
        return BacktestResult(
            symbol=symbol,
            total_trades=0,
            wins=0,
            losses=0,
            break_evens=0,
            stale_closes=0,
            win_rate=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_duration=0,
            calmar_ratio=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            largest_win_pct=0.0,
            largest_loss_pct=0.0,
            avg_holding_time=0.0,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            equity_curve=equity_curve,
            monthly_returns={},
            long_trades=0,
            short_trades=0,
            long_wins=0,
            short_wins=0,
            trades=trades,
        )

    wins = sum(1 for t in trades if t.pnl_pct > 0)
    losses = sum(1 for t in trades if t.pnl_pct < 0)
    break_evens = sum(1 for t in trades if t.close_reason == "BE")
    stale_closes = sum(1 for t in trades if t.close_reason == "STALE")

    win_rate = wins / total_trades

    win_pcts = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    loss_pcts = [t.pnl_pct for t in trades if t.pnl_pct < 0]

    total_profit = sum(win_pcts) if win_pcts else 0.0
    total_loss = abs(sum(loss_pcts)) if loss_pcts else 0.0
    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    avg_win_pct = statistics.mean(win_pcts) if win_pcts else 0.0
    avg_loss_pct = statistics.mean(loss_pcts) if loss_pcts else 0.0
    largest_win_pct = max(win_pcts) if win_pcts else 0.0
    largest_loss_pct = min(loss_pcts) if loss_pcts else 0.0
    avg_holding_time = statistics.mean(t.bars_held for t in trades)

    max_consec_wins = _max_consecutive(trades, positive=True)
    max_consec_losses = _max_consecutive(trades, positive=False)

    long_trades = sum(1 for t in trades if t.side == Side.LONG)
    short_trades = total_trades - long_trades
    long_wins = sum(1 for t in trades if t.side == Side.LONG and t.pnl_pct > 0)
    short_wins = sum(1 for t in trades if t.side == Side.SHORT and t.pnl_pct > 0)

    max_dd_pct, max_dd_duration = _calculate_max_drawdown(equity_curve)

    # Sharpe ratio — annualised using trade-level returns
    trade_returns = [t.pnl_pct for t in trades]
    if len(trade_returns) >= 2:
        mean_r = statistics.mean(trade_returns)
        std_r = statistics.stdev(trade_returns)
        # Scale to annual using 5m bars: sqrt(252 * 24 * 12)
        sharpe = (mean_r / std_r) * (252 * 24 * 12) ** 0.5 if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    # Calmar ratio — annualised total return / max drawdown
    if max_dd_pct > 0 and len(equity_curve) > 1:
        total_return_pct = (equity_curve[-1] - initial_capital) / initial_capital * 100
        total_bars = sum(t.bars_held for t in trades)
        annual_bars = 252 * 24 * 12  # 5-minute bars per year
        annualised_return = (
            total_return_pct * (annual_bars / total_bars)
            if total_bars > 0
            else 0.0
        )
        calmar = annualised_return / max_dd_pct
    else:
        calmar = 0.0

    monthly_returns = _compute_monthly_returns(trades)

    return BacktestResult(
        symbol=symbol,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        break_evens=break_evens,
        stale_closes=stale_closes,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration=max_dd_duration,
        calmar_ratio=calmar,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        largest_win_pct=largest_win_pct,
        largest_loss_pct=largest_loss_pct,
        avg_holding_time=avg_holding_time,
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
        equity_curve=equity_curve,
        monthly_returns=monthly_returns,
        long_trades=long_trades,
        short_trades=short_trades,
        long_wins=long_wins,
        short_wins=short_wins,
        trades=trades,
    )
