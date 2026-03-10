"""
Risk Manager
============
Implements all safety protocols from Section V of the master blueprint:

  1. Break-Even (BE) Trigger — move SL to entry when price hits 50 % of TP1.
  2. The "3-Pair" Cap — max 3 active signals on the same side.
  3. Stale Close — alert/close if entry zone is untouched for > 4 hours.
  4. Position-size calculator (/risk_calc command).
  5. Trailing Stop-Loss — tracks price extremes after BE trigger and closes
     signals when the trailing SL level is breached.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bot.signal_engine import Confidence, Side, SignalResult
from config import (
    BE_TRIGGER_FRACTION,
    DEFAULT_RISK_FRACTION,
    MAX_SAME_SIDE_SIGNALS,
    SIGNALS_FILE,
    STALE_SIGNAL_HOURS,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActiveSignal",
    "RiskManager",
    "TrailingStopConfig",
    "calculate_position_size",
]

# ── Trailing stop configuration ───────────────────────────────────────────────

try:
    from config import (
        TRAILING_SL_ATR_MULTIPLIER,
        TRAILING_SL_ENABLED,
        TRAILING_SL_STEP_PCT,
    )
except ImportError:
    TRAILING_SL_ENABLED: bool = True
    TRAILING_SL_ATR_MULTIPLIER: float = 1.5
    TRAILING_SL_STEP_PCT: float = 0.1


@dataclass
class TrailingStopConfig:
    """Configuration for the trailing stop-loss mechanism.

    Attributes
    ----------
    enabled:
        Whether trailing SL is active.
    atr_multiplier:
        Multiplier applied to the current ATR estimate to set the trailing
        distance from the running extreme.
    activation_after_be:
        When ``True`` the trailing SL only activates once break-even has been
        triggered; if ``False`` it activates immediately on signal open.
    trail_step_pct:
        Minimum price move (as a fraction of entry price) required before the
        trailing SL level is updated.  Prevents excessive micro-adjustments.
    """

    enabled: bool = True
    atr_multiplier: float = 1.5
    activation_after_be: bool = True
    trail_step_pct: float = 0.1  # minimum move before trail updates


@dataclass
class ActiveSignal:
    """Tracks a live signal from entry through to close."""

    result: SignalResult
    opened_at: float = field(default_factory=time.time)  # Unix timestamp
    be_triggered: bool = False
    closed: bool = False
    close_reason: Optional[str] = None
    origin_channel: int = 0  # Telegram channel ID where this signal was broadcast
    created_regime: str = "UNKNOWN"  # Market regime at signal creation

    # ── Trailing stop-loss state ──────────────────────────────────────────────
    trailing_sl_price: Optional[float] = None
    highest_since_entry: Optional[float] = None   # for LONG signals
    lowest_since_entry: Optional[float] = None    # for SHORT signals

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def entry_mid(self) -> float:
        return (self.result.entry_low + self.result.entry_high) / 2

    def is_stale(self, now: Optional[float] = None) -> bool:
        """Return True if the signal has been open longer than the stale threshold."""
        elapsed_hours = ((now or time.time()) - self.opened_at) / 3600
        return elapsed_hours >= STALE_SIGNAL_HOURS

    def should_trigger_be(self, current_price: float) -> bool:
        """Return True when current price has reached the BE trigger level."""
        if self.be_triggered or self.closed:
            return False
        distance_to_tp1 = abs(self.result.tp1 - self.entry_mid)
        trigger_price = (
            self.entry_mid + BE_TRIGGER_FRACTION * distance_to_tp1
            if self.result.side == Side.LONG
            else self.entry_mid - BE_TRIGGER_FRACTION * distance_to_tp1
        )
        if self.result.side == Side.LONG:
            return current_price >= trigger_price
        return current_price <= trigger_price

    def trigger_be(self) -> None:
        """Mark the break-even as triggered; SL is now at entry."""
        self.be_triggered = True

    def close(self, reason: str) -> None:
        self.closed = True
        self.close_reason = reason


class RiskManager:
    """
    Central registry of active signals with built-in safety enforcement.

    Dirty-tracking
    --------------
    ``_dirty_ids`` is a ``set[str]`` that records the ``signal_id`` of every
    signal that has been mutated since the last ``_save()`` call.  Only those
    signals are written to SQLite, avoiding a full-table re-insert on every
    price tick.

    Trailing Stop-Loss
    ------------------
    After break-even is triggered, ``update_prices()`` tracks the running
    price extreme (``highest_since_entry`` for LONG, ``lowest_since_entry``
    for SHORT) and recalculates ``trailing_sl_price`` each time the extreme
    advances by at least ``trail_step_pct`` of the entry price.  If the live
    price crosses the trailing SL the signal is closed with reason
    ``"trailing_sl"``.
    """

    def __init__(
        self,
        trailing_config: Optional[TrailingStopConfig] = None,
    ) -> None:
        self._signals: list[ActiveSignal] = []
        self._lock = threading.Lock()
        self._dirty_ids: set[str] = set()
        self._trailing_cfg = trailing_config or TrailingStopConfig(
            enabled=TRAILING_SL_ENABLED,
            atr_multiplier=TRAILING_SL_ATR_MULTIPLIER,
            trail_step_pct=TRAILING_SL_STEP_PCT,
        )
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _mark_dirty(self, sig: ActiveSignal) -> None:
        """Record that *sig* needs to be persisted on the next ``_save()`` call."""
        sid = sig.result.signal_id or f"sig_{int(sig.opened_at)}"
        self._dirty_ids.add(sid)

    def _save(self) -> None:
        """Persist only dirty (mutated) signals to SQLite.

        On the first call after a signal is *added* the full row is written via
        ``save_signal()`` (INSERT OR REPLACE).  Subsequent mutations only update
        the mutable columns via ``update_signal()`` to minimise I/O.
        """
        if not self._dirty_ids:
            return
        try:
            from bot.database import save_signal
            dirty = list(self._dirty_ids)
            for sig in self._signals:
                sid = sig.result.signal_id or f"sig_{int(sig.opened_at)}"
                if sid not in dirty:
                    continue
                signal_data = {
                    "id": sid,
                    "symbol": sig.result.symbol,
                    "side": sig.result.side.value,
                    "confidence": sig.result.confidence.value,
                    "entry_low": sig.result.entry_low,
                    "entry_high": sig.result.entry_high,
                    "tp1": sig.result.tp1,
                    "tp2": sig.result.tp2,
                    "tp3": sig.result.tp3,
                    "stop_loss": sig.result.stop_loss,
                    "structure_note": sig.result.structure_note,
                    "context_note": sig.result.context_note,
                    "leverage_min": sig.result.leverage_min,
                    "leverage_max": sig.result.leverage_max,
                    "opened_at": sig.opened_at,
                    "closed_at": None,
                    "be_triggered": sig.be_triggered,
                    "closed": sig.closed,
                    "close_reason": sig.close_reason,
                    "created_by": "risk_manager",
                    "confluence_gates_json": None,
                    "origin_channel": sig.origin_channel,
                    "confluence_score": sig.result.confluence_score,
                }
                save_signal(signal_data)
            self._dirty_ids.clear()
        except Exception as exc:
            logger.error("Failed to persist signals to SQLite: %s", exc)

    def _load(self) -> None:
        """Load ``_signals`` from SQLite database, with one-time JSON migration fallback."""
        # One-time migration: if JSON file exists, migrate it to SQLite first
        json_path = Path(SIGNALS_FILE)
        if json_path.exists():
            try:
                from bot.database import init_db, migrate_from_json
                init_db()
                migrate_from_json(str(json_path), "")  # empty string = skip dashboard migration
                logger.info("Migrated signals from JSON to SQLite: %s", json_path)
            except Exception as exc:
                logger.warning("JSON migration failed (%s); falling back to JSON load.", exc)
                self._load_from_json()
                return

        # Load from SQLite
        try:
            from bot.database import init_db, load_active_signals
            init_db()
            rows = load_active_signals()
            signals = []
            for row in rows:
                try:
                    result = SignalResult(
                        symbol=row["symbol"],
                        side=Side(row["side"]),
                        confidence=Confidence(row["confidence"]),
                        entry_low=float(row["entry_low"]),
                        entry_high=float(row["entry_high"]),
                        tp1=float(row["tp1"]),
                        tp2=float(row["tp2"]),
                        tp3=float(row["tp3"]),
                        stop_loss=float(row["stop_loss"]),
                        structure_note=row.get("structure_note") or "",
                        context_note=row.get("context_note") or "",
                        leverage_min=int(row.get("leverage_min") or 10),
                        leverage_max=int(row.get("leverage_max") or 20),
                        signal_id=row.get("id") or "",
                        confluence_score=int(row.get("confluence_score") or 0),
                    )
                    signals.append(
                        ActiveSignal(
                            result=result,
                            opened_at=float(row.get("opened_at") or time.time()),
                            be_triggered=bool(row.get("be_triggered") or False),
                            closed=bool(row.get("closed") or False),
                            close_reason=row.get("close_reason"),
                            origin_channel=int(row.get("origin_channel") or 0),
                            created_regime=row.get("created_regime") or "UNKNOWN",
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Skipping malformed signal row: %s", exc)
            self._signals = signals
        except Exception as exc:
            logger.warning(
                "Could not load signals from SQLite (%s); starting with empty list.", exc
            )
            self._signals = []

    def _load_from_json(self) -> None:
        """Legacy JSON load, used only as last-resort fallback during migration."""
        path = Path(SIGNALS_FILE)
        if not path.exists():
            self._signals = []
            return
        try:
            raw: list[dict] = json.loads(path.read_text(encoding="utf-8"))
            signals = []
            for d in raw:
                r = d["result"]
                result = SignalResult(
                    symbol=r["symbol"],
                    side=Side(r["side"]),
                    confidence=Confidence(r["confidence"]),
                    entry_low=r["entry_low"],
                    entry_high=r["entry_high"],
                    tp1=r["tp1"],
                    tp2=r["tp2"],
                    tp3=r["tp3"],
                    stop_loss=r["stop_loss"],
                    structure_note=r["structure_note"],
                    context_note=r["context_note"],
                    leverage_min=r["leverage_min"],
                    leverage_max=r["leverage_max"],
                    signal_id=r.get("signal_id", ""),
                    confluence_score=r.get("confluence_score", 0),
                )
                signals.append(
                    ActiveSignal(
                        result=result,
                        opened_at=d["opened_at"],
                        be_triggered=d["be_triggered"],
                        closed=d["closed"],
                        close_reason=d.get("close_reason"),
                        origin_channel=d.get("origin_channel", 0),
                        created_regime=d.get("created_regime", "UNKNOWN"),
                    )
                )
            self._signals = signals
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not load signals from %s (%s); starting with empty list.",
                SIGNALS_FILE, exc,
            )
            self._signals = []

    def save(self) -> None:
        """Public alias for ``_save`` — persist all dirty signals to disk.

        Marks *all* signals as dirty before calling ``_save()`` so a forced
        full-flush is possible (e.g. at shutdown).
        """
        with self._lock:
            for sig in self._signals:
                self._mark_dirty(sig)
            self._save()

    # ── public API ────────────────────────────────────────────────────────────

    def dynamic_risk_fraction(self, confidence: str, cooldown_manager: "object") -> float:
        """
        Return the dynamic risk fraction based on signal confidence and cooldown state.

        Risk table
        ----------
        Confidence  Normal Risk   Cooldown Risk (×0.5)
        HIGH        1.5% (0.015)  0.75% (0.0075)
        MEDIUM      1.0% (0.01)   0.50% (0.005)
        LOW         0.5% (0.005)  SUPPRESSED (0.0)

        Parameters
        ----------
        confidence:
            Confidence level string — "High", "MEDIUM", "LOW" (case-insensitive).
        cooldown_manager:
            A ``CooldownManager`` instance exposing ``is_cooldown_active()``.

        Returns
        -------
        float
            Risk fraction (0.0 means the signal is suppressed).
        """
        in_cooldown = cooldown_manager.is_cooldown_active() if cooldown_manager is not None else False
        conf_upper = confidence.upper()
        if conf_upper == "HIGH":
            return 0.0075 if in_cooldown else 0.015
        if conf_upper == "MEDIUM":
            return 0.005 if in_cooldown else 0.01
        # LOW confidence
        if in_cooldown:
            return 0.0  # suppressed
        return 0.005

    def can_open_signal(self, side: Side) -> bool:
        """
        Return True only when the "3-Pair" cap allows a new signal on *side*.
        """
        with self._lock:
            count = sum(
                1
                for s in self._signals
                if not s.closed and s.result.side == side
            )
        return count < MAX_SAME_SIDE_SIGNALS

    def add_signal(self, result: SignalResult, origin_channel: int = 0, created_regime: str = "UNKNOWN") -> ActiveSignal:
        """
        Register a new active signal.

        Parameters
        ----------
        result:
            The generated signal result.
        origin_channel:
            Telegram channel ID where this signal will be broadcast.
            Used by lifecycle jobs (trailing SL, stale-close) to send
            updates to the correct channel.
        created_regime:
            Market regime string at the time of signal creation.

        Raises
        ------
        RuntimeError
            If the 3-Pair Cap would be violated.
        """
        if not self.can_open_signal(result.side):
            raise RuntimeError(
                f"3-Pair Cap reached: already {MAX_SAME_SIDE_SIGNALS} active "
                f"{result.side.value} signals."
            )
        active = ActiveSignal(result=result, origin_channel=origin_channel, created_regime=created_regime)
        with self._lock:
            self._signals.append(active)
            self._mark_dirty(active)
            self._save()
        return active

    def _update_trailing_sl(
        self,
        signal: ActiveSignal,
        price: float,
        atr: Optional[float] = None,
    ) -> Optional[str]:
        """Update the trailing stop-loss for *signal* given the current *price*.

        Parameters
        ----------
        signal:
            The active signal to update.
        price:
            The current market price.
        atr:
            Optional ATR value used to set the trailing distance.  When
            ``None`` a simple percentage-based trail is used instead
            (``trail_step_pct * entry_price``).

        Returns
        -------
        str | None
            A broadcast message when the trailing SL is crossed (signal is
            closed), or ``None`` otherwise.
        """
        cfg = self._trailing_cfg
        if not cfg.enabled:
            return None
        if cfg.activation_after_be and not signal.be_triggered:
            return None

        sym = signal.result.symbol
        side = signal.result.side
        entry = signal.entry_mid
        trail_distance = (atr * cfg.atr_multiplier) if atr is not None else (cfg.trail_step_pct * entry)

        if side == Side.LONG:
            # Initialise the high-water mark and set an initial trailing SL
            if signal.highest_since_entry is None:
                signal.highest_since_entry = price
                signal.trailing_sl_price = signal.highest_since_entry - trail_distance
            # Advance the high-water mark
            if price > signal.highest_since_entry:
                advance = price - signal.highest_since_entry
                if advance >= cfg.trail_step_pct * entry:
                    signal.highest_since_entry = price
                    signal.trailing_sl_price = signal.highest_since_entry - trail_distance
            # Check for breach
            trail = signal.trailing_sl_price
            if trail is not None and price <= trail:
                signal.close("trailing_sl")
                return (
                    f"🔴 #{sym}/USDT LONG closed — trailing SL hit at {trail:.4f} "
                    f"(high was {signal.highest_since_entry:.4f})."
                )
        else:  # SHORT
            # Initialise the low-water mark and set an initial trailing SL
            if signal.lowest_since_entry is None:
                signal.lowest_since_entry = price
                signal.trailing_sl_price = signal.lowest_since_entry + trail_distance
            # Advance the low-water mark
            if price < signal.lowest_since_entry:
                advance = signal.lowest_since_entry - price
                if advance >= cfg.trail_step_pct * entry:
                    signal.lowest_since_entry = price
                    signal.trailing_sl_price = signal.lowest_since_entry + trail_distance
            # Check for breach
            trail = signal.trailing_sl_price
            if trail is not None and price >= trail:
                signal.close("trailing_sl")
                return (
                    f"🔴 #{sym}/USDT SHORT closed — trailing SL hit at {trail:.4f} "
                    f"(low was {signal.lowest_since_entry:.4f})."
                )
        return None

    def update_prices(self, prices: dict[str, float], atrs: Optional[dict[str, float]] = None) -> list[str]:
        """
        Feed the latest prices into the risk manager.

        Parameters
        ----------
        prices:
            Mapping of base symbol (e.g. "BTC") to current price.
        atrs:
            Optional mapping of base symbol to current ATR value.  When
            provided the trailing SL uses ATR-based distances; otherwise a
            percentage fallback is used.

        Returns a list of human-readable broadcast messages for any events
        that were triggered (BE, trailing SL close, stale-close, etc.).
        """
        messages: list[str] = []
        now = time.time()

        with self._lock:
            for signal in self._signals:
                if signal.closed:
                    continue
                sym = signal.result.symbol
                price = prices.get(sym)

                # ── stale check ──────────────────────────────────────────────────
                if signal.is_stale(now):
                    signal.close("stale")
                    self._mark_dirty(signal)
                    messages.append(
                        f"⚠️ #{sym}/USDT {signal.result.side.value} signal CLOSED "
                        f"(stale — no activity for >{STALE_SIGNAL_HOURS}h)."
                    )
                    continue

                if price is None:
                    continue

                # ── BE trigger ───────────────────────────────────────────────────
                if signal.should_trigger_be(price):
                    signal.trigger_be()
                    self._mark_dirty(signal)
                    messages.append(
                        f"🔒 #{sym}/USDT {signal.result.side.value}: "
                        f"Move SL to Entry {signal.entry_mid:.4f} (Risk-Free Mode ON)."
                    )

                # ── Trailing SL ──────────────────────────────────────────────────
                atr = (atrs or {}).get(sym)
                trail_msg = self._update_trailing_sl(signal, price, atr)
                if trail_msg:
                    self._mark_dirty(signal)
                    messages.append(trail_msg)

            self._save()

        return messages

    def close_signal(self, symbol: str, reason: str = "manual") -> bool:
        """Close the first open signal matching *symbol*. Returns True on success."""
        with self._lock:
            for signal in self._signals:
                if not signal.closed and signal.result.symbol == symbol:
                    signal.close(reason)
                    self._mark_dirty(signal)
                    self._save()
                    return True
        return False

    @property
    def active_signals(self) -> list[ActiveSignal]:
        """Return all signals that have not yet been closed."""
        with self._lock:
            return [s for s in self._signals if not s.closed]

    @property
    def all_signals(self) -> list[ActiveSignal]:
        with self._lock:
            return list(self._signals)


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    risk_fraction: float = DEFAULT_RISK_FRACTION,
) -> dict[str, float]:
    """
    Calculate the exact position size for a given trade setup.

    Parameters
    ----------
    account_balance:
        Total account balance in USDT.
    entry_price:
        Planned entry price.
    stop_loss_price:
        Structural stop-loss price.
    risk_fraction:
        Fraction of account to risk (default 1 %).

    Returns
    -------
    Dictionary with keys: risk_amount, sl_distance_pct, position_size_usdt,
    position_size_units.
    """
    if entry_price <= 0 or stop_loss_price <= 0:
        raise ValueError("Prices must be positive.")
    if entry_price == stop_loss_price:
        raise ValueError("Entry price and stop-loss price must differ.")

    risk_amount = account_balance * risk_fraction
    sl_distance = abs(entry_price - stop_loss_price)
    sl_distance_pct = sl_distance / entry_price

    # Position size in USDT (margin) such that the SL hit = risk_amount
    position_size_usdt = risk_amount / sl_distance_pct
    position_size_units = position_size_usdt / entry_price

    return {
        "risk_amount": round(risk_amount, 4),
        "sl_distance_pct": round(sl_distance_pct * 100, 4),
        "position_size_usdt": round(position_size_usdt, 4),
        "position_size_units": round(position_size_units, 6),
    }
