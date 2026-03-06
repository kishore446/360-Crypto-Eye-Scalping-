"""
CH3 — Easy Breakout detector.

Three-gate breakout scanner:
  1. Volume spike gate: current candle volume > CH3_VOLUME_SPIKE_RATIO × 20-period avg
  2. 4H breakout gate: price > max 4H high OR price < min 4H low
  3. RSI momentum gate: RSI(14) > 55 for LONG, RSI(14) < 45 for SHORT

No macro bias gate, no news gate — this channel is informational breakout alerts.

Produces a simplified "⚡ MOMENTUM ALERT" format (no TP3, no leverage).
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.signal_engine import (
    CandleData,
    Side,
    _average_volume,
    calculate_rsi,
    calculate_targets,
    calculate_atr,
)

try:
    from config import CH3_VOLUME_SPIKE_RATIO as _VOL_RATIO
except Exception:  # pragma: no cover
    _VOL_RATIO = 1.5


@dataclass
class BreakoutResult:
    """Simplified breakout signal for CH3."""

    symbol: str
    side: Side
    entry_price: float
    tp1: float
    tp2: float
    stop_loss: float

    def format_message(self) -> str:
        """Return the CH3 ⚡ MOMENTUM ALERT Telegram message."""
        direction = "🟢 LONG" if self.side == Side.LONG else "🔴 SHORT"
        return (
            f"⚡ MOMENTUM ALERT — #{self.symbol}/USDT\n"
            f"Direction: {direction}\n\n"
            f"Entry: {self.entry_price:.4f}\n"
            f"🎯 TP 1: {self.tp1:.4f}\n"
            f"🎯 TP 2: {self.tp2:.4f}\n"
            f"🛑 SL: {self.stop_loss:.4f}\n\n"
            f"⚠️ Breakout alert — use tight risk management."
        )


def run(
    symbol: str,
    current_price: float,
    five_min_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    volume_spike_ratio: float = _VOL_RATIO,
) -> BreakoutResult | None:
    """
    Run the CH3 Easy Breakout three-gate check.

    Parameters
    ----------
    symbol:
        Base asset symbol (e.g. "BTC").
    current_price:
        Latest market price.
    five_min_candles:
        Recent 5-minute OHLCV candles (most-recent last).
    four_hour_candles:
        Recent 4-hour OHLCV candles (most-recent last).
    volume_spike_ratio:
        Volume must exceed this multiple of the 20-period average
        (default: 1.5 = 150%).

    Returns
    -------
    A :class:`BreakoutResult` or None if no breakout is detected.
    """
    if len(five_min_candles) < 21 or len(four_hour_candles) < 2:
        return None

    last_5m = five_min_candles[-1]

    # Gate 1 — volume spike
    avg_vol = _average_volume(five_min_candles[-20:])
    if avg_vol <= 0 or last_5m.volume < volume_spike_ratio * avg_vol:
        return None

    # Gate 2 — 4H breakout (close above recent 4H high OR below recent 4H low)
    # Use last 3 4H candles (~12 hours) to establish the breakout reference range
    recent_4h = four_hour_candles[-3:] if len(four_hour_candles) >= 3 else four_hour_candles
    recent_4h_high = max(c.high for c in recent_4h)
    recent_4h_low = min(c.low for c in recent_4h)

    long_breakout = current_price > recent_4h_high
    short_breakout = current_price < recent_4h_low

    if not long_breakout and not short_breakout:
        return None

    side = Side.LONG if long_breakout else Side.SHORT

    # Gate 3 — RSI momentum
    rsi = calculate_rsi(five_min_candles, period=14)
    if side == Side.LONG and rsi <= 55:
        return None
    if side == Side.SHORT and rsi >= 45:
        return None

    # Build simplified signal
    atr = calculate_atr(five_min_candles)
    sl_buffer = atr if atr > 0 else abs(current_price * 0.005)

    if side == Side.LONG:
        stop_loss = current_price - sl_buffer
    else:
        stop_loss = current_price + sl_buffer

    tp1, tp2, _ = calculate_targets(current_price, stop_loss, side, tp1_rr=1.5, tp2_rr=2.5, tp3_rr=4.0)

    return BreakoutResult(
        symbol=symbol,
        side=side,
        entry_price=current_price,
        tp1=tp1,
        tp2=tp2,
        stop_loss=stop_loss,
    )
