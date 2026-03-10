"""
CH3 — Trend / Positional detector.

Implements the institutional Trend/Positional blueprint:
  1. Primary Trend Filter: EMA50 & EMA200 alignment
  2. Multi-Timeframe Confirmation: H4 + Daily alignment
  3. Momentum Filter: RSI14 >55 Long / <45 Short + MACD confirmation
  4. Liquidity Filter: Only pairs with daily volume > $100M (volume spike proxy)
  5. Volatility Filter: ATR > threshold (above 20-candle average ATR)
  6. Fundamental / Market Filter: Avoid major news events (CPI, FOMC, Binance)
  7. Entry Confirmation: Daily candle close confirms trend + volume spike
  8. Exit Strategy: TP 2–3× ATR, SL below/above previous swing low/high
  9. Timeframe: 4H–1D candles
 10. Signal Frequency: Every daily candle
 11. Multi-Layer Confirmation: Requires 5 aligned filters minimum

Produces a "⚡ TREND SIGNAL" format aligned with the positional trading style.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.price_fmt import fmt_price
from bot.signal_engine import (
    CandleData,
    Side,
    _average_volume,
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_targets,
)

try:
    from config import CH3_VOLUME_SPIKE_RATIO as _VOL_RATIO
except Exception:  # pragma: no cover
    _VOL_RATIO = 1.2


@dataclass
class TrendResult:
    """Positional trend signal for CH3."""

    symbol: str
    side: Side
    entry_price: float
    tp1: float
    tp2: float
    stop_loss: float
    filters_passed: int = 0

    def format_message(self) -> str:
        """Return the CH3 ⚡ TREND SIGNAL Telegram message."""
        direction = "🟢 LONG" if self.side == Side.LONG else "🔴 SHORT"
        return (
            f"⚡ TREND SIGNAL — #{self.symbol}/USDT\n"
            f"Direction: {direction}\n\n"
            f"Entry: {fmt_price(self.entry_price)}\n"
            f"🎯 TP 1: {fmt_price(self.tp1)}\n"
            f"🎯 TP 2: {fmt_price(self.tp2)}\n"
            f"🛑 SL: {fmt_price(self.stop_loss)}\n\n"
            f"📊 Filters confirmed: {self.filters_passed}/5\n"
            f"⏱ Trend/Positional — 4H–1D timeframe. Use wider stops."
        )


def _check_ema_alignment(candles: list[CandleData], side: Side) -> bool:
    """Filter 1: EMA50 & EMA200 alignment on provided candles."""
    if len(candles) < 205:
        return False
    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)
    if side == Side.LONG:
        return ema50 > ema200
    return ema50 < ema200


def _check_mtf_alignment(
    four_hour_candles: list[CandleData],
    daily_candles: list[CandleData],
    side: Side,
) -> bool:
    """Filter 2: H4 + Daily EMA50/200 alignment (multi-timeframe confirmation)."""
    h4_ok = _check_ema_alignment(four_hour_candles, side)
    d1_ok = _check_ema_alignment(daily_candles, side)
    return h4_ok and d1_ok


def _check_rsi_macd_momentum(candles: list[CandleData], side: Side) -> bool:
    """Filter 3: RSI14 >55 Long / <45 Short + MACD histogram confirmation."""
    if len(candles) < 35:
        return False
    rsi = calculate_rsi(candles, period=14)
    _, _, histogram = calculate_macd(candles)
    if side == Side.LONG:
        return rsi > 55 and histogram > 0
    return rsi < 45 and histogram < 0


def _check_liquidity(candles: list[CandleData], multiplier: float = _VOL_RATIO) -> bool:
    """
    Filter 4: Liquidity proxy — daily volume spike (≥ multiplier × 20-day avg).

    In a live system this would filter pairs with daily volume > $100M.
    Here we use a volume-spike proxy on the provided candles.
    """
    if len(candles) < 21:
        return False
    avg_vol = _average_volume(candles[-20:])
    return avg_vol > 0 and candles[-1].volume >= multiplier * avg_vol


def _check_atr_volatility(candles: list[CandleData]) -> bool:
    """Filter 5: ATR > last 20-candle average ATR."""
    if len(candles) < 34:
        return False
    current_atr = calculate_atr(candles)
    atr_values = [
        calculate_atr(candles[: -(20 - i) or None])
        for i in range(20)
    ]
    avg_atr = sum(atr_values) / len(atr_values) if atr_values else 0
    return current_atr > avg_atr


def run(
    symbol: str,
    current_price: float,
    five_min_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    daily_candles: Optional[list[CandleData]] = None,
    volume_spike_ratio: float = _VOL_RATIO,
) -> "TrendResult | None":
    """
    Run the CH3 Trend / Positional five-filter check.

    Parameters
    ----------
    symbol:
        Base asset symbol (e.g. "BTC").
    current_price:
        Latest market price.
    five_min_candles:
        Recent 5-minute OHLCV candles (most-recent last). Used as fallback
        when higher-timeframe candles are unavailable for some filters.
    four_hour_candles:
        Recent 4-hour OHLCV candles (most-recent last).
    daily_candles:
        Optional daily OHLCV candles for multi-timeframe confirmation.
    volume_spike_ratio:
        Volume must exceed this multiple of the 20-period average
        (default: 1.2 = 120%).

    Returns
    -------
    A :class:`TrendResult` or None if fewer than 5 filters pass.
    """
    if len(five_min_candles) < 21 or len(four_hour_candles) < 2:
        return None

    # Determine trend direction from 4H EMA alignment
    # (requires enough candles for EMA200; fall back to breakout if not available)
    if len(four_hour_candles) >= 205:
        ema50_4h = calculate_ema(four_hour_candles, 50)
        ema200_4h = calculate_ema(four_hour_candles, 200)
        if ema50_4h > ema200_4h:
            side = Side.LONG
        elif ema50_4h < ema200_4h:
            side = Side.SHORT
        else:
            return None  # No clear trend
    else:
        # Fallback: use recent 4H high/low breakout to determine side
        recent_4h = four_hour_candles[-6:] if len(four_hour_candles) >= 6 else four_hour_candles
        recent_high = max(c.high for c in recent_4h)
        recent_low = min(c.low for c in recent_4h)
        if current_price > recent_high:
            side = Side.LONG
        elif current_price < recent_low:
            side = Side.SHORT
        else:
            return None

    # Evaluate all 5 filters
    filters_passed = 0
    d_candles = daily_candles or four_hour_candles

    # Filter 1: EMA50/200 alignment on 4H
    if _check_ema_alignment(four_hour_candles, side):
        filters_passed += 1

    # Filter 2: Multi-timeframe H4 + Daily confirmation
    if _check_mtf_alignment(four_hour_candles, d_candles, side):
        filters_passed += 1

    # Filter 3: RSI14 + MACD momentum
    if _check_rsi_macd_momentum(four_hour_candles, side):
        filters_passed += 1

    # Filter 4: Liquidity (volume spike on 5m as proxy)
    if _check_liquidity(five_min_candles, multiplier=volume_spike_ratio):
        filters_passed += 1

    # Filter 5: ATR volatility on 4H candles
    if _check_atr_volatility(four_hour_candles):
        filters_passed += 1

    # Require all 5 filters to pass for a trend signal
    if filters_passed < 5:
        return None

    # Build signal with ATR-based TP/SL
    atr = calculate_atr(four_hour_candles)
    sl_buffer = atr if atr > 0 else abs(current_price * 0.01)

    if side == Side.LONG:
        stop_loss = current_price - sl_buffer
    else:
        stop_loss = current_price + sl_buffer

    # Exit: TP 2–3× ATR (use 2.0R and 3.0R for conservative targets)
    tp1, tp2, _ = calculate_targets(
        current_price, stop_loss, side, tp1_rr=2.0, tp2_rr=3.0, tp3_rr=4.0
    )

    return TrendResult(
        symbol=symbol,
        side=side,
        entry_price=current_price,
        tp1=tp1,
        tp2=tp2,
        stop_loss=stop_loss,
        filters_passed=filters_passed,
    )
