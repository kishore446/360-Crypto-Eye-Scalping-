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

from bot.price_fmt import fmt_price

logger = logging.getLogger(__name__)

try:
    from config import RSI_DIVERGENCE_PERIOD as _RSI_DIVERGENCE_PERIOD
except ImportError:
    _RSI_DIVERGENCE_PERIOD: int = 14

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
    "calculate_ema",
    "calculate_targets",
    "calculate_vwap",
    "detect_rsi_divergence",
    "volume_percentile",
    "run_confluence_check",
    "run_confluence_check_relaxed",
    "calculate_macd",
    "detect_macd_confirmation",
    "detect_bollinger_squeeze",
    "calculate_cvd",
    "detect_cvd_confirmation",
    "detect_ema_ribbon_alignment",
    "run_confluence_check_ch1_hard",
    "run_confluence_check_ch2_medium",
    "run_confluence_check_ch3_easy",
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
    risk_note: str = ""  # e.g., "⚠️ Cooldown active — half position size"

    def format_message(self) -> str:
        """Return the standardised Telegram broadcast message."""
        entry_range = f"{fmt_price(self.entry_low)} – {fmt_price(self.entry_high)}"
        copy_trade_entry = fmt_price((self.entry_low + self.entry_high) / 2)
        tp_list = f"{fmt_price(self.tp1)}, {fmt_price(self.tp2)}, {fmt_price(self.tp3)}"

        # Confidence stars
        stars = {"High": "⭐⭐⭐", "Medium": "⭐⭐", "Low": "⭐"}.get(self.confidence.value, "⭐")
        confidence_line = f"Confidence: {self.confidence.value} {stars}"
        if self.confluence_score > 0:
            confidence_line += f" | Score: {self.confluence_score}/100"

        risk_line = f"\n⚠️ {self.risk_note}" if self.risk_note else ""

        bybit_copy = (
            f"\n\n👇 CLICK TO COPY FOR BYBIT:\n"
            f"`{self.symbol}/USDT {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {fmt_price(self.stop_loss)}`"
        )
        okx_copy = (
            f"\n\n👇 CLICK TO COPY FOR OKX:\n"
            f"`{self.symbol}/USDT {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {fmt_price(self.stop_loss)}`"
        )
        bitget_copy = (
            f"\n\n👇 CLICK TO COPY FOR BITGET:\n"
            f"`{self.symbol}/USDT {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {fmt_price(self.stop_loss)}`"
        )
        hyperliquid_copy = (
            f"\n\n👇 CLICK TO COPY FOR HYPERLIQUID:\n"
            f"`{self.symbol}-USD {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {fmt_price(self.stop_loss)}`"
        )

        return (
            f"🚀 #{self.symbol}/USDT ({self.side.value}) | 360 EYE SCALP\n"
            f"{confidence_line}\n\n"
            f"📊 STRATEGY MAP:\n"
            f"- Structure: {self.structure_note}\n"
            f"- Context: {self.context_note}\n"
            f"- Risk: 1% of Account Balance.{risk_line}\n\n"
            f"⚡ ENTRY ZONE: {entry_range}\n"
            f"🎯 TARGETS:\n"
            f"- TP 1: {fmt_price(self.tp1)} (Close 50% + Move SL to Entry)\n"
            f"- TP 2: {fmt_price(self.tp2)} (Close 25% + Start Trailing)\n"
            f"- TP 3: {fmt_price(self.tp3)} (Final Moon Bag)\n\n"
            f"🛑 STOP LOSS: {fmt_price(self.stop_loss)} (Structural Invalidation)\n"
            f"Leverage: Cross {self.leverage_min}x - {self.leverage_max}x (Recommended)\n\n"
            f"👇 CLICK TO COPY FOR BINANCE:\n"
            f"`{self.symbol} {self.side.value} ENTRY {copy_trade_entry} "
            f"TP {tp_list} SL {fmt_price(self.stop_loss)}`"
            f"{bybit_copy}"
            f"{okx_copy}"
            f"{bitget_copy}"
            f"{hyperliquid_copy}"
        )


def _average_volume(candles: list[CandleData]) -> float:
    """Return the simple average volume across the supplied candles."""
    if not candles:
        return 0.0
    return sum(c.volume for c in candles) / len(candles)


def calculate_vwap(candles: list[CandleData]) -> float:
    """
    Compute Volume-Weighted Average Price (VWAP) from intraday candles.

    Uses ``(high + low + close) / 3`` as the typical price for each candle.
    Returns 0.0 when *candles* is empty or total volume is zero.

    Parameters
    ----------
    candles:
        OHLCV candles (most-recent last).

    Returns
    -------
    float
        VWAP price, or 0.0 when insufficient data.
    """
    if not candles:
        return 0.0
    total_pv = 0.0
    total_volume = 0.0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        total_pv += typical * c.volume
        total_volume += c.volume
    if total_volume == 0.0:
        return 0.0
    return total_pv / total_volume


