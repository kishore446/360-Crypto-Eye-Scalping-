"""
Auto-Close Monitor
==================
Background task that monitors all active signals for TP/SL price hits and
stale expiry, then automatically records outcomes and broadcasts close summaries.

This module runs as an asyncio background task started in ``build_application()``.

Sequence of events for each monitoring tick:
  1. Pull current prices from ``MarketDataStore``.
  2. For every open ``ActiveSignal`` check whether TP1/TP2/TP3 or SL has been hit.
  3. If a hit is detected, close the signal, record the result in ``Dashboard``,
     feed the outcome to ``CooldownManager``, and broadcast a close summary.
  4. Stale signals (open > ``STALE_SIGNAL_HOURS``) are closed with outcome STALE.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from bot.signal_engine import Side

if TYPE_CHECKING:
    from bot.dashboard import Dashboard
    from bot.loss_streak_cooldown import CooldownManager
    from bot.risk_manager import ActiveSignal, RiskManager
    from bot.signal_router import SignalRouter
    from bot.ws_manager import MarketDataStore

logger = logging.getLogger(__name__)

__all__ = ["AutoCloseMonitor", "CloseResult"]


@dataclass
class CloseResult:
    """Encapsulates the outcome of an auto-closed signal."""

    signal_id: str
    symbol: str
    side: str                 # "LONG" | "SHORT"
    outcome: str              # "TP1" | "TP2" | "TP3" | "SL" | "STALE"
    entry_price: float
    exit_price: float
    pnl_pct: float            # % PnL (positive = profit)
    opened_at: float          # Unix timestamp
    closed_at: float          # Unix timestamp
    channel_tier: str = "AGGREGATE"
    session: str = "UNKNOWN"


def _duration_str(seconds: float) -> str:
    """Format duration in seconds to a human-readable string like '1h 42m'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


