"""
CH5A — BTC Structure post (every 4H).

Detects BTC market structure (HH/HL = uptrend, LH/LL = downtrend, ranging)
and posts a structured update to the CH5 Insights channel.
"""
from __future__ import annotations

from bot.signal_engine import CandleData


def _find_swing_points(candles: list[CandleData]) -> tuple[list[float], list[float]]:
    """Return lists of (swing_highs, swing_lows) from the candle series."""
    highs = []
    lows = []
    for i in range(1, len(candles) - 1):
        if candles[i].high > candles[i - 1].high and candles[i].high > candles[i + 1].high:
            highs.append(candles[i].high)
        if candles[i].low < candles[i - 1].low and candles[i].low < candles[i + 1].low:
            lows.append(candles[i].low)
    return highs, lows


def detect_structure(four_hour_candles: list[CandleData]) -> str:
    """
    Classify BTC market structure from 4H candles.

    Returns one of: 'BULLISH (HH+HL pattern)', 'BEARISH (LH+LL pattern)',
    or 'RANGING'.
    """
    if len(four_hour_candles) < 10:
        return "RANGING"

    highs, lows = _find_swing_points(four_hour_candles[-20:])

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        lh = highs[-1] < highs[-2]
        ll = lows[-1] < lows[-2]

        if hh and hl:
            return "BULLISH (HH+HL pattern)"
        if lh and ll:
            return "BEARISH (LH+LL pattern)"

    return "RANGING"


def format_btc_structure_message(
    four_hour_candles: list[CandleData],
    current_price: float,
) -> str:
    """
    Build the CH5A BTC Structure post message.

    Parameters
    ----------
    four_hour_candles:
        Recent 4H BTC OHLCV candles (most-recent last).
    current_price:
        Current BTC price.

    Returns
    -------
    Formatted Telegram message string.
    """
    if len(four_hour_candles) < 10:
        return "📊 BTC STRUCTURE UPDATE [4H]\nInsufficient data."

    structure = detect_structure(four_hour_candles)

    recent = four_hour_candles[-20:]
    range_high = max(c.high for c in recent)
    range_low = min(c.low for c in recent)

    highs, lows = _find_swing_points(four_hour_candles[-20:])
    key_resistance = highs[-1] if highs else range_high
    key_support = lows[-1] if lows else range_low

    bias_label = "LONG" if "BULLISH" in structure else ("SHORT" if "BEARISH" in structure else "NEUTRAL")
    break_level = key_support if "BULLISH" in structure else key_resistance

    return (
        f"📊 BTC STRUCTURE UPDATE [4H]\n"
        f"Trend: {structure}\n"
        f"Dealing Range: ${range_low:,.2f} – ${range_high:,.2f}\n"
        f"Key Support: ${key_support:,.2f}\n"
        f"Key Resistance: ${key_resistance:,.2f}\n"
        f"Current Price: ${current_price:,.2f}\n"
        f"Bias: {bias_label} until structure breaks below ${break_level:,.2f}"
    )
