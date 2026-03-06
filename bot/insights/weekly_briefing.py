"""
CH5D — Weekly BTC Briefing (posts every Sunday at 18:00 UTC).

Produces a weekly BTC analysis post covering:
  - Weekly close analysis
  - Key support / resistance levels for the coming week
  - Directional bias and likely scenario
"""
from __future__ import annotations

from bot.signal_engine import CandleData, _calculate_ema


def format_weekly_briefing(
    daily_candles: list[CandleData],
    current_price: float,
) -> str:
    """
    Build the CH5D weekly BTC briefing message.

    Parameters
    ----------
    daily_candles:
        1D BTC OHLCV candles (most-recent last). Needs at least 14 candles.
    current_price:
        Current BTC price.

    Returns
    -------
    Formatted Telegram message string.
    """
    if len(daily_candles) < 14:
        return "📅 WEEKLY BTC ANALYSIS\nInsufficient data for weekly briefing."

    # Weekly close = last 7 daily candles (approx. one week)
    week_candles = daily_candles[-7:]
    week_open = week_candles[0].open
    week_high = max(c.high for c in week_candles)
    week_low = min(c.low for c in week_candles)
    week_close = week_candles[-1].close
    week_change_pct = (week_close - week_open) / week_open * 100

    # Key levels — use last 14 daily candles (2 weeks)
    two_week = daily_candles[-14:]
    resistance = max(c.high for c in two_week)
    support = min(c.low for c in two_week)

    # Bias from EMA-9 vs SMA-20 on daily
    if len(daily_candles) >= 20:
        sma20 = sum(c.close for c in daily_candles[-20:]) / 20
        ema9 = _calculate_ema(daily_candles, period=9)
        if current_price > sma20 and current_price > ema9:
            bias = "BULLISH"
            scenario = (
                f"Continuation above ${resistance:,.2f} targets new highs. "
                f"Pullback to ${support:,.2f} is a buy zone."
            )
        elif current_price < sma20 and current_price < ema9:
            bias = "BEARISH"
            scenario = (
                f"Break below ${support:,.2f} opens downside to lower supports. "
                f"Reclaim of ${resistance:,.2f} would invalidate bearish view."
            )
        else:
            bias = "NEUTRAL"
            scenario = (
                f"Price is between key MAs. Watch for a decisive break above "
                f"${resistance:,.2f} (bullish) or below ${support:,.2f} (bearish)."
            )
    else:
        bias = "NEUTRAL"
        scenario = "Insufficient data for directional bias."

    return (
        f"📅 WEEKLY BTC ANALYSIS\n\n"
        f"Weekly Range: ${week_low:,.2f} – ${week_high:,.2f}\n"
        f"Weekly Close: ${week_close:,.2f} ({week_change_pct:+.2f}%)\n"
        f"Current Price: ${current_price:,.2f}\n\n"
        f"🔑 Key Levels for Next Week:\n"
        f"  Resistance: ${resistance:,.2f}\n"
        f"  Support:    ${support:,.2f}\n\n"
        f"📈 Bias: {bias}\n"
        f"📋 Scenario: {scenario}"
    )
