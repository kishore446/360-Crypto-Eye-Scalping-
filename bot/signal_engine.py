"""
Signal Engine — Fractal Liquidity Engine
=========================================
Implements the multi-timeframe confluence logic described in the
360 Crypto Eye Scalping master blueprint:

  1D & 4H  →  Market Bias (Bullish / Bearish)
  15m      →  Setup identification
  5m       →  Execution trigger (MSS + ChoCh + Volume)

Entry is only taken when ALL four confluence checks pass:
  ① Price is in a Discount (long) or Premium (short) zone.
  ② A Liquidity Sweep (stop-hunt) has occurred.
  ③ A 5m Change of Character (ChoCh) with above-average volume is confirmed.
  ④ No high-impact news event falls within the next 60 minutes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class CandleData:
    """Minimal OHLCV representation for one candle."""

    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SignalResult:
    """Fully-formatted 360 Eye scalp signal ready to broadcast."""

    symbol: str
    side: Side
    confidence: Confidence
    entry_low: float
    entry_high: float
    tp1: float
    tp2: float
    tp3: float
    stop_loss: float
    structure_note: str
    context_note: str
    leverage_min: int
    leverage_max: int
    signal_id: str = field(default="")

    def format_message(self) -> str:
        """Return the standardised Telegram broadcast message."""
        entry_range = f"{self.entry_low:.4f} – {self.entry_high:.4f}"
        copy_trade_entry = f"{(self.entry_low + self.entry_high) / 2:.4f}"
        tp_list = f"{self.tp1:.4f}, {self.tp2:.4f}, {self.tp3:.4f}"

        return (
            f"🚀 #{self.symbol}/USDT ({self.side.value}) | 360 EYE SCALP\n"
            f"Confidence: {self.confidence.value}\n\n"
            f"📊 STRATEGY MAP:\n"
            f"- Structure: {self.structure_note}\n"
            f"- Context: {self.context_note}\n"
            f"- Risk: 1% of Account Balance.\n\n"
            f"⚡ ENTRY ZONE: {entry_range}\n"
            f"🎯 TARGETS:\n"
            f"- TP 1: {self.tp1:.4f} (Close 50% + Move SL to Entry)\n"
            f"- TP 2: {self.tp2:.4f} (Close 25% + Start Trailing)\n"
            f"- TP 3: {self.tp3:.4f} (Final Moon Bag)\n\n"
            f"🛑 STOP LOSS: {self.stop_loss:.4f} (Structural Invalidation)\n"
            f"Leverage: Cross {self.leverage_min}x - {self.leverage_max}x (Recommended)\n\n"
            f"👇 CLICK TO COPY FOR BINANCE:\n"
            f"`{self.symbol} {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {self.stop_loss:.4f}`"
        )


def _average_volume(candles: list[CandleData]) -> float:
    """Return the simple average volume across the supplied candles."""
    if not candles:
        return 0.0
    return sum(c.volume for c in candles) / len(candles)


def is_discount_zone(price: float, range_low: float, range_high: float) -> bool:
    """
    Return True when *price* sits in the lower 50 % (discount) of the
    supplied price range — a precondition for LONG entries.
    """
    midpoint = (range_low + range_high) / 2
    return price <= midpoint


def is_premium_zone(price: float, range_low: float, range_high: float) -> bool:
    """
    Return True when *price* sits in the upper 50 % (premium) of the
    supplied price range — a precondition for SHORT entries.
    """
    midpoint = (range_low + range_high) / 2
    return price >= midpoint


def detect_liquidity_sweep(
    candles: list[CandleData],
    key_level: float,
    side: Side,
) -> bool:
    """
    Detect whether recent candles have swept a key liquidity level.

    A sweep is defined as price briefly piercing the level and then
    closing back on the opposite side within the same candle.

    Parameters
    ----------
    candles:
        Recent OHLCV candles (most-recent last).
    key_level:
        The liquidity level to test (e.g., a prior swing high or low).
    side:
        LONG → check for a bearish sweep below key_level (stop-hunt of longs).
        SHORT → check for a bullish sweep above key_level.
    """
    for candle in candles[-3:]:  # inspect only the last three candles
        if side == Side.LONG:
            # Wick pierces below the level; body closes above it
            if candle.low < key_level and candle.close > key_level:
                return True
        else:
            # Wick pierces above the level; body closes below it
            if candle.high > key_level and candle.close < key_level:
                return True
    return False


def detect_market_structure_shift(
    candles: list[CandleData],
    side: Side,
    min_displacement_pct: float = 0.0,
) -> bool:
    """
    Detect a 5m Market Structure Shift (MSS) / Change of Character (ChoCh).

    For a LONG signal: the most-recent candle breaks above the prior
    swing high with above-average volume.
    For a SHORT signal: the most-recent candle breaks below the prior
    swing low with above-average volume.

    Parameters
    ----------
    candles:
        5-minute OHLCV candles (most-recent last).  Minimum 3 required.
    side:
        Direction of the anticipated trade.
    min_displacement_pct:
        Optional minimum displacement from the swing level (as a percentage).
        When > 0, the break must exceed this percentage move to qualify.
    """
    if len(candles) < 3:
        return False

    avg_vol = _average_volume(candles)
    last = candles[-1]
    prior_candles = candles[:-1]

    if side == Side.LONG:
        swing_high = max(c.high for c in prior_candles)
        if not (last.close > swing_high and last.volume > avg_vol):
            return False
        if min_displacement_pct > 0 and swing_high > 0:
            displacement = abs(last.close - swing_high) / swing_high
            if displacement < min_displacement_pct / 100:
                return False
        return True
    else:
        swing_low = min(c.low for c in prior_candles)
        if not (last.close < swing_low and last.volume > avg_vol):
            return False
        if min_displacement_pct > 0 and swing_low > 0:
            displacement = abs(last.close - swing_low) / swing_low
            if displacement < min_displacement_pct / 100:
                return False
        return True


def assess_macro_bias(
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
) -> Optional[Side]:
    """
    Return the dominant bias from 1D and 4H structure, or None when
    the two timeframes are in conflict (no-trade condition).

    Logic:
      - 1D bullish  = last close > previous close AND above SMA-20
      - 4H bullish  = last close > previous close
      Both must agree for a directional bias to be returned.
    """
    if len(daily_candles) < 20 or len(four_hour_candles) < 2:
        return None

    # 1D bias
    sma20_daily = sum(c.close for c in daily_candles[-20:]) / 20
    daily_bullish = (
        daily_candles[-1].close > daily_candles[-2].close
        and daily_candles[-1].close > sma20_daily
    )
    daily_bearish = (
        daily_candles[-1].close < daily_candles[-2].close
        and daily_candles[-1].close < sma20_daily
    )

    # 4H bias
    four_h_bullish = four_hour_candles[-1].close > four_hour_candles[-2].close
    four_h_bearish = four_hour_candles[-1].close < four_hour_candles[-2].close

    if daily_bullish and four_h_bullish:
        return Side.LONG
    if daily_bearish and four_h_bearish:
        return Side.SHORT
    return None  # conflict → no trade


def calculate_targets(
    entry: float,
    stop_loss: float,
    side: Side,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.5,
    tp3_rr: float = 4.0,
) -> tuple[float, float, float]:
    """
    Derive TP1, TP2, TP3 from the entry/SL pair using risk-reward ratios.

    Parameters
    ----------
    entry:
        Mid-point of the entry zone.
    stop_loss:
        Structural stop-loss price.
    side:
        Trade direction.
    tp1_rr / tp2_rr / tp3_rr:
        Risk-to-reward ratios for each take-profit level.

    Returns
    -------
    Tuple of (tp1, tp2, tp3) prices.
    """
    risk = abs(entry - stop_loss)
    direction = 1 if side == Side.LONG else -1
    tp1 = entry + direction * risk * tp1_rr
    tp2 = entry + direction * risk * tp2_rr
    tp3 = entry + direction * risk * tp3_rr
    return tp1, tp2, tp3


def calculate_atr(candles: list[CandleData], period: int = 14) -> float:
    """
    Calculate the Average True Range (ATR) over *period* candles.
    Returns 0.0 if insufficient data.
    """
    if len(candles) < 2:
        return 0.0
    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    if not true_ranges:
        return 0.0
    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window)


def detect_fair_value_gap(candles: list[CandleData], side: Side) -> bool:
    """
    Detect a Fair Value Gap (FVG) in the last three candles.

    A bullish FVG exists when candle[i].low > candle[i-2].high
    (gap between candle i-2's high and candle i's low, with a large middle candle).
    A bearish FVG exists when candle[i].high < candle[i-2].low.
    """
    if len(candles) < 3:
        return False
    c0 = candles[-3]
    c2 = candles[-1]
    if side == Side.LONG:
        return c2.low > c0.high
    else:
        return c2.high < c0.low


def detect_order_block(candles: list[CandleData], side: Side) -> bool:
    """
    Detect an Order Block — the last opposing candle before an impulse move.

    For LONG: look for the last bearish candle (close < open) before a
    sequence of bullish candles.
    For SHORT: look for the last bullish candle (close > open) before a
    sequence of bearish candles.

    Returns True if an order block exists within the last 10 candles.
    """
    if len(candles) < 3:
        return False
    window = candles[-10:]
    if side == Side.LONG:
        # Find last bearish candle followed by a bullish impulse
        for i in range(len(window) - 2, 0, -1):
            if window[i].close < window[i].open:  # bearish
                # Check that subsequent candles are bullish
                if window[i + 1].close > window[i + 1].open:
                    return True
    else:
        # Find last bullish candle followed by a bearish impulse
        for i in range(len(window) - 2, 0, -1):
            if window[i].close > window[i].open:  # bullish
                if window[i + 1].close < window[i + 1].open:
                    return True
    return False


def run_confluence_check(
    symbol: str,
    current_price: float,
    side: Side,
    range_low: float,
    range_high: float,
    key_liquidity_level: float,
    five_min_candles: list[CandleData],
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    news_in_window: bool,
    stop_loss: float,
    structure_note: str = "",
    context_note: str = "",
    leverage_min: int = 10,
    leverage_max: int = 20,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.5,
    tp3_rr: float = 4.0,
    check_fvg: bool = False,
    check_order_block: bool = False,
) -> Optional[SignalResult]:
    """
    Run all four confluence gates and return a :class:`SignalResult` when
    every condition is satisfied, or ``None`` when the trade should be skipped.

    Gates
    -----
    ① Macro bias (1D + 4H) aligns with *side*.
    ② Price is in the correct discount / premium zone.
    ③ A liquidity sweep has occurred at *key_liquidity_level*.
    ④ A 5m MSS / ChoCh with volume is confirmed.
    ⑤ No high-impact news event is imminent (*news_in_window* is False).
    ⑥ (Optional) Fair Value Gap present.
    ⑦ (Optional) Order Block present.
    """
    # Gate ⑤ — news blackout
    if news_in_window:
        return None

    # Gate ① — macro bias
    macro_bias = assess_macro_bias(daily_candles, four_hour_candles)
    if macro_bias != side:
        return None

    # Gate ② — discount / premium zone
    if side == Side.LONG and not is_discount_zone(current_price, range_low, range_high):
        return None
    if side == Side.SHORT and not is_premium_zone(current_price, range_low, range_high):
        return None

    # Gate ③ — liquidity sweep
    if not detect_liquidity_sweep(five_min_candles, key_liquidity_level, side):
        return None

    # Gate ④ — 5m MSS / ChoCh
    if not detect_market_structure_shift(five_min_candles, side):
        return None

    # Gate ⑥ — optional FVG check
    if check_fvg and not detect_fair_value_gap(five_min_candles, side):
        return None

    # Gate ⑦ — optional Order Block check
    if check_order_block and not detect_order_block(five_min_candles, side):
        return None

    # All gates passed — build signal
    atr = calculate_atr(five_min_candles)
    if atr > 0:
        entry_spread = atr * 0.5
    else:
        entry_spread = abs(current_price * 0.001)  # 0.1 % tight entry zone fallback
    entry_low = current_price - entry_spread
    entry_high = current_price + entry_spread

    tp1, tp2, tp3 = calculate_targets(current_price, stop_loss, side, tp1_rr, tp2_rr, tp3_rr)

    # High confidence when the 4H direction agrees with the signal side
    if len(four_hour_candles) >= 2:
        last_4h_rising = four_hour_candles[-1].close > four_hour_candles[-2].close
        direction_match = (side == Side.LONG and last_4h_rising) or (side == Side.SHORT and not last_4h_rising)
    else:
        direction_match = False
    confidence = Confidence.HIGH if direction_match else Confidence.MEDIUM

    from bot.logging_config import generate_signal_id
    sig_id = generate_signal_id()

    return SignalResult(
        symbol=symbol,
        side=side,
        confidence=confidence,
        entry_low=entry_low,
        entry_high=entry_high,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        stop_loss=stop_loss,
        structure_note=structure_note or f"4H {'Bullish' if side == Side.LONG else 'Bearish'} OB + 5m MSS Confirmed.",
        context_note=context_note or f"{symbol} structure aligned with higher timeframe bias.",
        leverage_min=leverage_min,
        leverage_max=leverage_max,
        signal_id=sig_id,
    )
