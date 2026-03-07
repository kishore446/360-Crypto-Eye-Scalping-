"""
Funding Rate Dashboard — CH5 Insights (CH5I)
=============================================
Formats a funding rate extremes dashboard showing the most negative
(short-crowded) and most positive (long-crowded) funding rates across
the top 10 pairs.
"""

from __future__ import annotations

__all__ = ["format_funding_dashboard"]

# Threshold for "extreme" funding rate
_EXTREME_THRESHOLD = 0.01  # 0.01% per 8h is considered notable


def format_funding_dashboard(rates: dict[str, float]) -> str:
    """
    Format top 10 pairs by extreme funding rates.

    Parameters
    ----------
    rates:
        Dict mapping symbol (e.g. ``"BTC"``) to funding rate percentage
        (e.g. ``0.0521`` for +0.0521%).

    Returns
    -------
    str
        Telegram-formatted funding rate extremes message.
    """
    if not rates:
        return "💰 *FUNDING RATE EXTREMES*\n\nNo data available."

    sorted_rates = sorted(rates.items(), key=lambda x: x[1])

    most_negative = [(s, r) for s, r in sorted_rates if r < 0][:5]
    most_positive = [(s, r) for s, r in reversed(sorted_rates) if r > 0][:5]

    lines = ["💰 *FUNDING RATE EXTREMES*"]

    if most_negative:
        lines.append("🔴 Most Negative (short-crowded):")
        parts = [f"{sym}: {rate:+.4f}%" for sym, rate in most_negative]
        lines.append("  " + " | ".join(parts))
    else:
        lines.append("🔴 Most Negative: None detected")

    if most_positive:
        lines.append("🟢 Most Positive (long-crowded):")
        parts = [f"{sym}: {rate:+.4f}%" for sym, rate in most_positive]
        lines.append("  " + " | ".join(parts))
    else:
        lines.append("🟢 Most Positive: None detected")

    lines.append("⚠️ Extreme funding = potential squeeze opportunity.")
    return "\n".join(lines)
