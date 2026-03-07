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

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "Side",
    "Confidence",
    "CandleData",
    "SignalResult",
    "is_discount_zone",
    "is_premium_zone",
    "detect_liquidity_sweep",
    "detect_market_structure_shift",
    "detect_fair_value_gap",
    "detect_order_block",
    "assess_macro_bias",
    "assess_macro_bias_relaxed",
    "calculate_atr",
    "calculate_rsi",
    "calculate_targets",
    "run_confluence_check",
    "run_confluence_check_relaxed",
]


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
    confluence_score: int = 0

    def format_message(self) -> str:
        """Return the standardised Telegram broadcast message."""
        entry_range = f"{self.entry_low:.4f} – {self.entry_high:.4f}"
        copy_trade_entry = f"{(self.entry_low + self.entry_high) / 2:.4f}"
        tp_list = f"{self.tp1:.4f}, {self.tp2:.4f}, {self.tp3:.4f}"

        # Confidence stars
        stars = {"High": "⭐⭐⭐", "Medium": "⭐⭐", "Low": "⭐"}.get(self.confidence.value, "⭐")
        confidence_line = f"Confidence: {self.confidence.value} {stars}"
        if self.confluence_score > 0:
            confidence_line += f" | Score: {self.confluence_score}/100"

        bybit_copy = (
            f"\n\n👇 CLICK TO COPY FOR BYBIT:\n"
            f"`{self.symbol}/USDT {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {self.stop_loss:.4f}`"
        )

        return (
            f"🚀 #{self.symbol}/USDT ({self.side.value}) | 360 EYE SCALP\n"
            f"{confidence_line}\n\n"
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
            f"{bybit_copy}"
        )


def _average_volume(candles: list[CandleData]) -> float:
    """Return the simple average volume across the supplied candles."""
    if not candles:
        return 0.0
    return sum(c.volume for c in candles) / len(candles)


