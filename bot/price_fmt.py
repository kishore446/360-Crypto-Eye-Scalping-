"""
Adaptive Price Formatter
=========================
Formats prices with appropriate decimal precision based on magnitude.
BTC at $90,000 → "90,000.00" not "90000.0000"
Micro-cap at $0.00001234 → "0.00001234" not "0.0000"
"""
from __future__ import annotations

__all__ = ["fmt_price"]


def fmt_price(price: float) -> str:
    """Format a price with adaptive decimal precision based on its magnitude."""
    abs_price = abs(price)
    if abs_price >= 1_000:
        return f"{price:,.2f}"
    if abs_price >= 0.01:
        return f"{price:.4f}"
    if abs_price >= 0.0001:
        return f"{price:.6f}"
    return f"{price:.8f}"
