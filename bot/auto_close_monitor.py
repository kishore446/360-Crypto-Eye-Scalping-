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

from bot.partial_position import PartialPosition
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
        poll_interval: float = 10.0,
        bot_state: "object | None" = None,
        telegram_bot: "object | None" = None,
    ) -> None:
        self._risk_manager = signal_tracker
        self._dashboard = dashboard
        self._cooldown = cooldown_manager
        self._market_data = market_data_store
        self._router = signal_router
        self._poll_interval = poll_interval
        self._bot_state = bot_state
        self._telegram_bot = telegram_bot  # Reuse bot instance (BUG #4 fix)
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._partial_positions: dict[str, PartialPosition] = {}
        self._alerted_invalidations: set[str] = set()
        self._tp_levels_hit: dict[str, set[str]] = {}  # BUG #3: sequential TP tracking

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
        self._alerted_invalidations.clear()
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
        # Load per-channel stale hours once per tick (avoids repeated imports)
        try:
            from config import (
                CH1_STALE_HOURS,
                CH2_STALE_HOURS,
                CH3_STALE_HOURS,
                CH4_STALE_HOURS,
            )
        except ImportError:
            CH1_STALE_HOURS = CH2_STALE_HOURS = CH3_STALE_HOURS = CH4_STALE_HOURS = None

        for signal in list(self._risk_manager.active_signals):
            symbol = signal.result.symbol
            current_price = self._market_data.get_price(symbol)

            # ── per-channel stale threshold ───────────────────────────────────
            tier = None
            if signal.origin_channel:
                tier_obj = self._router.get_tier_for_channel_id(signal.origin_channel)
                if tier_obj is not None:
                    tier = tier_obj.value.upper()
            stale_hours_override: Optional[int] = None
            if tier == "CH1_SCALPING":
                stale_hours_override = CH1_STALE_HOURS
            elif tier == "CH2_INTRADAY":
                stale_hours_override = CH2_STALE_HOURS
            elif tier == "CH3_TREND":
                stale_hours_override = CH3_STALE_HOURS
            elif tier == "CH4_SPOT":
                stale_hours_override = CH4_STALE_HOURS

            # ── stale check ──────────────────────────────────────────────────
            if signal.is_stale(stale_hours=stale_hours_override):
                # If we have a live price and it is within the entry zone, the
                # subscriber may already be in a position — skip the stale close
                # this tick and let the next natural tick decide.
                if current_price is not None and (
                    signal.result.entry_low <= current_price <= signal.result.entry_high
                ):
                    logger.info(
                        "[STALE_SKIP] %s %s: price %.4f is within entry zone "
                        "[%.4f - %.4f]; deferring stale close.",
                        symbol, signal.result.side.value, current_price,
                        signal.result.entry_low, signal.result.entry_high,
                    )
                    continue
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

            # ── Invalidation check ───────────────────────────────────────────
            await self._check_invalidation(signal, current_price)

    # ── detection helpers ─────────────────────────────────────────────────────

    async def _check_invalidation(self, signal: "ActiveSignal", current_price: float) -> None:
        """Run invalidation checks; broadcast alert if thesis breaks."""
        try:
            from config import INVALIDATION_CHECK_ENABLED
            if not INVALIDATION_CHECK_ENABLED:
                return
        except ImportError:
            pass

        sig_id = signal.result.signal_id
        if sig_id in self._alerted_invalidations:
            return  # already alerted, don't spam

        from bot.invalidation_detector import InvalidationDetector
        from bot.signal_engine import CandleData

        symbol = signal.result.symbol
        candles_5m_raw = self._market_data.get_candles(symbol, "5m")
        candles_4h_raw = self._market_data.get_candles(symbol, "4h")

        def _to_candle(candle_row: list) -> "CandleData":
            return CandleData(
                open=candle_row[1],
                high=candle_row[2],
                low=candle_row[3],
                close=candle_row[4],
                volume=candle_row[5] if len(candle_row) > 5 else 0.0,
            )

        candles_5m = [_to_candle(r) for r in candles_5m_raw]
        candles_4h = [_to_candle(r) for r in candles_4h_raw]
        market_regime = getattr(self._bot_state, "market_regime", "UNKNOWN") if self._bot_state else "UNKNOWN"

        detector = InvalidationDetector()
        reason = detector.check_invalidation(signal, current_price, candles_5m, candles_4h, market_regime)
        if reason:
            self._alerted_invalidations.add(sig_id)
            alert = detector.format_alert(signal, reason, current_price)
            # Route invalidation alert to the signal's origin channel (BUG #1 fix)
            origin = signal.origin_channel if signal.origin_channel else 0
            await self._broadcast_close_raw(alert, channel_id=origin)

    async def _broadcast_close_raw(self, message: str, channel_id: int = 0) -> None:
        """Broadcast a raw text message to the given channel (defaults to CH5 Insights)."""
        if not channel_id:
            from bot.signal_router import ChannelTier
            channel_id = self._router.get_channel_id(ChannelTier.INSIGHTS)
        if not channel_id:
            return
        try:
            if self._telegram_bot is not None:
                await self._telegram_bot.send_message(chat_id=channel_id, text=message)
            else:
                from telegram import Bot

                from config import TELEGRAM_BOT_TOKEN
                bot = Bot(token=TELEGRAM_BOT_TOKEN)
                await bot.send_message(chat_id=channel_id, text=message)
        except Exception as exc:
            logger.warning("Failed to broadcast invalidation alert: %s", exc)

    def _check_tp_sl_hit(self, signal: "ActiveSignal", current_price: float) -> Optional[CloseResult]:
        """
        Check whether the current price has hit any TP or SL level.

        Returns a ``CloseResult`` if a level was hit, else ``None``.
        Handles sequential TP tracking: if price gaps past TP1/TP2, the skipped
        levels are recorded first before the higher-level hit is returned.
        """
        r = signal.result
        now = time.time()
        entry = signal.entry_mid
        sig_id = r.signal_id

        # BUG #2 fix: derive channel_tier from signal.origin_channel
        channel_tier = "AGGREGATE"
        if signal.origin_channel:
            tier = self._router.get_tier_for_channel_id(signal.origin_channel)
            if tier is not None:
                channel_tier = tier.value.upper()

        # BUG #3: Ensure TP levels are tracked for sequential recording
        if sig_id not in self._tp_levels_hit:
            self._tp_levels_hit[sig_id] = set()
        tp_hit = self._tp_levels_hit[sig_id]

        def _make_result(outcome: str, exit_price: float, side: str, pnl: float) -> CloseResult:
            return CloseResult(
                signal_id=r.signal_id, symbol=r.symbol, side=side,
                outcome=outcome, entry_price=entry, exit_price=exit_price,
                pnl_pct=round(pnl, 4), opened_at=signal.opened_at, closed_at=now,
                channel_tier=channel_tier,
            )

        if r.side == Side.LONG:
            sl = signal.result.stop_loss if not signal.be_triggered else entry
            if current_price <= sl:
                return _make_result("SL", current_price, "LONG", (current_price - entry) / entry * 100)
            if current_price >= r.tp3:
                # BUG #2 fix: when price has gapped past TP3 in a single tick with no
                # prior TP hits, skip sequential TP1→TP2 recording and close the full
                # position at TP3 (the more conservative, lower price).  Sequential
                # partials only make sense when price crosses each level individually.
                #
                # TP1 and TP2 are added to tp_hit so that subsequent monitoring ticks
                # (if any) do not try to re-emit those levels — preventing false
                # duplicate partial-exit events after a gap close.
                if not tp_hit:
                    tp_hit.add("TP1")
                    tp_hit.add("TP2")
                    tp_hit.add("TP3")
                    return _make_result("TP3", r.tp3, "LONG", (r.tp3 - entry) / entry * 100)
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "LONG", (r.tp1 - entry) / entry * 100)
                if "TP2" not in tp_hit:
                    tp_hit.add("TP2")
                    return _make_result("TP2", r.tp2, "LONG", (r.tp2 - entry) / entry * 100)
                if "TP3" not in tp_hit:
                    tp_hit.add("TP3")
                    return _make_result("TP3", r.tp3, "LONG", (r.tp3 - entry) / entry * 100)
            if current_price >= r.tp2:
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "LONG", (r.tp1 - entry) / entry * 100)
                if "TP2" not in tp_hit:
                    tp_hit.add("TP2")
                    return _make_result("TP2", r.tp2, "LONG", (r.tp2 - entry) / entry * 100)
            if current_price >= r.tp1:
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "LONG", (r.tp1 - entry) / entry * 100)
        else:  # SHORT
            sl = signal.result.stop_loss if not signal.be_triggered else entry
            if current_price >= sl:
                return _make_result("SL", current_price, "SHORT", (entry - current_price) / entry * 100)
            if current_price <= r.tp3:
                # BUG #2 fix: same gap logic for SHORT — when price has gapped below TP3
                # with no prior TP hits, close the full position at TP3 (the more
                # conservative, higher price for a SHORT).  TP1 and TP2 are marked in
                # tp_hit to prevent duplicate partial-exit events on subsequent ticks.
                if not tp_hit:
                    tp_hit.add("TP1")
                    tp_hit.add("TP2")
                    tp_hit.add("TP3")
                    return _make_result("TP3", r.tp3, "SHORT", (entry - r.tp3) / entry * 100)
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "SHORT", (entry - r.tp1) / entry * 100)
                if "TP2" not in tp_hit:
                    tp_hit.add("TP2")
                    return _make_result("TP2", r.tp2, "SHORT", (entry - r.tp2) / entry * 100)
                if "TP3" not in tp_hit:
                    tp_hit.add("TP3")
                    return _make_result("TP3", r.tp3, "SHORT", (entry - r.tp3) / entry * 100)
            if current_price <= r.tp2:
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "SHORT", (entry - r.tp1) / entry * 100)
                if "TP2" not in tp_hit:
                    tp_hit.add("TP2")
                    return _make_result("TP2", r.tp2, "SHORT", (entry - r.tp2) / entry * 100)
            if current_price <= r.tp1:
                if "TP1" not in tp_hit:
                    tp_hit.add("TP1")
                    return _make_result("TP1", r.tp1, "SHORT", (entry - r.tp1) / entry * 100)
        return None

    def _build_stale_result(self, signal: "ActiveSignal") -> CloseResult:
        """Build a stale-close result with 0 PnL."""
        entry = signal.entry_mid
        now = time.time()
        # BUG #2 fix: derive channel_tier from signal.origin_channel
        channel_tier = "AGGREGATE"
        if signal.origin_channel:
            tier = self._router.get_tier_for_channel_id(signal.origin_channel)
            if tier is not None:
                channel_tier = tier.value.upper()
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
            channel_tier=channel_tier,
        )

    # ── close processing ──────────────────────────────────────────────────────

    async def _process_close(self, signal: "ActiveSignal", close_result: CloseResult) -> None:
        """
        Process a TP/SL/STALE close event.

        For TP1 and TP2 outcomes the signal is **not** fully closed — instead a
        partial WIN is recorded in the dashboard and the signal continues to be
        monitored.  On TP1 the SL is moved to break-even.  Only TP3, SL, and
        STALE outcomes trigger a full close.
        """
        sig_id = signal.result.signal_id
        outcome = close_result.outcome

        # ── Partial position tracking ─────────────────────────────────────────
        pp = self._partial_positions.get(sig_id)
        if pp is None:
            pp = PartialPosition(
                signal_id=sig_id,
                entry_price=close_result.entry_price,
                side=close_result.side,
            )
            self._partial_positions[sig_id] = pp

        pp.add_exit(
            level=outcome,
            exit_price=close_result.exit_price,
        )

        partial_exits_json = pp.to_json() if pp.has_exits() else ""
        composite_pnl = pp.composite_pnl() if pp.has_exits() else close_result.pnl_pct

        # ── Partial close: TP1 or TP2 — keep signal alive ────────────────────
        if outcome in ("TP1", "TP2"):
            if outcome == "TP1":
                # Move SL to break-even so the remaining position is risk-free.
                # trigger_be() also sets signal.result.stop_loss = entry_mid so
                # all downstream consumers (trailing SL job, next tick check)
                # see the updated floor immediately.
                signal.trigger_be()

            # Record partial WIN in dashboard
            from bot.dashboard import TradeResult
            partial_result = TradeResult(
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
                outcome="WIN",
                pnl_pct=close_result.pnl_pct,
                timeframe="5m",
                channel_tier=close_result.channel_tier,
                session=close_result.session,
                partial_exits=partial_exits_json,
                composite_pnl_pct=composite_pnl,
            )
            self._dashboard.record_result(partial_result)
            self._cooldown.record_outcome("WIN")

            # Broadcast partial-close summary; signal state is preserved
            await self._broadcast_close(close_result, signal=signal, partial_position=pp)
            return  # Signal stays in active_signals — monitoring continues

        # ── Full close: TP3, SL, or STALE ────────────────────────────────────
        self._partial_positions.pop(sig_id, None)
        self._tp_levels_hit.pop(sig_id, None)
        self._alerted_invalidations.discard(sig_id)

        self._risk_manager.close_signal(signal.result.symbol, reason=outcome.lower())

        # Map outcome to dashboard WIN/LOSS/BE/STALE.
        # When SL is hit but break-even was already triggered, the remaining
        # position closed at entry (0% PnL on that portion) — record as "BE"
        # so the win-rate excludes it from true losses.
        if outcome.startswith("TP"):
            dashboard_outcome = "WIN"
        elif outcome == "SL":
            dashboard_outcome = "BE" if signal.be_triggered else "LOSS"
        elif outcome == "STALE":
            dashboard_outcome = "STALE"
        else:
            dashboard_outcome = "BE"

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
            partial_exits=partial_exits_json,
            composite_pnl_pct=composite_pnl,
        )
        self._dashboard.record_result(trade_result)

        # Feed outcome to cooldown manager (STALE excluded from streak logic)
        if dashboard_outcome != "STALE":
            self._cooldown.record_outcome(dashboard_outcome)

        # Broadcast close summary — route to origin channel
        await self._broadcast_close(close_result, signal=signal, partial_position=pp)

    # ── broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast_close(
        self,
        close_result: CloseResult,
        signal: "ActiveSignal | None" = None,
        partial_position: Optional["PartialPosition"] = None,
    ) -> None:
        """Format and broadcast a signal close summary to the signal's origin channel."""
        message = self._format_close_message(close_result, partial_position=partial_position)
        # BUG #1 fix: route to origin channel, not always CH5 Insights
        if signal is not None and signal.origin_channel:
            channel_id = signal.origin_channel
        else:
            from bot.signal_router import ChannelTier
            channel_id = self._router.get_channel_id(ChannelTier.INSIGHTS)
        if not channel_id:
            logger.debug("No target channel configured; skipping close broadcast.")
            return
        try:
            if self._telegram_bot is not None:
                await self._telegram_bot.send_message(
                    chat_id=channel_id, text=message, parse_mode="HTML"
                )
            else:
                from telegram import Bot

                from config import TELEGRAM_BOT_TOKEN
                bot = Bot(token=TELEGRAM_BOT_TOKEN)
                await bot.send_message(chat_id=channel_id, text=message, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Failed to broadcast close summary for %s: %s", close_result.symbol, exc)

    @staticmethod
    def _format_close_message(r: CloseResult, partial_position: Optional["PartialPosition"] = None) -> str:
        """Format a Telegram close summary message, with multi-exit breakdown when available."""
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

        # Enhanced composite message when partial exits exist
        if partial_position is not None and partial_position.exit_count() >= 1:
            composite_pnl = partial_position.composite_pnl()
            composite_sign = "+" if composite_pnl >= 0 else ""
            exit_breakdown = partial_position.format_exit_breakdown(side=r.side)
            sep = "━" * 21
            return (
                f"📋 <b>SIGNAL CLOSED — {r.symbol}/USDT {r.side}</b>\n"
                f"{sep}\n"
                f"{exit_breakdown}\n"
                f"{sep}\n"
                f"Composite P&L: {composite_sign}{composite_pnl:.2f}% (weighted)\n"
                f"Time Held: {duration} | Channel: {tier_label}"
            )

        return (
            f"📋 <b>SIGNAL CLOSED — {r.symbol}/USDT {r.side}</b>\n"
            f"Outcome: {outcome_label} | {pnl_sign}{r.pnl_pct:.2f}%\n"
            f"Entry: {r.entry_price:,.4f} → Exit: {r.exit_price:,.4f}\n"
            f"Duration: {duration}\n"
            f"Channel: {tier_label}"
        )