def _calculate_ema(candles: list[CandleData], period: int) -> float:
    """
    Calculate the Exponential Moving Average of closing prices.

    Uses the standard smoothing factor k = 2 / (period + 1).
    Returns the last close if there are fewer candles than the period.
    """
    if not candles:
        return 0.0
    if len(candles) < period:
        return sum(c.close for c in candles) / len(candles)
    k = 2.0 / (period + 1)
    ema = sum(c.close for c in candles[:period]) / period
    for candle in candles[period:]:
        ema = candle.close * k + ema * (1 - k)
    return ema


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
    for candle in candles[-7:]:  # inspect the last seven candles (~35 min)
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
    min_displacement_pct: float = 0.15,
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
        swing_high = max(c.high for c in prior_candles[-7:])  # last 7 candles ≈ 35 min
        if not (last.close > swing_high and last.volume > avg_vol):
            return False
        if min_displacement_pct > 0 and swing_high > 0:
            displacement = abs(last.close - swing_high) / swing_high
            if displacement < min_displacement_pct / 100:
                return False
        return True
    else:
        swing_low = min(c.low for c in prior_candles[-7:])  # last 7 candles ≈ 35 min
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
      - 1D bullish  = last close > previous close AND (close > SMA-20 OR close > EMA-9)
      - 1D bearish  = last close < previous close AND (close < SMA-20 OR close < EMA-9)
      - 4H bullish  = last close > previous close
      Both must agree for a directional bias to be returned.

    Using OR between SMA-20 and EMA-9 prevents false negatives during
    ranging/consolidating markets where only one MA is above price.
    """
    if len(daily_candles) < 20 or len(four_hour_candles) < 2:
        return None

    # 1D bias
    sma20_daily = sum(c.close for c in daily_candles[-20:]) / 20

    # EMA-9 on daily candles (smoothing factor k = 2/(9+1) = 0.2)
    ema9_daily = _calculate_ema(daily_candles, period=9)

    last_daily = daily_candles[-1]
    prev_daily = daily_candles[-2]

    daily_bullish = (
        last_daily.close > prev_daily.close
        and (last_daily.close > sma20_daily or last_daily.close > ema9_daily)
    )
    daily_bearish = (
        last_daily.close < prev_daily.close
        and (last_daily.close < sma20_daily or last_daily.close < ema9_daily)
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
    fifteen_min_candles: Optional[list[CandleData]] = None,
    min_displacement_pct: Optional[float] = None,
) -> Optional[SignalResult]:
    """
    Run all four confluence gates and return a :class:`SignalResult` when
    every condition is satisfied, or ``None`` when the trade should be skipped.

    Gates
    -----
    ① Macro bias (1D + 4H) aligns with *side*.
    ② Price is in the correct discount / premium zone.
    ③ A liquidity sweep has occurred at *key_liquidity_level*.
    ④ A 5m MSS / ChoCh with volume is confirmed (with 0.15% displacement filter).
    ⑤ No high-impact news event is imminent (*news_in_window* is False).
    ⑥ (Optional) Fair Value Gap present.
    ⑦ (Optional) Order Block present.

    Parameters
    ----------
    fifteen_min_candles:
        Optional 15m candles used for FVG / OB scoring per Blueprint §2.1.
        Falls back to *five_min_candles* when not supplied.
    min_displacement_pct:
        Override the displacement filter for Gate ④.  When ``None``, the
        value from ``config.MIN_DISPLACEMENT_PCT`` (default 0.15) is used.
    """
    try:
        from config import MIN_DISPLACEMENT_PCT as _cfg_displacement
    except ImportError:
        _cfg_displacement = 0.15
    effective_displacement = min_displacement_pct if min_displacement_pct is not None else _cfg_displacement

    # Gate ⑤ — news blackout
    if news_in_window:
        logger.info("[GATE_FAIL] %s %s: gate=news reason=high_impact_imminent", symbol, side.value)
        return None

    # Gate ① — macro bias
    macro_bias = assess_macro_bias(daily_candles, four_hour_candles)
    if macro_bias != side:
        logger.info(
            "[GATE_FAIL] %s %s: gate=macro_bias reason=conflict bias=%s",
            symbol, side.value, macro_bias.value if macro_bias else "None",
        )
        return None

    # Gate ② — discount / premium zone
    if side == Side.LONG and not is_discount_zone(current_price, range_low, range_high):
        logger.info("[GATE_FAIL] %s %s: gate=zone reason=price_not_in_discount", symbol, side.value)
        return None
    if side == Side.SHORT and not is_premium_zone(current_price, range_low, range_high):
        logger.info("[GATE_FAIL] %s %s: gate=zone reason=price_not_in_premium", symbol, side.value)
        return None

    # Gate ③ — liquidity sweep
    if not detect_liquidity_sweep(five_min_candles, key_liquidity_level, side):
        logger.info("[GATE_FAIL] %s %s: gate=liquidity_sweep reason=no_sweep_detected", symbol, side.value)
        return None

    # Gate ④ — 5m MSS / ChoCh (with displacement filter per Blueprint §2.2)
    if not detect_market_structure_shift(five_min_candles, side, min_displacement_pct=effective_displacement):
        logger.info("[GATE_FAIL] %s %s: gate=mss reason=no_structure_shift", symbol, side.value)
        return None

    # Candles to use for FVG / OB detection (prefer 15m per Blueprint §2.1)
    scoring_candles = fifteen_min_candles if fifteen_min_candles else five_min_candles

    # Gate ⑥ — optional FVG check
    if check_fvg and not detect_fair_value_gap(scoring_candles, side):
        logger.info("[GATE_FAIL] %s %s: gate=fvg reason=no_fvg_detected", symbol, side.value)
        return None

    # Gate ⑦ — optional Order Block check
    if check_order_block and not detect_order_block(scoring_candles, side):
        logger.info("[GATE_FAIL] %s %s: gate=order_block reason=no_ob_detected", symbol, side.value)
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

    # Confidence scoring per BLUEPRINT §2.6: always check FVG and OB for scoring
    if len(four_hour_candles) >= 2:
        last_4h_rising = four_hour_candles[-1].close > four_hour_candles[-2].close
        direction_match = (side == Side.LONG and last_4h_rising) or (side == Side.SHORT and not last_4h_rising)
    else:
        direction_match = False

    fvg_present = detect_fair_value_gap(scoring_candles, side)
    ob_present = detect_order_block(scoring_candles, side)

    # Weighted confluence score (gates that passed earn their points)
    score = 0
    score += 20 if macro_bias == side else 0   # Gate ①
    score += 15                                 # Gate ② (zone — passed above)
    score += 20                                 # Gate ③ (sweep — passed above)
    score += 20                                 # Gate ④ (MSS — passed above)
    score += 10 if fvg_present else 0           # Gate ⑥
    score += 15 if ob_present else 0            # Gate ⑦

    if direction_match and fvg_present and ob_present:
        confidence = Confidence.HIGH
    elif direction_match:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

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
        confluence_score=score,
    )


def calculate_rsi(candles: list[CandleData], period: int = 14) -> float:
    """
    Calculate RSI over the last *period* candles.

    Returns 50.0 if there is insufficient data to compute the RSI.

    Parameters
    ----------
    candles:
        OHLCV candles (most-recent last).
    period:
        RSI look-back period (default 14).
    """
    if len(candles) < period + 1:
        return 50.0

    closes = [c.close for c in candles[-(period + 1):]]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def assess_macro_bias_relaxed(four_hour_candles: list[CandleData]) -> Optional[Side]:
    """
    4H-only bias assessment used by CH2 Medium Scalp and CH3 Easy Breakout.

    Returns LONG if at least 2 of the last 3 4H candles are bullish,
    SHORT if at least 2 of the last 3 are bearish, or None if mixed.

    This is a lighter-weight bias check that does not require 1D confluence,
    making it suitable for relaxed-gate channels.
    """
    if len(four_hour_candles) < 3:
        return None

    recent = four_hour_candles[-3:]
    bullish_count = sum(1 for c in recent if c.close > c.open)
    bearish_count = sum(1 for c in recent if c.close < c.open)

    if bullish_count >= 2:
        return Side.LONG
    if bearish_count >= 2:
        return Side.SHORT
    return None


def run_confluence_check_relaxed(
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
    news_window_minutes: int = 30,
    sweep_window: int = 10,
    mss_window: int = 10,
    fifteen_min_candles: Optional[list[CandleData]] = None,
    min_displacement_pct: Optional[float] = None,
    **kwargs,
) -> Optional[SignalResult]:
    """
    Relaxed confluence check for CH2 Medium Scalp.

    Differences from :func:`run_confluence_check`:

    - Gate ①: 4H-only bias (skip 1D requirement).
    - Gate ③: sweep window = *sweep_window* candles (default 10, not 7).
    - Gate ④: MSS window = *mss_window* candles (default 10, not 7 for CH1).
    - Gate ⑤: news window = *news_window_minutes* (default 30, not 60).
    - Gates ⑥⑦ (FVG / OB): always disabled.

    Parameters
    ----------
    news_window_minutes:
        The news blackout window passed in from the caller (default 30 min).
        When ``news_in_window`` is already pre-evaluated by the caller, this
        parameter is informational only; the caller supplies the bool.
    sweep_window:
        Number of recent 5m candles to inspect for a liquidity sweep.
    mss_window:
        Number of prior candles used when computing the swing high/low for
        the MSS check.
    fifteen_min_candles:
        Optional 15m candles used for FVG / OB scoring per Blueprint §2.1.
        Falls back to *five_min_candles* when not supplied.
    min_displacement_pct:
        Override the displacement filter for Gate ④.  When ``None``, the
        value from ``config.MIN_DISPLACEMENT_PCT`` (default 0.15) is used.
    """
    try:
        from config import MIN_DISPLACEMENT_PCT as _cfg_displacement
    except ImportError:
        _cfg_displacement = 0.15
    effective_displacement = min_displacement_pct if min_displacement_pct is not None else _cfg_displacement

    # Gate ⑤ — relaxed news blackout (30-min window instead of 60)
    if news_in_window:
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=news reason=high_impact_imminent",
            symbol, side.value,
        )
        return None

    # Gate ① — 4H-only macro bias
    macro_bias = assess_macro_bias_relaxed(four_hour_candles)
    if macro_bias != side:
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=macro_bias_4h reason=conflict bias=%s",
            symbol, side.value, macro_bias.value if macro_bias else "None",
        )
        return None

    # Gate ② — discount / premium zone (50% threshold — same as CH1)
    if side == Side.LONG and not is_discount_zone(current_price, range_low, range_high):
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=zone reason=price_not_in_discount",
            symbol, side.value,
        )
        return None
    if side == Side.SHORT and not is_premium_zone(current_price, range_low, range_high):
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=zone reason=price_not_in_premium",
            symbol, side.value,
        )
        return None

    # Gate ③ — liquidity sweep (wider window)
    sweep_candles = five_min_candles[-sweep_window:] if len(five_min_candles) >= sweep_window else five_min_candles
    # Temporarily override the sweep window by slicing; detect_liquidity_sweep always uses [-7:]
    # so we pass the already-sliced window and rely on the fact it checks [-7:] of what we give
    _sweep_check_candles = five_min_candles[-sweep_window:]
    if not any(
        (side == Side.LONG and c.low < key_liquidity_level and c.close > key_liquidity_level)
        or (side == Side.SHORT and c.high > key_liquidity_level and c.close < key_liquidity_level)
        for c in _sweep_check_candles
    ):
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=liquidity_sweep reason=no_sweep_in_%dc_window",
            symbol, side.value, sweep_window,
        )
        return None

    # Gate ④ — MSS using wider window (with displacement filter per Blueprint §2.2)
    mss_candles = five_min_candles[-(mss_window + 1):] if len(five_min_candles) >= mss_window + 1 else five_min_candles
    if not detect_market_structure_shift(mss_candles, side, min_displacement_pct=effective_displacement):
        logger.info(
            "[GATE_FAIL][RELAXED] %s %s: gate=mss reason=no_structure_shift",
            symbol, side.value,
        )
        return None

    # Candles to use for FVG / OB scoring (prefer 15m per Blueprint §2.1)
    scoring_candles = fifteen_min_candles if fifteen_min_candles else five_min_candles

    # All gates passed — build signal
    atr = calculate_atr(five_min_candles)
    entry_spread = atr * 0.5 if atr > 0 else abs(current_price * 0.001)
    entry_low = current_price - entry_spread
    entry_high = current_price + entry_spread

    tp1, tp2, tp3 = calculate_targets(current_price, stop_loss, side, tp1_rr, tp2_rr, tp3_rr)

    # Confidence scoring for relaxed check (no FVG/OB required)
    if len(four_hour_candles) >= 2:
        last_4h_rising = four_hour_candles[-1].close > four_hour_candles[-2].close
        direction_match = (side == Side.LONG and last_4h_rising) or (side == Side.SHORT and not last_4h_rising)
    else:
        direction_match = False

    fvg_present = detect_fair_value_gap(scoring_candles, side)
    ob_present = detect_order_block(scoring_candles, side)

    # Weighted confluence score
    score = 0
    score += 20 if macro_bias == side else 0   # Gate ①
    score += 15                                 # Gate ② (zone — passed above)
    score += 20                                 # Gate ③ (sweep — passed above)
    score += 20                                 # Gate ④ (MSS — passed above)
    score += 10 if fvg_present else 0           # Gate ⑥
    score += 15 if ob_present else 0            # Gate ⑦

    if direction_match and fvg_present and ob_present:
        confidence = Confidence.HIGH
    elif direction_match:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

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
        structure_note=structure_note or f"4H {'Bullish' if side == Side.LONG else 'Bearish'} Structure + 5m MSS (Relaxed).",
        context_note=context_note or f"{symbol} aligned with 4H bias (medium scalp).",
        leverage_min=leverage_min,
        leverage_max=leverage_max,
        signal_id=sig_id,
        confluence_score=score,
    )
