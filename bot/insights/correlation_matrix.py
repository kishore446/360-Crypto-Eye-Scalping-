"""
Correlation Matrix — CH5 Insights (CH5J)
=========================================
Calculates and formats Pearson correlation between BTC and altcoin price
series for market insight broadcasting.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.signal_engine import CandleData

__all__ = ["calculate_correlation", "format_correlation_report"]


def calculate_correlation(
    candles_a: list["CandleData"],
    candles_b: list["CandleData"],
) -> float:
    """
    Calculate the Pearson correlation coefficient between two price series.

    Parameters
    ----------
    candles_a:
        First candle series (e.g. BTC).
    candles_b:
        Second candle series (e.g. an altcoin).

    Returns
    -------
    float
        Pearson correlation coefficient in range [-1.0, 1.0].
        Returns 0.0 when fewer than 3 shared data points exist.
    """
    n = min(len(candles_a), len(candles_b))
    if n < 3:
        return 0.0

    closes_a = [c.close for c in candles_a[-n:]]
    closes_b = [c.close for c in candles_b[-n:]]

    mean_a = sum(closes_a) / n
    mean_b = sum(closes_b) / n

    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(closes_a, closes_b))
    denom_a = math.sqrt(sum((a - mean_a) ** 2 for a in closes_a))
    denom_b = math.sqrt(sum((b - mean_b) ** 2 for b in closes_b))

    if denom_a == 0 or denom_b == 0:
        return 0.0

    return round(numerator / (denom_a * denom_b), 4)


def format_correlation_report(correlations: dict[str, float]) -> str:
    """
    Format a BTC vs altcoin correlation matrix message for Telegram.

    Parameters
    ----------
    correlations:
        Dict mapping altcoin symbol (e.g. ``"ETH"``) to its Pearson correlation
        with BTC (e.g. ``0.87``).

    Returns
    -------
    str
        Telegram-formatted correlation report.
    """
    if not correlations:
        return "🔗 *BTC CORRELATION MATRIX*\n\nNo data available."

    sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)

    lines = ["🔗 *BTC CORRELATION MATRIX*", ""]
    for symbol, corr in sorted_corr:
        bar = "█" * max(1, int(abs(corr) * 10)) if corr != 0.0 else ""
        sign = "+" if corr >= 0 else "-"
        direction = "🟢 CORR" if corr >= 0 else "🔴 INV"
        lines.append(f"  {symbol:<6} {sign}{abs(corr):.2f} {bar:<10} {direction}")

    lines.append("")
    lines.append("ℹ️ High correlation = altcoin follows BTC closely.")
    return "\n".join(lines)