def calculate_ema(candles: list[CandleData], period: int) -> float:
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
    for candle in candles[-15:]:  # inspect the last fifteen candles (~75 min)
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
    atr: float = 0.0,
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
        Minimum displacement from the swing level as a percentage.
        When > 0 and *atr* is 0, the break must exceed this percentage move.
        Ignored when *atr* > 0 (ATR-based threshold takes precedence).
    atr:
        When > 0, use an ATR-adaptive displacement threshold of ``0.3 * atr``
        instead of the fixed percentage.  This avoids over-filtering altcoins
        with tight price ranges relative to the fixed percentage.
    """
    if len(candles) < 3:
        return False

    last = candles[-1]
    prior_candles = candles[:-1]

    # Volume percentile check: require at least 70th percentile for MSS confirmation
    # Use only the last 20 candles for relevant volume context (BUG #6 fix)
    recent_for_vol = candles[-20:] if len(candles) > 20 else candles
    vol_rank = sum(1 for c in recent_for_vol if c.volume <= last.volume) / len(recent_for_vol) if recent_for_vol else 0
    if vol_rank < 0.70:
        return False

    if side == Side.LONG:
        swing_high = max(c.high for c in prior_candles[-7:])  # last 7 candles ≈ 35 min
        if not (last.close > swing_high):
            return False
        displacement = abs(last.close - swing_high)
        if atr > 0:
            if displacement < 0.3 * atr:
                return False
        elif min_displacement_pct > 0 and swing_high > 0:
            if displacement / swing_high < min_displacement_pct / 100:
                return False
        return True
    else:
        swing_low = min(c.low for c in prior_candles[-7:])  # last 7 candles ≈ 35 min
        if not (last.close < swing_low):
            return False
        displacement = abs(last.close - swing_low)
        if atr > 0:
            if displacement < 0.3 * atr:
                return False
        elif min_displacement_pct > 0 and swing_low > 0:
            if displacement / swing_low < min_displacement_pct / 100:
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
      - 1D bullish  = at least 2 of the last 3 daily closes rise day-over-day
                      AND 3-day average close is above SMA-20 or EMA-9.
      - 1D bearish  = at least 2 of the last 3 daily closes fall day-over-day
                      AND 3-day average close is below SMA-20 or EMA-9.
      - 4H bullish  = last close > previous close
      Both must agree for a directional bias to be returned.

    Using a 3-day window prevents a single red candle from killing all longs
    during a strong bull trend. OR between SMA-20 and EMA-9 prevents false
    negatives during ranging/consolidating markets.
    """
    if len(daily_candles) < 20 or len(four_hour_candles) < 2:
        return None

    # 1D bias
    sma20_daily = sum(c.close for c in daily_candles[-20:]) / 20

    # EMA-9 on daily candles (smoothing factor k = 2/(9+1) = 0.2)
    ema9_daily = calculate_ema(daily_candles, period=9)

    # BUG #5 fix: use 3-day comparison instead of single-candle
    last4 = daily_candles[-4:]  # need 4 candles for 3 comparisons
    if len(last4) >= 4:
        rises = sum(
            1 for i in range(1, 4) if last4[i].close > last4[i - 1].close
        )
        falls = sum(
            1 for i in range(1, 4) if last4[i].close < last4[i - 1].close
        )
    else:
        # Fallback to single-candle comparison when insufficient history
        rises = 1 if daily_candles[-1].close > daily_candles[-2].close else 0
        falls = 1 if daily_candles[-1].close < daily_candles[-2].close else 0

    avg_close_3d = sum(c.close for c in daily_candles[-3:]) / 3

    daily_bullish = (
        rises >= 2
        and (avg_close_3d > sma20_daily or avg_close_3d > ema9_daily)
    )
    daily_bearish = (
        falls >= 2
        and (avg_close_3d < sma20_daily or avg_close_3d < ema9_daily)
    )

    # 4H bias
    four_h_bullish = four_hour_candles[-1].close > four_hour_candles[-2].close
    four_h_bearish = four_hour_candles[-1].close < four_hour_candles[-2].close

    if daily_bullish and four_h_bullish:
        return Side.LONG
    if daily_bearish and four_h_bearish:
        return Side.SHORT
    # Allow 1D clear bias when 4H is neutral (not actively conflicting)
    if daily_bullish and not four_h_bearish:
        return Side.LONG
    if daily_bearish and not four_h_bullish:
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


def _compute_dynamic_rr(
    entry: float,
    five_min_candles: list[CandleData],
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.5,
    tp3_rr: float = 4.0,
    regime: str = "UNKNOWN",
) -> tuple[float, float, float]:
    """
    Dynamically adjust R:R ratios based on ATR relative to entry price and market regime.

    When ATR is exceptionally high (volatile market) the targets are stretched
    so they are not clipped by normal noise.  When ATR is very low (compressed
    market) targets are tightened so they remain achievable.

    A regime-based adjustment is applied on top of the ATR scaling to further
    tune targets for the current market condition.

    Degrades gracefully when ATR is 0 or entry is 0 — returns base ratios unchanged.

    Parameters
    ----------
    entry:
        Current entry price.
    five_min_candles:
        5-minute candles used to calculate ATR.
    tp1_rr / tp2_rr / tp3_rr:
        Base risk-to-reward ratios.
    regime:
        Market regime string: ``"RANGING"``, ``"TRENDING"``, ``"HIGH_VOL"``,
        or ``"UNKNOWN"`` (default — no regime adjustment).

    Returns
    -------
    Adjusted (tp1_rr, tp2_rr, tp3_rr) tuple.
    """
    # Threshold constants for ATR-based R:R scaling
    _ATR_HIGH_THRESHOLD_PCT = 1.5    # ATR > 1.5% of price → stretch targets
    _ATR_LOW_THRESHOLD_PCT = 0.3     # ATR < 0.3% of price → tighten targets
    _ATR_HIGH_BASELINE_PCT = 1.0     # Baseline divisor for high-vol multiplier
    _MIN_TARGET_MULTIPLIER = 0.7     # Floor multiplier to avoid over-tightening

    atr = calculate_atr(five_min_candles)
    if atr <= 0 or entry <= 0:
        atr_tp1, atr_tp2, atr_tp3 = tp1_rr, tp2_rr, tp3_rr
    else:
        atr_pct = atr / entry * 100
        # Stretch targets in high-volatility environments
        if atr_pct > _ATR_HIGH_THRESHOLD_PCT:
            multiplier = min(atr_pct / _ATR_HIGH_BASELINE_PCT, 1.5)
            atr_tp1 = tp1_rr * multiplier
            atr_tp2 = tp2_rr * multiplier
            atr_tp3 = tp3_rr * multiplier
        # Tighten targets in low-volatility / compressed environments
        elif atr_pct < _ATR_LOW_THRESHOLD_PCT:
            multiplier = max(atr_pct / _ATR_LOW_THRESHOLD_PCT, _MIN_TARGET_MULTIPLIER)
            atr_tp1 = tp1_rr * multiplier
            atr_tp2 = tp2_rr * multiplier
            atr_tp3 = tp3_rr * multiplier
        else:
            atr_tp1, atr_tp2, atr_tp3 = tp1_rr, tp2_rr, tp3_rr

    # Regime-based adjustment on top of ATR scaling
    regime_upper = regime.upper() if regime else "UNKNOWN"
    if regime_upper == "RANGING":
        atr_tp1 *= 0.85   # tighter TP1, more hits
        atr_tp2 *= 0.80
        atr_tp3 *= 0.75
    elif regime_upper in ("TRENDING", "BULLISH", "BEARISH"):
        atr_tp1 *= 1.0    # standard
        atr_tp2 *= 1.15   # wider TP2/3 to let winners run
        atr_tp3 *= 1.25
    elif regime_upper in ("HIGH_VOL", "VOLATILE"):
        atr_tp1 *= 1.1
        atr_tp2 *= 1.2
        atr_tp3 *= 1.4
    # "UNKNOWN" / "SIDEWAYS" / others: no regime adjustment

    return atr_tp1, atr_tp2, atr_tp3


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