class AutoCloseMonitor:
    """
    Monitors active signals for TP/SL hits and stale expiry.

    Parameters
    ----------
    signal_tracker:
        The bot's ``RiskManager`` instance used to access and close active signals.
    dashboard:
        ``Dashboard`` instance for recording trade results.
    cooldown_manager:
        ``CooldownManager`` for recording outcomes and triggering loss-streak logic.
    market_data_store:
        ``MarketDataStore`` supplying live prices.
    signal_router:
        ``SignalRouter`` used to broadcast close summaries to the right channel.
    poll_interval:
        Seconds between monitoring ticks. Default 30.
    """

    def __init__(
        self,
        signal_tracker: "RiskManager",
        dashboard: "Dashboard",
        cooldown_manager: "CooldownManager",
        market_data_store: "MarketDataStore",
        signal_router: "SignalRouter",
        poll_interval: float = 30.0,
    ) -> None:
        self._risk_manager = signal_tracker
        self._dashboard = dashboard
        self._cooldown = cooldown_manager
        self._market_data = market_data_store
        self._router = signal_router
        self._poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the monitoring loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info("AutoCloseMonitor started (poll interval: %ss).", self._poll_interval)

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AutoCloseMonitor stopped.")

    # ── main loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Continuously poll for TP/SL hits at ``_poll_interval`` second intervals."""
        while self._running:
            try:
                await self._check_signals()
            except Exception as exc:
                logger.exception("AutoCloseMonitor tick error: %s", exc)
            await asyncio.sleep(self._poll_interval)

    async def _check_signals(self) -> None:
        """Main monitoring tick — check all open signals against current prices."""
        for signal in list(self._risk_manager.active_signals):
            symbol = signal.result.symbol
            current_price = self._market_data.get_price(symbol)

            # ── stale check ──────────────────────────────────────────────────
            if signal.is_stale():
                close_result = self._build_stale_result(signal)
                await self._process_close(signal, close_result)
                continue

            if current_price is None:
                continue

            # ── TP/SL check ──────────────────────────────────────────────────
            close_result = self._check_tp_sl_hit(signal, current_price)
            if close_result is not None:
                await self._process_close(signal, close_result)
                continue

            # ── Invalidation check (after TP/SL; non-closing alert) ───────────
            await self._check_invalidation(signal, current_price)

    # ── invalidation check ────────────────────────────────────────────────────

    async def _check_invalidation(self, signal: "ActiveSignal", current_price: float) -> None:
        """Check for signal invalidation and broadcast an alert if detected."""
        try:
            from config import INVALIDATION_CHECK_ENABLED
            if not INVALIDATION_CHECK_ENABLED:
                return
        except Exception:
            pass

        try:
            from bot.invalidation_detector import InvalidationDetector, format_invalidation_alert
            from bot.signal_engine import CandleData
        except Exception:
            return

        candles_5m_raw = self._market_data.get_candles(signal.result.symbol, "5m")
        candles_4h_raw = self._market_data.get_candles(signal.result.symbol, "4h")

        def _to_candles(rows: list) -> "list[CandleData]":
            return [
                CandleData(open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows
            ]

        candles_5m = _to_candles(candles_5m_raw)
        candles_4h = _to_candles(candles_4h_raw)

        # Retrieve current regime from BotState (best-effort)
        try:
            from bot.state import BotState
            market_regime = BotState().market_regime
        except Exception:
            market_regime = "UNKNOWN"

        detector = InvalidationDetector()
        reason = detector.check_invalidation(signal, current_price, candles_5m, candles_4h, market_regime)
        if reason is None:
            return

        alert = format_invalidation_alert(signal, reason, current_price)
        from bot.signal_router import ChannelTier
        channel_id = signal.origin_channel or self._router.get_channel_id(ChannelTier.INSIGHTS)
        if not channel_id:
            return
        try:
            from telegram import Bot

            from config import TELEGRAM_BOT_TOKEN
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=channel_id, text=alert)
        except Exception as exc:
            logger.warning("Invalidation alert send failed for %s: %s", signal.result.symbol, exc)

    # ── detection helpers ─────────────────────────────────────────────────────

    def _check_tp_sl_hit(self, signal: "ActiveSignal", current_price: float) -> Optional[CloseResult]:
        """
        Check whether the current price has hit any TP or SL level.

        Returns a ``CloseResult`` if a level was hit, else ``None``.
        """
        r = signal.result
        now = time.time()
        entry = signal.entry_mid

        if r.side == Side.LONG:
            if current_price >= r.tp3:
                pnl = (r.tp3 - entry) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="LONG",
                    outcome="TP3", entry_price=entry, exit_price=r.tp3,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            if current_price >= r.tp2:
                pnl = (r.tp2 - entry) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="LONG",
                    outcome="TP2", entry_price=entry, exit_price=r.tp2,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            if current_price >= r.tp1:
                pnl = (r.tp1 - entry) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="LONG",
                    outcome="TP1", entry_price=entry, exit_price=r.tp1,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            sl = signal.result.stop_loss if not signal.be_triggered else entry
            if current_price <= sl:
                pnl = (current_price - entry) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="LONG",
                    outcome="SL", entry_price=entry, exit_price=current_price,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
        else:  # SHORT
            if current_price <= r.tp3:
                pnl = (entry - r.tp3) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="SHORT",
                    outcome="TP3", entry_price=entry, exit_price=r.tp3,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            if current_price <= r.tp2:
                pnl = (entry - r.tp2) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="SHORT",
                    outcome="TP2", entry_price=entry, exit_price=r.tp2,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            if current_price <= r.tp1:
                pnl = (entry - r.tp1) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="SHORT",
                    outcome="TP1", entry_price=entry, exit_price=r.tp1,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
            sl = signal.result.stop_loss if not signal.be_triggered else entry
            if current_price >= sl:
                pnl = (entry - current_price) / entry * 100
                return CloseResult(
                    signal_id=r.signal_id, symbol=r.symbol, side="SHORT",
                    outcome="SL", entry_price=entry, exit_price=current_price,
                    pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                )
        return None

    def _build_stale_result(self, signal: "ActiveSignal") -> CloseResult:
        """Build a stale-close result with 0 PnL."""
        entry = signal.entry_mid
        now = time.time()
        return CloseResult(
            signal_id=signal.result.signal_id,
            symbol=signal.result.symbol,
            side=signal.result.side.value,
            outcome="STALE",
            entry_price=entry,
            exit_price=entry,
            pnl_pct=0.0,
            opened_at=signal.opened_at,
            closed_at=now,
        )

    # ── close processing ──────────────────────────────────────────────────────

    async def _process_close(self, signal: "ActiveSignal", close_result: CloseResult) -> None:
        """Close signal, record result, update cooldown, and broadcast."""
        self._risk_manager.close_signal(signal.result.symbol, reason=close_result.outcome.lower())

        # Map outcome to dashboard WIN/LOSS/BE
        if close_result.outcome.startswith("TP"):
            dashboard_outcome = "WIN"
        elif close_result.outcome == "SL":
            dashboard_outcome = "LOSS"
        else:
            dashboard_outcome = "BE"  # STALE treated as break-even

        from bot.dashboard import TradeResult
        trade_result = TradeResult(
            symbol=close_result.symbol,
            side=close_result.side,
            entry_price=close_result.entry_price,
            exit_price=close_result.exit_price,
            stop_loss=signal.result.stop_loss,
            tp1=signal.result.tp1,
            tp2=signal.result.tp2,
            tp3=signal.result.tp3,
            opened_at=close_result.opened_at,
            closed_at=close_result.closed_at,
            outcome=dashboard_outcome,
            pnl_pct=close_result.pnl_pct,
            timeframe="5m",
            channel_tier=close_result.channel_tier,
            session=close_result.session,
        )
        self._dashboard.record_result(trade_result)

        # Feed outcome to cooldown manager
        self._cooldown.record_outcome(dashboard_outcome)

        # Broadcast close summary
        await self._broadcast_close(close_result)

    # ── broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast_close(self, close_result: CloseResult) -> None:
        """Format and broadcast a signal close summary to the insights channel."""
        from bot.signal_router import ChannelTier
        message = self._format_close_message(close_result)
        channel_id = self._router.get_channel_id(ChannelTier.INSIGHTS)
        if not channel_id:
            logger.debug("No CH5 insights channel configured; skipping close broadcast.")
            return
        try:
            from telegram import Bot

            from config import TELEGRAM_BOT_TOKEN
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=channel_id, text=message, parse_mode="Markdown")
        except Exception as exc:
            logger.warning("Failed to broadcast close summary for %s: %s", close_result.symbol, exc)

    @staticmethod
    def _format_close_message(r: CloseResult) -> str:
        """Format a Telegram close summary message."""
        outcome_map = {
            "TP1": "✅ TP1 HIT",
            "TP2": "✅ TP2 HIT",
            "TP3": "✅ TP3 HIT (FULL)",
            "SL": "❌ SL HIT",
            "STALE": "⏰ STALE CLOSE",
        }
        outcome_label = outcome_map.get(r.outcome, r.outcome)
        pnl_sign = "+" if r.pnl_pct >= 0 else ""
        duration = _duration_str(r.closed_at - r.opened_at)
        tier_label = r.channel_tier.replace("_", " ")

        return (
            f"📋 *SIGNAL CLOSED — #{r.symbol}/USDT {r.side}*\n"
            f"Outcome: {outcome_label} | {pnl_sign}{r.pnl_pct:.2f}%\n"
            f"Entry: {r.entry_price:,.4f} → Exit: {r.exit_price:,.4f}\n"
            f"Duration: {duration}\n"
            f"Channel: {tier_label}"
        )
