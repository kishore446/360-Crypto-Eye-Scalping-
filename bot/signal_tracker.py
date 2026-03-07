"""
Signal Tracker
==============
Real-time signal lifecycle tracking with auto-update broadcasts.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["SignalTracker"]


class SignalTracker:
    """
    Tracks signal lifecycle events: TP1/TP2/TP3 hits, SL hits, BE triggers,
    and trailing stop-loss updates after TP2.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def check_signal(self, signal, current_price: float) -> list[str]:
        """
        Check a signal against current price and return broadcast messages for any newly hit levels.

        After TP2 is reached, a trailing SL is maintained using ATR if ATR data is available.
        The effective trailing SL is updated whenever price makes a new extreme in the trade direction.
        """
        sig_id = signal.result.signal_id
        messages: list[str] = []

        with self._lock:
            if sig_id not in self._state:
                self._state[sig_id] = {
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "tp3_hit": False,
                    "sl_hit": False,
                    "be_triggered": False,
                    "trailing_stop_loss": None,        # trailing SL price level (active after TP2)
                    "trailing_extreme_price": None,   # best price seen since TP2 hit
                }
            state = self._state[sig_id]

        side = signal.result.side
        from bot.signal_engine import Side

        risk_distance = abs(signal.entry_mid - signal.result.stop_loss)
        safe_risk = risk_distance if risk_distance > 0 else 1.0  # guard against division by zero

        if side == Side.LONG:
            if not state["tp1_hit"] and current_price >= signal.result.tp1:
                state["tp1_hit"] = True
                state["be_triggered"] = True
                r = abs(signal.result.tp1 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP1 HIT at {signal.result.tp1:.4f} "
                    f"— SL moved to BE. +{r:.1f}R"
                )
            elif state["tp1_hit"] and not state["tp2_hit"] and current_price >= signal.result.tp2:
                state["tp2_hit"] = True
                state["trailing_extreme_price"] = current_price
                state["trailing_stop_loss"] = self._compute_trail_sl(signal, current_price)
                r = abs(signal.result.tp2 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP2 HIT at {signal.result.tp2:.4f} "
                    f"— Trailing SL active. +{r:.1f}R"
                )
                if state["trailing_stop_loss"] is not None:
                    messages.append(
                        f"📍 #{signal.result.symbol}/USDT Trailing SL set at "
                        f"{state['trailing_stop_loss']:.4f}"
                    )
            elif state["tp2_hit"] and not state["tp3_hit"] and current_price >= signal.result.tp3:
                state["tp3_hit"] = True
                r = abs(signal.result.tp3 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP3 HIT at {signal.result.tp3:.4f} "
                    f"— Full target reached. +{r:.1f}R"
                )
            elif state["tp2_hit"] and not state["tp3_hit"]:
                # Update trailing SL if price has moved in our favour
                trail_msg = self._update_trail_sl(signal, current_price, state, side)
                if trail_msg:
                    messages.append(trail_msg)

            if not state["sl_hit"] and not state["tp3_hit"]:
                effective_sl = self._effective_sl(signal, state)
                if current_price <= effective_sl:
                    state["sl_hit"] = True
                    messages.append(
                        f"❌ #{signal.result.symbol}/USDT SL HIT at {effective_sl:.4f} "
                        f"— -1.0R (1% account loss)"
                    )
        else:
            if not state["tp1_hit"] and current_price <= signal.result.tp1:
                state["tp1_hit"] = True
                state["be_triggered"] = True
                r = abs(signal.result.tp1 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP1 HIT at {signal.result.tp1:.4f} "
                    f"— SL moved to BE. +{r:.1f}R"
                )
            elif state["tp1_hit"] and not state["tp2_hit"] and current_price <= signal.result.tp2:
                state["tp2_hit"] = True
                state["trailing_extreme_price"] = current_price
                state["trailing_stop_loss"] = self._compute_trail_sl(signal, current_price)
                r = abs(signal.result.tp2 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP2 HIT at {signal.result.tp2:.4f} "
                    f"— Trailing SL active. +{r:.1f}R"
                )
                if state["trailing_stop_loss"] is not None:
                    messages.append(
                        f"📍 #{signal.result.symbol}/USDT Trailing SL set at "
                        f"{state['trailing_stop_loss']:.4f}"
                    )
            elif state["tp2_hit"] and not state["tp3_hit"] and current_price <= signal.result.tp3:
                state["tp3_hit"] = True
                r = abs(signal.result.tp3 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP3 HIT at {signal.result.tp3:.4f} "
                    f"— Full target reached. +{r:.1f}R"
                )
            elif state["tp2_hit"] and not state["tp3_hit"]:
                trail_msg = self._update_trail_sl(signal, current_price, state, side)
                if trail_msg:
                    messages.append(trail_msg)

            if not state["sl_hit"] and not state["tp3_hit"]:
                effective_sl = self._effective_sl(signal, state)
                if current_price >= effective_sl:
                    state["sl_hit"] = True
                    messages.append(
                        f"❌ #{signal.result.symbol}/USDT SL HIT at {effective_sl:.4f} "
                        f"— -1.0R (1% account loss)"
                    )

        return messages

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_trail_sl(signal, current_price: float) -> Optional[float]:
        """
        Compute the initial trailing SL level using ATR.

        Uses 1×ATR as the trail distance.  Falls back to 1% of current price
        when ATR is unavailable.
        """
        try:
            from bot.signal_engine import Side
        except ImportError:
            return None

        atr = getattr(signal, 'atr', None)
        if atr is None or atr <= 0:
            atr = current_price * 0.01  # 1% fallback

        if signal.result.side == Side.LONG:
            return current_price - atr
        return current_price + atr

    @staticmethod
    def _update_trail_sl(signal, current_price: float, state: dict, side) -> Optional[str]:
        """
        Ratchet the trailing SL up (LONG) or down (SHORT) when price makes a new extreme.

        Returns a broadcast message string if the trailing SL was updated, else None.
        """
        from bot.signal_engine import Side

        trail_extreme = state.get("trailing_extreme_price")
        trail_sl = state.get("trailing_stop_loss")
        if trail_sl is None:
            return None

        atr = getattr(signal, 'atr', None)
        if atr is None or atr <= 0:
            atr = current_price * 0.01

        if side == Side.LONG:
            if trail_extreme is None or current_price > trail_extreme:
                new_trail = current_price - atr
                if new_trail > trail_sl:
                    state["trailing_extreme_price"] = current_price
                    state["trailing_stop_loss"] = new_trail
                    return (
                        f"📍 #{signal.result.symbol}/USDT Trailing SL updated to "
                        f"{new_trail:.4f}"
                    )
        else:
            if trail_extreme is None or current_price < trail_extreme:
                new_trail = current_price + atr
                if new_trail < trail_sl:
                    state["trailing_extreme_price"] = current_price
                    state["trailing_stop_loss"] = new_trail
                    return (
                        f"📍 #{signal.result.symbol}/USDT Trailing SL updated to "
                        f"{new_trail:.4f}"
                    )
        return None

    @staticmethod
    def _effective_sl(signal, state: dict) -> float:
        """Return the current effective stop-loss price."""

        if state.get("trailing_stop_loss") is not None:
            return state["trailing_stop_loss"]
        if state["be_triggered"]:
            return signal.entry_mid
        return signal.result.stop_loss

    def clear_signal(self, signal_id: str) -> None:
        """Remove tracking state for a closed signal."""
        with self._lock:
            self._state.pop(signal_id, None)