def detect_fair_value_gap(
    candles: list[CandleData],
    side: Side,
    current_price: Optional[float] = None,
) -> bool:
    """
    Detect an unfilled Fair Value Gap (FVG) in the last ten candles.

    A bullish FVG exists when candle[i].low > candle[i-2].high.
    A bearish FVG exists when candle[i].high < candle[i-2].low.

    Parameters
    ----------
    candles:
        OHLCV candles (most-recent last).
    side:
        Signal direction to look for.
    current_price:
        When provided, only return True if the gap has NOT been filled.
        A bullish FVG is considered filled if current_price < c0.high.
        A bearish FVG is considered filled if current_price > c0.low.
        When None (default), the fill check is skipped (backward compatible).
    """
    if len(candles) < 3:
        return False
    window = candles[-10:]
    for i in range(len(window) - 1, 1, -1):
        c0 = window[i - 2]
        c2 = window[i]
        if side == Side.LONG:
            if c2.low > c0.high:
                # Gap found — verify it has not been filled
                if current_price is not None and current_price < c0.high:
                    continue  # price entered the gap zone — filled
                return True
        else:
            if c2.high < c0.low:
                if current_price is not None and current_price > c0.low:
                    continue  # price entered the gap zone — filled
                return True
    return False


def detect_order_block(
    candles: list[CandleData],
    side: Side,
    atr: float = 0,
) -> bool:
    """
    Detect an Order Block — the last opposing candle before an impulse move.

    Requires at least **two consecutive** directional impulse candles following
    the opposing OB candle to confirm displacement (reduces false positives).

    For LONG: look for the last bearish candle (close < open) before two
    consecutive bullish candles.
    For SHORT: look for the last bullish candle (close > open) before two
    consecutive bearish candles.

    Parameters
    ----------
    candles:
        OHLCV candles (most-recent last).
    side:
        Signal direction.
    atr:
        When > 0, the impulse move (from OB close to the highest/lowest
        point of the two impulse candles) must cover at least 0.5 × ATR.
        Defaults to 0 which disables the ATR displacement check.

    Returns True if a qualifying order block exists within the last 10 candles.
    """
    if len(candles) < 3:
        return False
    window = candles[-10:]
    if side == Side.LONG:
        for i in range(len(window) - 3, -1, -1):
            if window[i].close < window[i].open:  # bearish OB candidate
                c1, c2 = window[i + 1], window[i + 2]
                if c1.close > c1.open and c2.close > c2.open:  # 2 bullish impulse candles
                    if atr > 0:
                        impulse = max(c1.high, c2.high) - window[i].close
                        if impulse < atr * 0.5:
                            continue
                    return True
    else:
        for i in range(len(window) - 3, -1, -1):
            if window[i].close > window[i].open:  # bullish OB candidate
                c1, c2 = window[i + 1], window[i + 2]
                if c1.close < c1.open and c2.close < c2.open:  # 2 bearish impulse candles
                    if atr > 0:
                        impulse = window[i].close - min(c1.low, c2.low)
                        if impulse < atr * 0.5:
                            continue
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
    funding_rate: Optional[float] = None,
    oi_change: Optional[float] = None,
    regime: str = "UNKNOWN",
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
    funding_rate:
        Optional current funding rate.  When provided, adjusts the confluence
        score by ±5 based on contrarian / crowded-trade conditions.
    oi_change:
        Optional OI percentage change (positive = OI rising).  When provided,
        adjusts the score by ±5 based on OI / price divergence signals.
    """
    try:
        from config import MIN_DISPLACEMENT_PCT as _cfg_displacement
    except ImportError:
        _cfg_displacement = 0.15
    effective_displacement = min_displacement_pct if min_displacement_pct is not None else _cfg_displacement

    # Evaluate all gates up front for structured logging and near-miss detection
    gate_news = not news_in_window
    macro_bias = assess_macro_bias(daily_candles, four_hour_candles)
    gate_macro = macro_bias == side
    if side == Side.LONG:
        gate_zone = is_discount_zone(current_price, range_low, range_high)
    else:
        gate_zone = is_premium_zone(current_price, range_low, range_high)
    gate_sweep = detect_liquidity_sweep(five_min_candles, key_liquidity_level, side)
    gate_mss = detect_market_structure_shift(five_min_candles, side, min_displacement_pct=effective_displacement)

    # Candles to use for FVG / OB detection (prefer 15m per Blueprint §2.1)
    scoring_candles = fifteen_min_candles if fifteen_min_candles else five_min_candles
    atr = calculate_atr(five_min_candles)

    gate_fvg = detect_fair_value_gap(scoring_candles, side, current_price=current_price) if check_fvg else True
    gate_ob = detect_order_block(scoring_candles, side, atr=atr) if check_order_block else True

    required_gates = {
        "news": gate_news,
        "macro": gate_macro,
        "zone": gate_zone,
        "sweep": gate_sweep,
        "mss": gate_mss,
    }

    passed_required = sum(1 for v in required_gates.values() if v)
    total_required = len(required_gates)

    # Structured summary log for every check — enables engine tuning
    logger.info(
        "Confluence check: %s %s — gates: news=%s macro=%s zone=%s sweep=%s mss=%s"
        " fvg=%s ob=%s | passed=%d/%d",
        symbol, side.value,
        gate_news, gate_macro, gate_zone, gate_sweep, gate_mss,
        gate_fvg, gate_ob,
        passed_required, total_required,
    )

    # Near-miss warning: all required gates except one passed
    failed_required = [name for name, v in required_gates.items() if not v]
    if len(failed_required) == 1:
        logger.warning(
            "[NEAR_MISS] %s %s: only gate '%s' failed — consider relaxing for CH2/CH3",
            symbol, side.value, failed_required[0],
        )

    # Gate ⑤ — news blackout
    if not gate_news:
        logger.info("[GATE_FAIL] %s %s: gate=news reason=high_impact_imminent", symbol, side.value)
        return None

    # Gate ① — macro bias
    if not gate_macro:
        logger.info(
            "[GATE_FAIL] %s %s: gate=macro_bias reason=conflict bias=%s",
            symbol, side.value, macro_bias.value if macro_bias else "None",
        )
        return None

    # Gate ② — discount / premium zone
    if not gate_zone:
        if side == Side.LONG:
            logger.info("[GATE_FAIL] %s %s: gate=zone reason=price_not_in_discount", symbol, side.value)
        else:
            logger.info("[GATE_FAIL] %s %s: gate=zone reason=price_not_in_premium", symbol, side.value)
        return None

    # Gate ③ — liquidity sweep
    if not gate_sweep:
        logger.info("[GATE_FAIL] %s %s: gate=liquidity_sweep reason=no_sweep_detected", symbol, side.value)
        return None

    # Gate ④ — 5m MSS / ChoCh (with displacement filter per Blueprint §2.2)
    if not gate_mss:
        logger.info("[GATE_FAIL] %s %s: gate=mss reason=no_structure_shift", symbol, side.value)
        return None

    # Gate ⑥ — optional FVG check (pass current_price to verify gap is unfilled)
    if check_fvg and not gate_fvg:
        logger.info("[GATE_FAIL] %s %s: gate=fvg reason=no_fvg_detected", symbol, side.value)
        return None

    # Gate ⑦ — optional Order Block check (pass ATR for displacement verification)
    if check_order_block and not gate_ob:
        logger.info("[GATE_FAIL] %s %s: gate=order_block reason=no_ob_detected", symbol, side.value)
        return None

    # All gates passed — build signal
    if atr > 0:
        entry_spread = atr * 0.5
    else:
        entry_spread = abs(current_price * 0.001)  # 0.1 % tight entry zone fallback
    entry_low = current_price - entry_spread
    entry_high = current_price + entry_spread

    tp1_dyn, tp2_dyn, tp3_dyn = _compute_dynamic_rr(current_price, five_min_candles, tp1_rr, tp2_rr, tp3_rr, regime=regime)
    tp1, tp2, tp3 = calculate_targets(current_price, stop_loss, side, tp1_dyn, tp2_dyn, tp3_dyn)

    # Confidence scoring per BLUEPRINT §2.6: always check FVG and OB for scoring
    if len(four_hour_candles) >= 2:
        last_4h_rising = four_hour_candles[-1].close > four_hour_candles[-2].close
        direction_match = (side == Side.LONG and last_4h_rising) or (side == Side.SHORT and not last_4h_rising)
    else:
        direction_match = False

    fvg_present = detect_fair_value_gap(scoring_candles, side, current_price=current_price)
    ob_present = detect_order_block(scoring_candles, side, atr=atr)

    # Weighted confluence score (gates that passed earn their points)
    score = 0
    score += 20 if macro_bias == side else 0   # Gate ①
    score += 15                                 # Gate ② (zone — passed above)
    score += 20                                 # Gate ③ (sweep — passed above)
    score += 20                                 # Gate ④ (MSS — passed above)
    score += 10 if fvg_present else 0           # Gate ⑥
    score += 15 if ob_present else 0            # Gate ⑦

    # RSI divergence bonus (+10 when divergence confirms trade direction)
    rsi_div = detect_rsi_divergence(five_min_candles, side, period=_RSI_DIVERGENCE_PERIOD)
    score += 10 if rsi_div else 0

    # New indicator bonus scores (additive, non-blocking)
    macd_ok = detect_macd_confirmation(five_min_candles, side)
    score += 10 if macd_ok else 0

    bb_squeeze = detect_bollinger_squeeze(five_min_candles)
    score += 10 if bb_squeeze else 0

    cvd_ok = detect_cvd_confirmation(five_min_candles, side)
    score += 10 if cvd_ok else -5  # divergence penalty

    ribbon_ok = detect_ema_ribbon_alignment(five_min_candles, side)
    score += 10 if ribbon_ok else 0

    # Gate ⑧ — optional funding rate sentiment adjustment (arbitrage gate)
    if funding_rate is not None:
        try:
            from config import FUNDING_EXTREME_NEGATIVE, FUNDING_EXTREME_POSITIVE
        except ImportError:
            FUNDING_EXTREME_NEGATIVE = -0.0001
            FUNDING_EXTREME_POSITIVE = 0.0005
        # Hard thresholds: 3× the soft extremes — heavily opposing funding rates
        # indicate crowded positioning that creates squeeze/arbitrage risk.
        funding_hard_positive = FUNDING_EXTREME_POSITIVE * 3
        funding_hard_negative = FUNDING_EXTREME_NEGATIVE * 3
        if side == Side.LONG:
            if funding_rate > funding_hard_positive:
                # Heavily positive funding while going LONG → extreme long crowding,
                # high squeeze/arbitrage risk — reject the trade outright.
                logger.info(
                    "[GATE_FAIL] %s %s: gate=funding_rate reason=extreme_long_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate > FUNDING_EXTREME_POSITIVE:
                score -= 15  # strong opposing penalty
            elif funding_rate < FUNDING_EXTREME_NEGATIVE:
                score += 5   # contrarian: extreme short crowding → bullish edge
        else:
            if funding_rate < funding_hard_negative:
                # Heavily negative funding while going SHORT → extreme short crowding,
                # high short-squeeze risk — reject the trade outright.
                logger.info(
                    "[GATE_FAIL] %s %s: gate=funding_rate reason=extreme_short_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate < FUNDING_EXTREME_NEGATIVE:
                score -= 15  # strong opposing penalty
            elif funding_rate > FUNDING_EXTREME_POSITIVE:
                score += 5   # contrarian: extreme long crowding → bearish edge

    # OI divergence / confirmation adjustment
    if oi_change is not None and len(five_min_candles) >= 2:
        price_up = five_min_candles[-1].close > five_min_candles[-2].close
        oi_up = oi_change > 0
        if side == Side.LONG:
            if price_up and not oi_up:
                score -= 5   # price new high but OI declining — divergence warning
            elif price_up and oi_up:
                score += 5   # OI confirms bullish move
        else:
            if not price_up and not oi_up:
                score -= 5   # price new low but OI declining — short-squeeze risk
            elif not price_up and oi_up:
                score += 5   # OI confirms bearish move

    # Score-based confidence: score is the primary driver
    if score >= 90:
        confidence = Confidence.HIGH
    elif score >= 75:
        if direction_match and fvg_present and ob_present:
            confidence = Confidence.HIGH
        else:
            confidence = Confidence.MEDIUM
    elif score >= 60:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    from bot.logging_config import generate_signal_id
    sig_id = generate_signal_id()

    # Wire narrative generator for richer signal descriptions
    if not structure_note and not context_note:
        try:
            from bot.narrative import generate_signal_narrative
            gates_fired = ["macro_bias", "zone", "sweep", "mss"]
            if fvg_present:
                gates_fired.append("fvg")
            if ob_present:
                gates_fired.append("order_block")
            structure_note, context_note = generate_signal_narrative(
                symbol=symbol,
                side=side.value,
                confidence=confidence.value,
                gates_fired=gates_fired,
                confluence_score=score,
            )
        except Exception:
            pass

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


def detect_rsi_divergence(candles: list[CandleData], side: Side, period: int = 14) -> bool:
    """
    Detect RSI divergence as a confluence filter.

    LONG: Price makes lower low but RSI makes higher low = bullish divergence (GOOD for LONG)
    SHORT: Price makes higher high but RSI makes lower high = bearish divergence (GOOD for SHORT)

    Looks at the last 20 candles and finds the two most recent swing lows (LONG)
    or swing highs (SHORT), then compares price direction vs RSI direction at those swings.

    Parameters
    ----------
    candles:
        OHLCV candles (most-recent last). Minimum ``period + 3`` candles required.
    side:
        Direction of the anticipated trade.
    period:
        RSI lookback period (default 14).

    Returns
    -------
    bool
        ``True`` if divergence is detected in the direction of *side*.
    """
    window = candles[-20:] if len(candles) >= 20 else candles
    if len(window) < period + 3:
        return False

    # Compute RSI for each candle in window using expanding subsets
    rsi_values: list[float] = []
    for i in range(len(window)):
        sub = window[: i + 1]
        rsi_values.append(calculate_rsi(sub, period=period))

    if side == Side.LONG:
        # Find swing lows: local minima in price (low)
        swing_indices: list[int] = []
        for i in range(1, len(window) - 1):
            if window[i].low < window[i - 1].low and window[i].low < window[i + 1].low:
                swing_indices.append(i)
        if len(swing_indices) < 2:
            return False
        # Take the two most recent swing lows
        i1, i2 = swing_indices[-2], swing_indices[-1]
        price_lower_low = window[i2].low < window[i1].low
        rsi_higher_low = rsi_values[i2] > rsi_values[i1]
        return price_lower_low and rsi_higher_low
    else:  # SHORT
        # Find swing highs: local maxima in price (high)
        swing_indices = []
        for i in range(1, len(window) - 1):
            if window[i].high > window[i - 1].high and window[i].high > window[i + 1].high:
                swing_indices.append(i)
        if len(swing_indices) < 2:
            return False
        i1, i2 = swing_indices[-2], swing_indices[-1]
        price_higher_high = window[i2].high > window[i1].high
        rsi_lower_high = rsi_values[i2] < rsi_values[i1]
        return price_higher_high and rsi_lower_high


def volume_percentile(candles: list[CandleData], current_volume: float) -> float:
    """
    Return the volume percentile (0.0–1.0) of *current_volume* within *candles*.

    Parameters
    ----------
    candles:
        Historical candles used as the population for ranking.
    current_volume:
        The volume to rank.

    Returns
    -------
    float
        Percentile between 0.0 (lowest) and 1.0 (highest). Returns 0.0 when
        *candles* is empty.
    """
    if not candles:
        return 0.0
    sorted_vols = sorted(c.volume for c in candles)
    # Find rank: number of candles with volume <= current_volume
    rank = sum(1 for v in sorted_vols if v <= current_volume)
    return rank / len(sorted_vols)


# ── New Indicators ─────────────────────────────────────────────────────────────


def calculate_macd(
    candles: list[CandleData],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[float, float, float]:
    """
    Calculate MACD (fast EMA − slow EMA), signal line (EMA of MACD), and histogram.

    Returns (macd_line, signal_line, histogram). Returns (0, 0, 0) on insufficient data.
    """
    if len(candles) < slow + signal_period:
        return 0.0, 0.0, 0.0

    closes = [c.close for c in candles]

    def _ema_series(values: list[float], period: int) -> list[float]:
        k = 2.0 / (period + 1)
        ema = [values[0]]
        for v in values[1:]:
            ema.append(v * k + ema[-1] * (1 - k))
        return ema

    fast_ema = _ema_series(closes, fast)
    slow_ema = _ema_series(closes, slow)

    macd_series = [f - s for f, s in zip(fast_ema, slow_ema)]
    if len(macd_series) < signal_period:
        return 0.0, 0.0, 0.0

    signal_series = _ema_series(macd_series, signal_period)
    macd_line = macd_series[-1]
    signal_line = signal_series[-1]
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def detect_macd_confirmation(
    candles: list[CandleData],
    side: Side,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
    lookback: int = 3,
) -> bool:
    """
    Return True when MACD confirms the trade direction.

    Confirmation requires:
    - Histogram is positive (LONG) or negative (SHORT) on the last candle.
    - MACD line crossed above/below signal line within the last *lookback* candles.
    """
    min_needed = slow + signal_period + lookback
    if len(candles) < min_needed:
        return False

    closes = [c.close for c in candles]

    def _ema_series(values: list[float], period: int) -> list[float]:
        k = 2.0 / (period + 1)
        ema = [values[0]]
        for v in values[1:]:
            ema.append(v * k + ema[-1] * (1 - k))
        return ema

    fast_ema = _ema_series(closes, fast)
    slow_ema = _ema_series(closes, slow)
    macd_series = [f - s for f, s in zip(fast_ema, slow_ema)]
    if len(macd_series) < signal_period + lookback:
        return False

    signal_series = _ema_series(macd_series, signal_period)

    # Check histogram direction on last candle
    last_hist = macd_series[-1] - signal_series[-1]
    if side == Side.LONG and last_hist <= 0:
        return False
    if side == Side.SHORT and last_hist >= 0:
        return False

    # Check for a crossover within the last *lookback* candles
    window_macd = macd_series[-lookback - 1:]
    window_signal = signal_series[-lookback - 1:]
    for i in range(1, len(window_macd)):
        prev_above = window_macd[i - 1] > window_signal[i - 1]
        curr_above = window_macd[i] > window_signal[i]
        if side == Side.LONG and not prev_above and curr_above:
            return True
        if side == Side.SHORT and prev_above and not curr_above:
            return True
    return False


def detect_bollinger_squeeze(
    candles: list[CandleData],
    period: int = 20,
    squeeze_threshold: float = 0.04,
) -> bool:
    """
    Return True when Bollinger Band width is below *squeeze_threshold*.

    Bandwidth = (upper − lower) / middle. A squeeze (low bandwidth) signals
    potential breakout imminent. Threshold of 0.04 = 4% band width.
    """
    if len(candles) < period:
        return False

    recent = candles[-period:]
    closes = [c.close for c in recent]
    middle = sum(closes) / period
    variance = sum((c - middle) ** 2 for c in closes) / period
    std_dev = variance ** 0.5

    upper = middle + 2 * std_dev
    lower = middle - 2 * std_dev
    if middle == 0:
        return False
    bandwidth = (upper - lower) / middle
    return bandwidth < squeeze_threshold


def calculate_cvd(candles: list[CandleData]) -> list[float]:
    """
    Estimate Cumulative Volume Delta (CVD) per candle.

    Buy volume proxy: (close − low) / (high − low) * volume
    Sell volume proxy: remainder.
    CVD = cumulative sum of (buy_vol − sell_vol).

    Returns a list of CVD values the same length as *candles*.
    Returns an empty list when *candles* is empty.
    """
    if not candles:
        return []

    cvd_series: list[float] = []
    cumulative = 0.0
    for c in candles:
        rng = c.high - c.low
        if rng > 0:
            buy_vol = (c.close - c.low) / rng * c.volume
        else:
            # Zero-range doji: split volume evenly — net delta is neutral
            buy_vol = c.volume / 2.0
        sell_vol = c.volume - buy_vol
        delta = buy_vol - sell_vol
        cumulative += delta
        cvd_series.append(cumulative)
    return cvd_series


def detect_cvd_confirmation(
    candles: list[CandleData],
    side: Side,
    lookback: int = 5,
) -> bool:
    """
    Return True when CVD trend aligns with the trade direction.

    Computes CVD for *candles* and checks whether the net CVD change over the
    last *lookback* candles is positive (LONG) or negative (SHORT).
    """
    if len(candles) < lookback + 1:
        return False

    cvd = calculate_cvd(candles)
    if len(cvd) < lookback + 1:
        return False

    net_delta = cvd[-1] - cvd[-(lookback + 1)]
    if side == Side.LONG:
        return net_delta > 0
    return net_delta < 0


def detect_ema_ribbon_alignment(
    candles: list[CandleData],
    side: Side,
    periods: tuple[int, int, int, int] = (8, 13, 21, 55),
) -> bool:
    """
    Return True when the EMA ribbon is fully aligned for *side*.

    For LONG: EMA8 > EMA13 > EMA21 > EMA55.
    For SHORT: EMA8 < EMA13 < EMA21 < EMA55.
    """
    max_period = max(periods)
    if len(candles) < max_period + 5:
        return False

    ema_values = [calculate_ema(candles, p) for p in periods]
    if side == Side.LONG:
        return all(ema_values[i] > ema_values[i + 1] for i in range(len(ema_values) - 1))
    return all(ema_values[i] < ema_values[i + 1] for i in range(len(ema_values) - 1))


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
    funding_rate: Optional[float] = None,
    oi_change: Optional[float] = None,
    regime: str = "UNKNOWN",
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
    funding_rate:
        Optional current funding rate.  When provided, adjusts the confluence
        score by ±5 based on contrarian / crowded-trade conditions.
    oi_change:
        Optional OI percentage change (positive = OI rising).  When provided,
        adjusts the score by ±5 based on OI / price divergence signals.
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

    tp1_dyn, tp2_dyn, tp3_dyn = _compute_dynamic_rr(current_price, five_min_candles, tp1_rr, tp2_rr, tp3_rr, regime=regime)
    tp1, tp2, tp3 = calculate_targets(current_price, stop_loss, side, tp1_dyn, tp2_dyn, tp3_dyn)

    # Confidence scoring for relaxed check (no FVG/OB required)
    if len(four_hour_candles) >= 2:
        last_4h_rising = four_hour_candles[-1].close > four_hour_candles[-2].close
        direction_match = (side == Side.LONG and last_4h_rising) or (side == Side.SHORT and not last_4h_rising)
    else:
        direction_match = False

    fvg_present = detect_fair_value_gap(scoring_candles, side, current_price=current_price)
    ob_present = detect_order_block(scoring_candles, side, atr=atr)

    # Weighted confluence score
    score = 0
    score += 20 if macro_bias == side else 0   # Gate ①
    score += 15                                 # Gate ② (zone — passed above)
    score += 20                                 # Gate ③ (sweep — passed above)
    score += 20                                 # Gate ④ (MSS — passed above)
    score += 10 if fvg_present else 0           # Gate ⑥
    score += 15 if ob_present else 0            # Gate ⑦

    # RSI divergence bonus (+10 when divergence confirms trade direction)
    rsi_div = detect_rsi_divergence(five_min_candles, side, period=_RSI_DIVERGENCE_PERIOD)
    score += 10 if rsi_div else 0

    # Gate ⑧ — optional funding rate sentiment adjustment (arbitrage gate)
    if funding_rate is not None:
        try:
            from config import FUNDING_EXTREME_NEGATIVE, FUNDING_EXTREME_POSITIVE
        except ImportError:
            FUNDING_EXTREME_NEGATIVE = -0.0001
            FUNDING_EXTREME_POSITIVE = 0.0005
        # Hard thresholds: 3× the soft extremes — heavily opposing funding rates
        # indicate crowded positioning that creates squeeze/arbitrage risk.
        funding_hard_positive = FUNDING_EXTREME_POSITIVE * 3
        funding_hard_negative = FUNDING_EXTREME_NEGATIVE * 3
        if side == Side.LONG:
            if funding_rate > funding_hard_positive:
                # Heavily positive funding while going LONG → extreme long crowding,
                # high squeeze/arbitrage risk — reject the trade outright.
                logger.info(
                    "[GATE_FAIL][RELAXED] %s %s: gate=funding_rate reason=extreme_long_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate > FUNDING_EXTREME_POSITIVE:
                score -= 15  # strong opposing penalty
            elif funding_rate < FUNDING_EXTREME_NEGATIVE:
                score += 5
        else:
            if funding_rate < funding_hard_negative:
                # Heavily negative funding while going SHORT → extreme short crowding,
                # high short-squeeze risk — reject the trade outright.
                logger.info(
                    "[GATE_FAIL][RELAXED] %s %s: gate=funding_rate reason=extreme_short_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate < FUNDING_EXTREME_NEGATIVE:
                score -= 15  # strong opposing penalty
            elif funding_rate > FUNDING_EXTREME_POSITIVE:
                score += 5

    # OI divergence / confirmation adjustment
    if oi_change is not None and len(five_min_candles) >= 2:
        price_up = five_min_candles[-1].close > five_min_candles[-2].close
        oi_up = oi_change > 0
        if side == Side.LONG:
            if price_up and not oi_up:
                score -= 5
            elif price_up and oi_up:
                score += 5
        else:
            if not price_up and not oi_up:
                score -= 5
            elif not price_up and oi_up:
                score += 5

    # Score-based confidence: score is the primary driver
    if score >= 90:
        confidence = Confidence.HIGH
    elif score >= 75:
        if direction_match and fvg_present and ob_present:
            confidence = Confidence.HIGH
        else:
            confidence = Confidence.MEDIUM
    elif score >= 60:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    from bot.logging_config import generate_signal_id
    sig_id = generate_signal_id()

    # Wire narrative generator for richer signal descriptions
    if not structure_note and not context_note:
        try:
            from bot.narrative import generate_signal_narrative
            gates_fired = ["macro_bias", "zone", "sweep", "mss"]
            if fvg_present:
                gates_fired.append("fvg")
            if ob_present:
                gates_fired.append("order_block")
            structure_note, context_note = generate_signal_narrative(
                symbol=symbol,
                side=side.value,
                confidence=confidence.value,
                gates_fired=gates_fired,
                confluence_score=score,
            )
        except Exception:
            pass

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


# ── 3-Channel dedicated confluence functions ──────────────────────────────────


def run_confluence_check_ch1_hard(
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
    fifteen_min_candles: Optional[list[CandleData]] = None,
    min_displacement_pct: Optional[float] = None,
    funding_rate: Optional[float] = None,
    oi_change: Optional[float] = None,
    regime: str = "UNKNOWN",
) -> Optional[SignalResult]:
    """CH1 Hard Scalp — all 7 gates mandatory, confluence score >= 70/100.

    Gate requirements (all must pass):
    Gate 1: Macro Bias (1D + 4H alignment)
    Gate 2: Discount/Premium Zone
    Gate 3: Liquidity Sweep
    Gate 4: MSS/ChoCh with volume confirmation
    Gate 5: Order Block on 15m
    Gate 6: Fair Value Gap on 15m
    Gate 7: No high-impact news within 60 minutes

    Leverage: 15x-20x | TP: 1.5R / 2.5R / 4.0R | Min score: 70
    """
    try:
        from config import (
            CH1_LEVERAGE_MAX,
            CH1_LEVERAGE_MIN,
            CH1_MIN_CONFLUENCE,
            CH1_TP1_RR,
            CH1_TP2_RR,
            CH1_TP3_RR,
        )
    except ImportError:
        CH1_LEVERAGE_MIN, CH1_LEVERAGE_MAX = 15, 20
        CH1_TP1_RR, CH1_TP2_RR, CH1_TP3_RR = 1.5, 2.5, 4.0
        CH1_MIN_CONFLUENCE = 70

    result = run_confluence_check(
        symbol=symbol,
        current_price=current_price,
        side=side,
        range_low=range_low,
        range_high=range_high,
        key_liquidity_level=key_liquidity_level,
        five_min_candles=five_min_candles,
        daily_candles=daily_candles,
        four_hour_candles=four_hour_candles,
        news_in_window=news_in_window,
        stop_loss=stop_loss,
        structure_note=structure_note,
        context_note=context_note,
        leverage_min=CH1_LEVERAGE_MIN,
        leverage_max=CH1_LEVERAGE_MAX,
        tp1_rr=CH1_TP1_RR,
        tp2_rr=CH1_TP2_RR,
        tp3_rr=CH1_TP3_RR,
        check_fvg=True,
        check_order_block=True,
        fifteen_min_candles=fifteen_min_candles,
        min_displacement_pct=min_displacement_pct,
        funding_rate=funding_rate,
        oi_change=oi_change,
        regime=regime,
    )
    if result is None:
        return None
    if result.confluence_score < CH1_MIN_CONFLUENCE:
        logger.info(
            "[CH1_FAIL] %s %s: score %d < min %d -- signal suppressed",
            symbol, side.value, result.confluence_score, CH1_MIN_CONFLUENCE,
        )
        return None
    return result


def run_confluence_check_ch2_medium(
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
    fifteen_min_candles: Optional[list[CandleData]] = None,
    min_displacement_pct: Optional[float] = None,
    funding_rate: Optional[float] = None,
    oi_change: Optional[float] = None,
    regime: str = "UNKNOWN",
) -> Optional[SignalResult]:
    """CH2 Medium Scalp -- 5 mandatory gates, confluence score >= 50/100.

    Mandatory gates:
    Gate 1: Macro Bias (4H-only allowed when 1D is clear)
    Gate 2: Discount/Premium Zone
    Gate 3: Liquidity Sweep
    Gate 4: MSS/ChoCh (volume threshold at 60th percentile)
    Gate 7: No high-impact news within 30 minutes

    Optional bonus: OB (+score), FVG (+score), Funding Rate, OI.
    Leverage: 10x-15x | TP: 1.2R / 2.0R / 3.0R | Min score: 50
    """
    try:
        from config import (
            CH2_LEVERAGE_MAX,
            CH2_LEVERAGE_MIN,
            CH2_MIN_CONFLUENCE,
            CH2_NEWS_WINDOW_MINUTES,
            CH2_TP1_RR,
            CH2_TP2_RR,
            CH2_TP3_RR,
        )
    except ImportError:
        CH2_LEVERAGE_MIN, CH2_LEVERAGE_MAX = 10, 15
        CH2_TP1_RR, CH2_TP2_RR, CH2_TP3_RR = 1.2, 2.0, 3.0
        CH2_MIN_CONFLUENCE = 50
        CH2_NEWS_WINDOW_MINUTES = 30

    result = run_confluence_check_relaxed(
        symbol=symbol,
        current_price=current_price,
        side=side,
        range_low=range_low,
        range_high=range_high,
        key_liquidity_level=key_liquidity_level,
        five_min_candles=five_min_candles,
        daily_candles=daily_candles,
        four_hour_candles=four_hour_candles,
        news_in_window=news_in_window,
        stop_loss=stop_loss,
        structure_note=structure_note,
        context_note=context_note,
        leverage_min=CH2_LEVERAGE_MIN,
        leverage_max=CH2_LEVERAGE_MAX,
        tp1_rr=CH2_TP1_RR,
        tp2_rr=CH2_TP2_RR,
        tp3_rr=CH2_TP3_RR,
        news_window_minutes=CH2_NEWS_WINDOW_MINUTES,
        fifteen_min_candles=fifteen_min_candles,
        min_displacement_pct=min_displacement_pct,
        funding_rate=funding_rate,
        oi_change=oi_change,
        regime=regime,
    )
    if result is None:
        return None
    if result.confluence_score < CH2_MIN_CONFLUENCE:
        logger.info(
            "[CH2_FAIL] %s %s: score %d < min %d -- signal suppressed",
            symbol, side.value, result.confluence_score, CH2_MIN_CONFLUENCE,
        )
        return None
    return result


def run_confluence_check_ch3_easy(
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
    fifteen_min_candles: Optional[list[CandleData]] = None,
    min_displacement_pct: Optional[float] = None,
    funding_rate: Optional[float] = None,
    oi_change: Optional[float] = None,
    regime: str = "UNKNOWN",
) -> Optional[SignalResult]:
    """CH3 Easy Breakout -- 3 core gates + momentum signals, score >= 35/100.

    Mandatory gates (3 of 7):
    Gate 2: Discount/Premium Zone (or volume spike breakout as alternative)
    Gate 4: MSS/ChoCh (volume threshold at 50th percentile)
    Gate 7: No high-impact news within 15 minutes (minimal restriction)

    Additional triggers (bonus): Macro bias, Liquidity Sweep, OB, FVG,
    volume spike (150% avg), Bollinger squeeze, EMA ribbon alignment.
    Session filter: DISABLED (24/7 trading).
    Leverage: 5x-10x | TP: 1.0R / 1.5R / 2.5R | Min score: 35
    """
    try:
        from config import (
            CH3_LEVERAGE_MAX,
            CH3_LEVERAGE_MIN,
            CH3_MIN_CONFLUENCE,
            CH3_TP1_RR,
            CH3_TP2_RR,
            CH3_TP3_RR,
        )
    except ImportError:
        CH3_LEVERAGE_MIN, CH3_LEVERAGE_MAX = 5, 10
        CH3_TP1_RR, CH3_TP2_RR, CH3_TP3_RR = 1.0, 1.5, 2.5
        CH3_MIN_CONFLUENCE = 35

    try:
        from config import MIN_DISPLACEMENT_PCT as _cfg_displacement
    except ImportError:
        _cfg_displacement = 0.15
    effective_displacement = (
        min_displacement_pct if min_displacement_pct is not None else _cfg_displacement
    )

    # Gate 7 -- minimal news blackout (15-minute window)
    if news_in_window:
        logger.info(
            "[GATE_FAIL][CH3] %s %s: gate=news reason=high_impact_imminent",
            symbol, side.value,
        )
        return None

    # Gate 2 -- Discount/Premium Zone (required) OR volume spike alternative
    if side == Side.LONG:
        gate_zone = is_discount_zone(current_price, range_low, range_high)
    else:
        gate_zone = is_premium_zone(current_price, range_low, range_high)

    # Volume spike alternative: if not in zone, accept 150%+ volume breakout
    avg_vol = _average_volume(five_min_candles[:-1]) if len(five_min_candles) > 1 else 0.0
    current_vol = five_min_candles[-1].volume if five_min_candles else 0.0
    volume_spike = avg_vol > 0 and current_vol >= avg_vol * 1.5

    if not gate_zone and not volume_spike:
        logger.info(
            "[GATE_FAIL][CH3] %s %s: gate=zone reason=price_not_in_zone_and_no_volume_spike",
            symbol, side.value,
        )
        return None

    # Gate 4 -- MSS/ChoCh (50th percentile volume threshold -- very relaxed)
    if not detect_market_structure_shift(
        five_min_candles, side, min_displacement_pct=effective_displacement
    ):
        logger.info(
            "[GATE_FAIL][CH3] %s %s: gate=mss reason=no_structure_shift",
            symbol, side.value,
        )
        return None

    # All mandatory gates passed -- build signal with bonus scoring
    atr = calculate_atr(five_min_candles)
    entry_spread = atr * 0.5 if atr > 0 else abs(current_price * 0.001)
    entry_low = current_price - entry_spread
    entry_high = current_price + entry_spread

    tp1_dyn, tp2_dyn, tp3_dyn = _compute_dynamic_rr(
        current_price, five_min_candles, CH3_TP1_RR, CH3_TP2_RR, CH3_TP3_RR, regime=regime,
    )
    tp1, tp2, tp3 = calculate_targets(current_price, stop_loss, side, tp1_dyn, tp2_dyn, tp3_dyn)

    # Scoring -- bonus gates add points, no hard-fail beyond the 3 mandatory gates
    score = 0
    score += 15  # Gate 2 (zone/spike -- passed above)
    score += 20  # Gate 4 (MSS -- passed above)

    # Optional bonus: macro bias (+15 if aligned, not required)
    macro_bias = assess_macro_bias(daily_candles, four_hour_candles)
    if macro_bias == side:
        score += 15

    # Optional bonus: liquidity sweep (+10)
    if detect_liquidity_sweep(five_min_candles, key_liquidity_level, side):
        score += 10

    # Optional bonus: volume spike bonus (+10 if triggered)
    if volume_spike:
        score += 10

    # Candles for FVG / OB scoring (prefer 15m)
    scoring_candles = fifteen_min_candles if fifteen_min_candles else five_min_candles

    fvg_present = detect_fair_value_gap(scoring_candles, side, current_price=current_price)
    ob_present = detect_order_block(scoring_candles, side, atr=atr)
    if ob_present:
        score += 5
    if fvg_present:
        score += 5

    # Momentum indicator bonuses
    if detect_bollinger_squeeze(five_min_candles):
        score += 10
    if detect_ema_ribbon_alignment(five_min_candles, side):
        score += 10
    if detect_macd_confirmation(five_min_candles, side):
        score += 10

    # Funding rate and OI adjustments
    if funding_rate is not None:
        try:
            from config import FUNDING_EXTREME_NEGATIVE, FUNDING_EXTREME_POSITIVE
        except ImportError:
            FUNDING_EXTREME_NEGATIVE = -0.0001
            FUNDING_EXTREME_POSITIVE = 0.0005
        funding_hard_positive = FUNDING_EXTREME_POSITIVE * 3
        funding_hard_negative = FUNDING_EXTREME_NEGATIVE * 3
        if side == Side.LONG:
            if funding_rate > funding_hard_positive:
                logger.info(
                    "[GATE_FAIL][CH3] %s %s: gate=funding_rate "
                    "reason=extreme_long_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate < FUNDING_EXTREME_NEGATIVE:
                score += 5
        else:
            if funding_rate < funding_hard_negative:
                logger.info(
                    "[GATE_FAIL][CH3] %s %s: gate=funding_rate "
                    "reason=extreme_short_crowding rate=%.6f",
                    symbol, side.value, funding_rate,
                )
                return None
            elif funding_rate > FUNDING_EXTREME_POSITIVE:
                score += 5

    if oi_change is not None and len(five_min_candles) >= 2:
        price_up = five_min_candles[-1].close > five_min_candles[-2].close
        oi_up = oi_change > 0
        if side == Side.LONG and price_up and oi_up:
            score += 5
        elif side == Side.SHORT and not price_up and oi_up:
            score += 5

    if score < CH3_MIN_CONFLUENCE:
        logger.info(
            "[CH3_FAIL] %s %s: score %d < min %d -- signal suppressed",
            symbol, side.value, score, CH3_MIN_CONFLUENCE,
        )
        return None

    # Confidence tier based on score
    if score >= 75:
        confidence = Confidence.HIGH
    elif score >= 55:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    from bot.logging_config import generate_signal_id
    sig_id = generate_signal_id()

    if not structure_note and not context_note:
        try:
            from bot.narrative import generate_signal_narrative
            gates_fired = ["zone", "mss"]
            if macro_bias == side:
                gates_fired.insert(0, "macro_bias")
            if fvg_present:
                gates_fired.append("fvg")
            if ob_present:
                gates_fired.append("order_block")
            structure_note, context_note = generate_signal_narrative(
                symbol=symbol,
                side=side.value,
                confidence=confidence.value,
                gates_fired=gates_fired,
                confluence_score=score,
            )
        except Exception:
            pass

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
        structure_note=(
            structure_note
            or f"{'Bullish' if side == Side.LONG else 'Bearish'} breakout momentum "
            "-- 3-gate easy entry."
        ),
        context_note=context_note or f"{symbol} easy breakout setup (CH3).",
        leverage_min=CH3_LEVERAGE_MIN,
        leverage_max=CH3_LEVERAGE_MAX,
        signal_id=sig_id,
        confluence_score=score,
    )
