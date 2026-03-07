"""
Signal Tracker
==============
Real-time signal lifecycle tracking with auto-update broadcasts.
"""
from __future__ import annotations
import logging
import threading

logger = logging.getLogger(__name__)


class SignalTracker:
    """
    Tracks signal lifecycle events: TP1/TP2/TP3 hits, SL hits, BE triggers.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def check_signal(self, signal, current_price: float) -> list[str]:
        """
        Check a signal against current price and return broadcast messages for any newly hit levels.
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
                r = abs(signal.result.tp2 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP2 HIT at {signal.result.tp2:.4f} "
                    f"— Trailing SL active. +{r:.1f}R"
                )
            elif state["tp2_hit"] and not state["tp3_hit"] and current_price >= signal.result.tp3:
                state["tp3_hit"] = True
                r = abs(signal.result.tp3 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP3 HIT at {signal.result.tp3:.4f} "
                    f"— Full target reached. +{r:.1f}R"
                )
            if not state["sl_hit"] and not state["tp3_hit"]:
                effective_sl = signal.entry_mid if state["be_triggered"] else signal.result.stop_loss
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
                r = abs(signal.result.tp2 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP2 HIT at {signal.result.tp2:.4f} "
                    f"— Trailing SL active. +{r:.1f}R"
                )
            elif state["tp2_hit"] and not state["tp3_hit"] and current_price <= signal.result.tp3:
                state["tp3_hit"] = True
                r = abs(signal.result.tp3 - signal.entry_mid) / safe_risk
                messages.append(
                    f"✅ #{signal.result.symbol}/USDT TP3 HIT at {signal.result.tp3:.4f} "
                    f"— Full target reached. +{r:.1f}R"
                )
            if not state["sl_hit"] and not state["tp3_hit"]:
                effective_sl = signal.entry_mid if state["be_triggered"] else signal.result.stop_loss
                if current_price >= effective_sl:
                    state["sl_hit"] = True
                    messages.append(
                        f"❌ #{signal.result.symbol}/USDT SL HIT at {effective_sl:.4f} "
                        f"— -1.0R (1% account loss)"
                    )

        return messages

    def clear_signal(self, signal_id: str) -> None:
        """Remove tracking state for a closed signal."""
        with self._lock:
            self._state.pop(signal_id, None)
