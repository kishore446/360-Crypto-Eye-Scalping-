"""
Signal Invalidation Detector
=============================
Detects when a signal's thesis breaks *before* stop-loss is hit.

Invalidation conditions:
  1. OB Breach  — price closes beyond entry zone +/- 0.5*ATR
  2. Regime Flip — market regime changed vs signal creation regime
  3. Volume Death — last 5 candles all below 50% of 20-period average volume
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.risk_manager import ActiveSignal
    from bot.signal_engine import CandleData

__all__ = ["InvalidationDetector"]


def _compute_atr(candles: list["CandleData"], period: int = 14) -> float:
    """
    Compute a simple ATR (True Range average) over the last *period* candles.

    Requires at least 2 candles to produce a non-zero result; returns 0.0
    when fewer than 2 candles are provided.
    """
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    subset = candles[-period:] if len(candles) >= period else candles
    for i, c in enumerate(subset):
        if i == 0:
            trs.append(c.high - c.low)
        else:
            prev_close = subset[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


class InvalidationDetector:
    """
    Detects thesis-break conditions for active signals.

    Usage::

        detector = InvalidationDetector()
        reason = detector.check_invalidation(signal, price, candles_5m, candles_4h, regime)
        if reason:
            # broadcast alert
    """

    def check_invalidation(
        self,
        signal: "ActiveSignal",
        current_price: float,
        candles_5m: list["CandleData"],
        candles_4h: list["CandleData"],
        market_regime: str,
    ) -> Optional[str]:
        """
        Check whether the signal's thesis has been invalidated.

        Returns a reason string if any invalidation condition matches,
        or None if the signal is still valid.

        Parameters
        ----------
        signal:
            The active signal to check.
        current_price:
            Latest traded price for the signal's symbol.
        candles_5m:
            List of recent 5-minute candles (CandleData).
        candles_4h:
            List of recent 4-hour candles (CandleData).
        market_regime:
            Current market regime string (e.g. "BULL", "BEAR", "NEUTRAL").
        """
        from bot.signal_engine import Side

        r = signal.result
        atr = _compute_atr(candles_5m)

        # ── Condition 1: OB Breach ────────────────────────────────────────────
        if r.side == Side.LONG:
            breach_level = r.entry_low - 0.5 * atr
            if current_price < breach_level:
                return f"OB Breach (price {current_price:.4f} < entry_low {r.entry_low:.4f} - 0.5×ATR)"
        else:  # SHORT
            breach_level = r.entry_high + 0.5 * atr
            if current_price > breach_level:
                return f"OB Breach (price {current_price:.4f} > entry_high {r.entry_high:.4f} + 0.5×ATR)"

        # ── Condition 2: Regime Flip ──────────────────────────────────────────
        created_regime: str = getattr(signal, "created_regime", "UNKNOWN")
        if created_regime not in ("UNKNOWN", "") and market_regime not in ("UNKNOWN", ""):
            if r.side == Side.LONG and "BEAR" in market_regime.upper() and "BULL" in created_regime.upper():
                return f"Regime Flip (created in {created_regime}, now {market_regime})"
            if r.side == Side.SHORT and "BULL" in market_regime.upper() and "BEAR" in created_regime.upper():
                return f"Regime Flip (created in {created_regime}, now {market_regime})"

        # ── Condition 3: Volume Death ─────────────────────────────────────────
        if len(candles_5m) >= 20:
            recent_20 = candles_5m[-20:]
            avg_vol = sum(c.volume for c in recent_20) / 20
            if avg_vol > 0:
                last_5 = candles_5m[-5:]
                if len(last_5) == 5 and all(c.volume < avg_vol * 0.5 for c in last_5):
                    return "Volume Death (last 5 candles all below 50% of 20-period avg)"

        return None

    def format_alert(
        self,
        signal: "ActiveSignal",
        reason: str,
        current_price: float,
    ) -> str:
        """Format an invalidation alert for Telegram broadcast."""
        r = signal.result
        entry = signal.entry_mid
        return (
            f"⚠️ SIGNAL INVALIDATION — {r.symbol}/USDT {r.side.value}\n"
            f"Reason: {reason}\n"
            f"Recommendation: Consider closing manually or tightening SL\n"
            f"Original Entry: {entry:.4f}\n"
            f"Current Price: {current_price:.4f}"
        )
