"""
Signal Invalidation Detector
=============================
Detects when a signal's thesis breaks *before* SL is hit and returns
a proactive alert reason string.

Invalidation conditions:
  1. OB Breach  — order block zone breached by a close beyond it.
  2. Regime Flip — market regime has flipped against the signal direction.
  3. Volume Death — last 5 candles all below 50 % of 20-period average volume.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.risk_manager import ActiveSignal
    from bot.signal_engine import CandleData

logger = logging.getLogger(__name__)

__all__ = ["InvalidationDetector"]


class InvalidationDetector:
    """Checks whether a live signal's thesis has been invalidated."""

    def check_invalidation(
        self,
        signal: "ActiveSignal",
        current_price: float,
        candles_5m: "list[CandleData]",
        candles_4h: "list[CandleData]",
        market_regime: str,
    ) -> Optional[str]:
        """
        Evaluate all invalidation conditions for *signal*.

        Parameters
        ----------
        signal:
            The active signal to evaluate.
        current_price:
            Latest market price.
        candles_5m:
            Recent 5-minute candles (at least 5 required for volume check).
        candles_4h:
            Recent 4-hour candles (used for ATR approximation).
        market_regime:
            Current market regime string ('BULL', 'BEAR', 'SIDEWAYS', 'UNKNOWN').

        Returns
        -------
        Optional[str]
            A human-readable reason string if any condition is met, else None.
        """
        # 1. Order Block Breach
        ob_reason = self._check_ob_breach(signal, candles_5m, candles_4h)
        if ob_reason:
            return ob_reason

        # 2. Regime Flip
        regime_reason = self._check_regime_flip(signal, market_regime)
        if regime_reason:
            return regime_reason

        # 3. Volume Death
        volume_reason = self._check_volume_death(candles_5m)
        if volume_reason:
            return volume_reason

        return None

    # ── condition checkers ────────────────────────────────────────────────────

    def _check_ob_breach(
        self,
        signal: "ActiveSignal",
        candles_5m: "list[CandleData]",
        candles_4h: "list[CandleData]",
    ) -> Optional[str]:
        """Check whether the order block zone has been breached."""
        from bot.signal_engine import Side, calculate_atr

        side = signal.result.side
        # Use 4h candles for ATR if available, else fall back to 5m
        atr_candles = candles_4h if len(candles_4h) >= 5 else candles_5m
        if not atr_candles:
            return None

        atr = calculate_atr(atr_candles, period=min(14, len(atr_candles)))
        if atr <= 0:
            return None

        # Approximate OB breach threshold
        if side == Side.LONG:
            breach_level = signal.result.entry_low - 0.5 * atr
            # A close below the OB low means breach
            if candles_5m and candles_5m[-1].close < breach_level:
                return "Order block zone breached — price closed below OB low"
        else:
            breach_level = signal.result.entry_high + 0.5 * atr
            # A close above the OB high means breach
            if candles_5m and candles_5m[-1].close > breach_level:
                return "Order block zone breached — price closed above OB high"

        return None

    @staticmethod
    def _check_regime_flip(
        signal: "ActiveSignal",
        current_regime: str,
    ) -> Optional[str]:
        """Check whether the market regime has flipped against the signal direction."""
        from bot.signal_engine import Side

        created_regime = getattr(signal, "created_regime", "UNKNOWN")
        side = signal.result.side

        if created_regime == "UNKNOWN" or current_regime == "UNKNOWN":
            return None

        flipped = (
            (side == Side.LONG and created_regime == "BULL" and current_regime == "BEAR")
            or (side == Side.SHORT and created_regime == "BEAR" and current_regime == "BULL")
        )
        if flipped:
            return (
                f"Market regime flipped from {created_regime} to {current_regime} "
                f"— thesis no longer valid for {side.value}"
            )
        return None

    @staticmethod
    def _check_volume_death(candles_5m: "list[CandleData]") -> Optional[str]:
        """Check whether the last 5 candles are all below 50 % of the 20-period average."""
        if len(candles_5m) < 6:  # need at least 5 recent candles + 1 for history baseline
            return None

        recent = candles_5m[-5:]
        history = candles_5m[-20:] if len(candles_5m) >= 20 else candles_5m
        avg_vol = sum(c.volume for c in history) / len(history) if history else 0.0

        if avg_vol <= 0:
            return None

        threshold = avg_vol * 0.5
        if all(c.volume < threshold for c in recent):
            return "Volume momentum exhausted — last 5 candles below 50% avg volume"

        return None


def format_invalidation_alert(
    signal: "ActiveSignal",
    reason: str,
    current_price: float,
) -> str:
    """Format an invalidation alert as a Telegram message."""
    r = signal.result
    return (
        f"⚠️ SIGNAL INVALIDATION — #{r.symbol}/USDT {r.side.value}\n"
        f"Reason: {reason}\n"
        f"Recommendation: Consider closing manually or tightening SL\n"
        f"Original Entry: {signal.entry_mid:,.2f}\n"
        f"Current Price: {current_price:,.2f}"
    )
