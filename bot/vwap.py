"""
VWAP Calculator
===============
Computes Volume-Weighted Average Price for intraday candles.
"""
from __future__ import annotations

import logging

from bot.signal_engine import CandleData

logger = logging.getLogger(__name__)


def calculate_vwap(candles: list[CandleData]) -> float:
    """
    Compute Volume-Weighted Average Price from intraday candles.
    Uses (high + low + close) / 3 as the typical price.
    Returns 0.0 if no candles or no volume.
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


def is_near_vwap(price: float, vwap: float, threshold_pct: float = 0.5) -> bool:
    """
    Returns True if price is within threshold% of VWAP.
    """
    if vwap == 0.0:
        return False
    distance_pct = abs(price - vwap) / vwap * 100.0
    return distance_pct <= threshold_pct
