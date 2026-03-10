"""
Dashboard
=========
Live transparency log (Section VI of the master blueprint).

Tracks every closed signal result and exposes real-time statistics:
  • Win-rate % (by timeframe bucket: 5m, 15m, 1h)
  • Profit Factor = Gross Profit / Gross Loss
  • Current PnL — live floating profit/loss of all open 360 Eye signals
  • Sharpe Ratio, Max Drawdown, Equity Curve, Per-Symbol Performance

Results are persisted to a JSON file so they survive process restarts.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from config import DASHBOARD_LOG_FILE


@dataclass
class TradeResult:
    """One completed or open trade recorded in the transparency log."""

    symbol: str
    side: str           # "LONG" | "SHORT"
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: float    # Unix timestamp
    closed_at: Optional[float]
    outcome: str        # "WIN" | "LOSS" | "BE" | "STALE" | "OPEN"
    pnl_pct: float      # % PnL relative to entry
    timeframe: str      # "5m" | "15m" | "1h" — identifies which TF triggered entry
    channel_tier: str = "AGGREGATE"  # "CH1_HARD" | "CH2_MEDIUM" | "CH3_EASY" | "CH4_SPOT" | "AGGREGATE"
    session: str = "UNKNOWN"         # "LONDON" | "NYC" | "ASIA" | "OVERLAP" | "UNKNOWN"
    partial_exits: str = ""          # JSON-encoded list of {"level": "TP1", "pct": 50, "pnl": 1.5}
    composite_pnl_pct: float = 0.0   # weighted composite PnL across partial exits

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TradeResult":
        return cls(**d)


class Dashboard:
    """
    In-memory + file-persisted transparency dashboard.

    Usage example
    -------------
    >>> db = Dashboard()
    >>> db.record_result(TradeResult(..., outcome="WIN", pnl_pct=1.5, ...))
    >>> print(db.summary())
    """

    def __init__(self, log_file: str = DASHBOARD_LOG_FILE) -> None:
        self._log_file = Path(log_file)
        self._results: list[TradeResult] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._log_file.exists():
            try:
                raw = json.loads(self._log_file.read_text(encoding="utf-8"))
                self._results = [TradeResult.from_dict(r) for r in raw]
            except (json.JSONDecodeError, KeyError, TypeError):
                self._results = []

    def _save(self) -> None:
        self._log_file.write_text(
            json.dumps([r.to_dict() for r in self._results], indent=2),
            encoding="utf-8",
        )

    # ── recording ─────────────────────────────────────────────────────────────

    def record_result(self, result: TradeResult) -> None:
        """Append *result* to the log and persist immediately."""
        self._results.append(result)
        self._save()

    def update_open_pnl(self, symbol: str, current_price: float) -> None:
        """Refresh the floating PnL for an OPEN trade."""
        for r in self._results:
            if r.symbol == symbol and r.outcome == "OPEN":
                direction = 1 if r.side == "LONG" else -1
                r.pnl_pct = direction * (current_price - r.entry_price) / r.entry_price * 100
        self._save()

    # ── statistics ────────────────────────────────────────────────────────────

    def win_rate(self, timeframe: Optional[str] = None) -> float:
        """
        Return the win-rate as a percentage for closed trades.

        Parameters
        ----------
        timeframe:
            Filter by timeframe bucket ("5m", "15m", "1h").
            When None all closed trades are included.
        """
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE")
            and (timeframe is None or r.timeframe == timeframe)
        ]
        if not closed:
            return 0.0
        wins = sum(1 for r in closed if r.outcome == "WIN")
        return round(wins / len(closed) * 100, 2)

    def protected_win_rate(self, timeframe: Optional[str] = None) -> float:
        """
        Return the *protected* win-rate counting BE (breakeven) outcomes as wins.

        Rationale: When TP1 is hit and 50% is closed, position is moved to
        breakeven.  The trader protected capital and took partial profit, so BE
        is counted as a "protected win" rather than a loss.

        Parameters
        ----------
        timeframe:
            Filter by timeframe bucket ("5m", "15m", "1h").
            When None all closed trades are included.
        """
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE")
            and (timeframe is None or r.timeframe == timeframe)
        ]
        if not closed:
            return 0.0
        protected_wins = sum(1 for r in closed if r.outcome in ("WIN", "BE"))
        return round(protected_wins / len(closed) * 100, 2)

    def profit_factor(self) -> float:
        """
        Return the Profit Factor = Gross Profit / Gross Loss.
        Returns 0.0 (undefined) when there are no closed losing trades to divide by.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS")]
        gross_profit = sum(r.pnl_pct for r in closed if r.pnl_pct > 0)
        gross_loss = abs(sum(r.pnl_pct for r in closed if r.pnl_pct < 0))
        if gross_loss == 0:
            return 0.0
        return round(gross_profit / gross_loss, 4)

    def avg_risk_reward(self) -> float:
        """
        Return the average realised R:R across all closed trades.

        R is calculated as ``|pnl_pct| / |entry_to_sl_pct|`` for each trade,
        where ``entry_to_sl_pct = abs(entry_price - stop_loss) / entry_price * 100``.

        Returns 0.0 when there are no qualifying closed trades.
        """
        rr_values: list[float] = []
        for r in self._results:
            if r.outcome not in ("WIN", "LOSS", "BE"):
                continue
            if r.entry_price <= 0 or r.stop_loss <= 0:
                continue
            sl_dist_pct = abs(r.entry_price - r.stop_loss) / r.entry_price * 100
            if sl_dist_pct == 0:
                continue
            rr = abs(r.pnl_pct) / sl_dist_pct
            rr_values.append(rr)
        if not rr_values:
            return 0.0
        return round(sum(rr_values) / len(rr_values), 4)

    def current_open_pnl(self) -> float:
        """Return the aggregate floating PnL % across all OPEN signals."""
        return round(sum(r.pnl_pct for r in self._results if r.outcome == "OPEN"), 4)

    def win_rate_rolling(self, days: int = 7) -> float:
        """
        Return the win-rate for closed trades within the last *days* days.

        Parameters
        ----------
        days:
            Rolling lookback window in days (e.g. 7 for weekly, 30 for monthly).

        Returns
        -------
        float
            Win-rate as a percentage (0–100), or 0.0 when no trades in window.
        """
        cutoff = time.time() - days * 86400
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE")
            and r.closed_at is not None
            and r.closed_at >= cutoff
        ]
        if not closed:
            return 0.0
        wins = sum(1 for r in closed if r.outcome == "WIN")
        return round(wins / len(closed) * 100, 2)

    def total_trades(self) -> int:
        return len([r for r in self._results if r.outcome != "OPEN"])

    def stale_count(self) -> int:
        """Return the total number of STALE-closed trades."""
        return sum(1 for r in self._results if r.outcome == "STALE")

    def get_closed_trades(self) -> list[TradeResult]:
        """Return all closed trade results (WIN, LOSS, or BE) in chronological order."""
        return [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]

    def sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """
        Return the annualised Sharpe Ratio for closed trades.

        Aggregates per-trade PnL into daily buckets, then computes:
        ``Sharpe = (mean_daily_return - risk_free) / std_daily_return * sqrt(365)``

        Using 365 (not 252) because crypto markets trade 24/7.

        Returns 0.0 when there are fewer than 3 daily observations or std is 0.
        Uses Bessel's correction (n-1) for an unbiased sample variance.
        """
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE") and r.closed_at is not None
        ]
        if len(closed) < 3:
            return 0.0

        # Group PnL by calendar day (UTC)
        daily: dict[int, float] = {}
        for r in closed:
            # UTC day key (Unix timestamp in seconds // 86400)
            day_key = int(r.closed_at // 86400)
            daily[day_key] = daily.get(day_key, 0.0) + r.pnl_pct

        returns = list(daily.values())
        if len(returns) < 3:
            return 0.0

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance)
        if std_r == 0:
            return 0.0
        # Annualise using 365 trading days (crypto is 24/7)
        annualised = (mean_r - risk_free_rate) / std_r * math.sqrt(365)
        return round(annualised, 4)

    def max_drawdown(self) -> float:
        """
        Return the maximum peak-to-trough drawdown as a positive percentage.
        Returns 0.0 when there are no closed trades.
        """
        curve = self.equity_curve()
        if not curve:
            return 0.0
        peak = curve[0]
        max_dd = 0.0
        for val in curve:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 4)

    def average_holding_time(self) -> float:
        """
        Return the average holding time in hours for closed trades.
        Returns 0.0 when no trades have both opened_at and closed_at.
        """
        durations = [
            (r.closed_at - r.opened_at) / 3600
            for r in self._results
            if r.outcome not in ("OPEN",) and r.closed_at is not None
        ]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 4)

    def win_streak(self) -> int:
        """Return the current consecutive win streak (from most recent trade)."""
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        streak = 0
        for r in reversed(closed):
            if r.outcome == "WIN":
                streak += 1
            else:
                break
        return streak

    def loss_streak(self) -> int:
        """Return the current consecutive loss streak (from most recent trade)."""
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        streak = 0
        for r in reversed(closed):
            if r.outcome == "LOSS":
                streak += 1
            else:
                break
        return streak

    def equity_curve(self) -> list[float]:
        """
        Return a list of cumulative PnL values for all closed trades in order.
        Starting value is 0.0.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        curve: list[float] = []
        cumulative = 0.0
        for r in closed:
            cumulative += r.pnl_pct
            curve.append(round(cumulative, 4))
        return curve

    def per_symbol_performance(self) -> dict[str, dict]:
        """
        Return per-symbol performance stats.

        Returns a dict mapping symbol → {total, wins, losses, win_rate, total_pnl}.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        perf: dict[str, dict] = {}
        for r in closed:
            sym = r.symbol
            if sym not in perf:
                perf[sym] = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0}
            perf[sym]["total"] += 1
            if r.outcome == "WIN":
                perf[sym]["wins"] += 1
            elif r.outcome == "LOSS":
                perf[sym]["losses"] += 1
            perf[sym]["total_pnl"] = round(perf[sym]["total_pnl"] + r.pnl_pct, 4)
        for sym, stats in perf.items():
            if stats["total"] > 0:
                stats["win_rate"] = round(stats["wins"] / stats["total"] * 100, 2)
        return perf

    def summary(self) -> str:
        """Return a formatted Telegram-ready dashboard summary."""
        sharpe = self.sharpe_ratio()
        drawdown = self.max_drawdown()
        hold_time = self.average_holding_time()
        w_streak = self.win_streak()
        l_streak = self.loss_streak()
        lines = [
            "📊 360 EYE SCALP — LIVE DASHBOARD",
            "─────────────────────────────────",
            f"Total Closed Trades : {self.total_trades()}",
            f"  → Stale Closed    : {self.stale_count()}",
            f"Win Rate (strict)    : {self.win_rate():.2f}%",
            f"Win Rate (protected) : {self.protected_win_rate():.2f}%  (BE counted as win)",
            f"  → 5m entries       : {self.win_rate('5m'):.2f}%",
            f"  → 15m entries      : {self.win_rate('15m'):.2f}%",
            f"  → 1h entries       : {self.win_rate('1h'):.2f}%",
            f"Avg R:R Realised     : {self.avg_risk_reward():.2f}R",
            f"Profit Factor        : {self.profit_factor():.2f}",
            f"Sharpe Ratio         : {sharpe:.4f}",
            f"Max Drawdown         : {drawdown:.2f}%",
            f"Avg Holding Time     : {hold_time:.2f}h",
            f"Win Streak           : {w_streak}",
            f"Loss Streak          : {l_streak}",
            f"Open PnL (floating)  : {self.current_open_pnl():+.2f}%",
        ]
        return "\n".join(lines)

    # ── per-channel & per-session statistics ──────────────────────────────────

    def _channel_stats_for(self, trades: list[TradeResult]) -> dict:
        """Compute aggregate stats dict for a list of closed trades."""
        wins = [r for r in trades if r.outcome == "WIN"]
        losses = [r for r in trades if r.outcome == "LOSS"]
        be_trades = [r for r in trades if r.outcome == "BE"]
        stale_trades = [r for r in trades if r.outcome == "STALE"]
        scored_trades = [r for r in trades if r.outcome in ("WIN", "LOSS", "BE")]
        total = len(scored_trades)
        win_rate = round(len(wins) / total * 100, 2) if total else 0.0
        protected_win_rate = round((len(wins) + len(be_trades)) / total * 100, 2) if total else 0.0
        avg_pnl = round(sum(r.pnl_pct for r in scored_trades) / total, 4) if total else 0.0
        pnl_values = [r.pnl_pct for r in scored_trades]
        best_trade = round(max(pnl_values), 4) if pnl_values else 0.0
        worst_trade = round(min(pnl_values), 4) if pnl_values else 0.0
        # Sharpe for this subset
        sharpe = 0.0
        if len(scored_trades) >= 3:
            mean_r = avg_pnl
            variance = sum((r.pnl_pct - mean_r) ** 2 for r in scored_trades) / (len(scored_trades) - 1)
            std_r = math.sqrt(variance)
            if std_r > 0:
                sharpe = round(mean_r / std_r, 4)
        return {
            "total_signals": total,
            "wins": len(wins),
            "losses": len(losses),
            "be_count": len(be_trades),
            "stale_count": len(stale_trades),
            "win_rate": win_rate,
            "protected_win_rate": protected_win_rate,
            "avg_pnl": avg_pnl,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "sharpe": sharpe,
        }

    def per_channel_stats(self) -> dict[str, dict]:
        """
        Return per-channel performance statistics.

        Returns a dict keyed by channel tier containing win_rate, total_signals,
        wins, losses, avg_pnl, best_trade, worst_trade, and sharpe.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE", "STALE")]
        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"]
        result: dict[str, dict] = {}
        for tier in tiers:
            subset = [r for r in closed if r.channel_tier == tier]
            result[tier] = self._channel_stats_for(subset)
        return result

    def per_session_stats(self) -> dict[str, dict]:
        """
        Return per-session performance statistics.

        Returns a dict keyed by session (LONDON, NYC, ASIA, OVERLAP, UNKNOWN)
        containing win_rate, total_signals, wins, losses, avg_pnl, best_trade,
        worst_trade, and sharpe.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE", "STALE")]
        sessions = ["LONDON", "NYC", "ASIA", "OVERLAP", "UNKNOWN"]
        result: dict[str, dict] = {}
        for session in sessions:
            subset = [r for r in closed if r.session == session]
            result[session] = self._channel_stats_for(subset)
        return result

    def format_per_channel_report(self, days: int = 30) -> str:
        """
        Generate a Telegram-formatted per-channel performance report.

        Parameters
        ----------
        days:
            Rolling window in days. Defaults to 30.
        """
        cutoff = time.time() - days * 86400
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE")
            and r.closed_at is not None
            and r.closed_at >= cutoff
        ]

        channel_configs = [
            ("CH1_HARD", "🔴 CH1 Hard Scalp"),
            ("CH2_MEDIUM", "🟡 CH2 Medium"),
            ("CH3_EASY", "🔵 CH3 Easy Breakout"),
            ("CH4_SPOT", "💰 CH4 Spot"),
        ]

        lines = [f"📊 PERFORMANCE BY CHANNEL ({days}d)", ""]
        for tier_key, label in channel_configs:
            subset = [r for r in closed if r.channel_tier == tier_key]
            stats = self._channel_stats_for(subset)
            lines.append(f"{label}:")
            lines.append(
                f"  Win Rate: {stats['win_rate']:.1f}% ({stats['total_signals']} signals)"
            )
            lines.append(
                f"  Avg PnL: {stats['avg_pnl']:+.2f}% | Sharpe: {stats['sharpe']:.2f}"
            )
            lines.append("")

        return "\n".join(lines).rstrip()

    def per_channel_rolling_stats(self, days: int = 7) -> dict[str, dict]:
        """
        Return per-channel rolling performance statistics filtered by closed_at.

        Parameters
        ----------
        days:
            Rolling lookback window in days.

        Returns
        -------
        dict
            Keyed by channel tier, each value contains rolling win_rate,
            profit_factor, avg_pnl, and total_signals for the window.
        """
        cutoff = time.time() - days * 86400
        closed = [
            r for r in self._results
            if r.outcome in ("WIN", "LOSS", "BE", "STALE")
            and r.closed_at is not None
            and r.closed_at >= cutoff
        ]
        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"]
        result: dict[str, dict] = {}
        for tier in tiers:
            subset = [r for r in closed if r.channel_tier == tier]
            stats = self._channel_stats_for(subset)
            # Add rolling profit factor
            wins_pnl = sum(r.pnl_pct for r in subset if r.pnl_pct > 0 and r.outcome in ("WIN", "LOSS", "BE"))
            loss_pnl = abs(sum(r.pnl_pct for r in subset if r.pnl_pct < 0 and r.outcome in ("WIN", "LOSS", "BE")))
            stats["profit_factor"] = round(wins_pnl / loss_pnl, 4) if loss_pnl > 0 else 0.0
            result[tier] = stats
        return result

    def per_channel_profit_factor(self) -> dict[str, float]:
        """
        Return gross profit / gross loss (Profit Factor) per channel tier.

        Returns 0.0 for channels with no losing trades.
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"]
        result: dict[str, float] = {}
        for tier in tiers:
            subset = [r for r in closed if r.channel_tier == tier]
            gross_profit = sum(r.pnl_pct for r in subset if r.pnl_pct > 0)
            gross_loss = abs(sum(r.pnl_pct for r in subset if r.pnl_pct < 0))
            result[tier] = round(gross_profit / gross_loss, 4) if gross_loss > 0 else 0.0
        return result

    def per_channel_tp_distribution(self) -> dict[str, dict]:
        """
        Return TP/SL/BE/STALE outcome distribution per channel tier.

        Returns a dict mapping each channel tier to counts of TP1, TP2, TP3, SL, BE, STALE
        outcomes. WIN/LOSS outcomes in the dashboard are mapped from original close reasons,
        so this method uses the raw outcome field stored in TradeResult.
        """
        all_closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE", "STALE")]
        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"]
        result: dict[str, dict] = {}
        for tier in tiers:
            subset = [r for r in all_closed if r.channel_tier == tier]
            result[tier] = {
                "WIN": sum(1 for r in subset if r.outcome == "WIN"),
                "LOSS": sum(1 for r in subset if r.outcome == "LOSS"),
                "BE": sum(1 for r in subset if r.outcome == "BE"),
                "STALE": sum(1 for r in subset if r.outcome == "STALE"),
                "total": len(subset),
            }
        return result

    def per_channel_equity_curve(self) -> dict[str, list[float]]:
        """
        Return a separate equity curve (cumulative PnL) per channel tier.

        Returns a dict mapping each channel tier to a list of cumulative PnL
        values in chronological order. Excludes STALE trades (0 PnL, no price move).
        """
        closed = [r for r in self._results if r.outcome in ("WIN", "LOSS", "BE")]
        # Sort by closed_at for proper chronological order
        closed_sorted = sorted(
            (r for r in closed if r.closed_at is not None),
            key=lambda r: r.closed_at,  # type: ignore[arg-type]
        )
        tiers = ["CH1_HARD", "CH2_MEDIUM", "CH3_EASY", "CH4_SPOT", "AGGREGATE"]
        result: dict[str, list[float]] = {}
        for tier in tiers:
            subset = [r for r in closed_sorted if r.channel_tier == tier]
            curve: list[float] = []
            cumulative = 0.0
            for r in subset:
                cumulative += r.pnl_pct
                curve.append(round(cumulative, 4))
            result[tier] = curve
        return result

    def check_drawdown_halt(self, threshold_pct: float = -15.0) -> bool:
        """
        Return True if cumulative PnL has fallen far enough below its peak to
        trigger a drawdown halt.

        When this returns True, the caller should suspend signal generation
        until the drawdown recovers above the threshold.

        Parameters
        ----------
        threshold_pct:
            Drawdown percentage at which trading is halted.  Defaults to
            ``-15.0`` (i.e. a 15 % decline from the equity-curve peak).

        Returns
        -------
        bool
            ``True`` when the current drawdown is at or below *threshold_pct*.
        """
        equity_curve = self.equity_curve()
        if not equity_curve:
            return False
        peak = max(equity_curve)
        current = equity_curve[-1]
        if peak == 0.0:
            return False
        drawdown_pct = (current - peak) / abs(peak) * 100
        return drawdown_pct <= threshold_pct
