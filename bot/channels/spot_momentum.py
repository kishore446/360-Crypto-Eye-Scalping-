"""
CH4 — Spot Momentum scanner.

Five-gate spot scanner (runs every 4 hours, not per 5m candle):
  1. Weekly bias: close > 10-week SMA (using 70 daily candles ≈ 10 weeks)
  2. Accumulation zone: price within CH4_ACCUMULATION_THRESHOLD (15%) above 90-day low
  3. Volume building: 3-day avg volume > 90-day avg volume
  4. RSI (1D) between 40 and 60
  5. 4H higher lows: last two 4H swing lows are ascending

Always produces "SPOT ONLY — No Leverage" signals.
Produces a "🎯 SPOT SETUP" format with wide TP targets (15%/30%/50%).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.signal_engine import (
    CandleData,
    Side,
    calculate_rsi,
)

try:
    from config import CH4_ACCUMULATION_THRESHOLD as _ACCUM_THRESHOLD
except Exception:  # pragma: no cover
    _ACCUM_THRESHOLD = 0.15


@dataclass
class SpotSignalResult:
    """Spot momentum signal for CH4."""

    symbol: str
    entry_low: float
    entry_high: float
    tp1: float
    tp2: float
    tp3: float
    stop_loss: float
    accumulation_low: float

    def format_message(self) -> str:
        """Return the CH4 🎯 SPOT SETUP Telegram message."""
        entry_range = f"{self.entry_low:.4f} – {self.entry_high:.4f}"
        return (
            f"🎯 SPOT SETUP — #{self.symbol}/USDT\n"
            f"Signal Type: SPOT ONLY — No Leverage\n\n"
            f"📊 Entry Zone: {entry_range}\n\n"
            f"🎯 Targets:\n"
            f"- TP 1: {self.tp1:.4f} (+15%)\n"
            f"- TP 2: {self.tp2:.4f} (+30%)\n"
            f"- TP 3: {self.tp3:.4f} (+50%)\n\n"
            f"🛑 Stop Loss: {self.stop_loss:.4f} (below accumulation low)\n\n"
            f"⏳ Holding Time: Days to weeks\n"
            f"⚠️ SPOT ONLY — No Leverage"
        )


def run(
    symbol: str,
    current_price: float,
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    accumulation_threshold: float = _ACCUM_THRESHOLD,
) -> Optional[SpotSignalResult]:
    """
    Run the CH4 Spot Momentum five-gate scan.

    Parameters
    ----------
    symbol:
        Base asset symbol (e.g. "BTC").
    current_price:
        Latest market price.
    daily_candles:
        1D OHLCV candles (most-recent last). Needs at least 90 candles.
    four_hour_candles:
        4H OHLCV candles (most-recent last). Needs at least 4 candles.
    accumulation_threshold:
        Price must be within this fraction above the 90-day low.

    Returns
    -------
    A :class:`SpotSignalResult` or None if the setup does not qualify.
    """
    if len(daily_candles) < 70 or len(four_hour_candles) < 4:
        return None

    # Gate 1 — weekly bias: close > 10-week SMA (70 daily candles)
    sma10w = sum(c.close for c in daily_candles[-70:]) / 70
    if current_price <= sma10w:
        return None

    # Gate 2 — accumulation zone: price within threshold above 90-day low
    low_90d = min(c.low for c in daily_candles[-90:]) if len(daily_candles) >= 90 else min(c.low for c in daily_candles)
    accumulation_ceiling = low_90d * (1 + accumulation_threshold)
    if current_price > accumulation_ceiling:
        return None

    # Gate 3 — volume building: 3-day avg > 90-day avg
    vol_90d_avg = sum(c.volume for c in daily_candles[-90:]) / min(len(daily_candles), 90)
    vol_3d_avg = sum(c.volume for c in daily_candles[-3:]) / 3
    if vol_3d_avg <= vol_90d_avg:
        return None

    # Gate 4 — RSI (1D) between 40 and 60
    rsi_1d = calculate_rsi(daily_candles, period=14)
    if not (40 <= rsi_1d <= 60):
        return None

    # Gate 5 — 4H higher lows: last two 4H swing lows are ascending
    swing_lows = [c.low for c in four_hour_candles[-4:]]
    if len(swing_lows) < 2 or swing_lows[-1] <= swing_lows[-2]:
        return None

    # Build spot signal with wide TP targets
    entry_low = current_price * 0.99
    entry_high = current_price * 1.01
    entry_mid = current_price

    tp1 = entry_mid * 1.15
    tp2 = entry_mid * 1.30
    tp3 = entry_mid * 1.50
    stop_loss = low_90d * 0.98  # just below accumulation low

    return SpotSignalResult(
        symbol=symbol,
        entry_low=entry_low,
        entry_high=entry_high,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        stop_loss=stop_loss,
        accumulation_low=low_90d,
    )
