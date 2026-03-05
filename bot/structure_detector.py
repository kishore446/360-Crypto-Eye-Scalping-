"""
Auto Swing Detector
===================
Algorithmically detects what a human trader reads from chart structure:
- Fractal swing highs/lows using fractal pivots on candle data
- Dealing range auto-detection from swings
- Key liquidity level identification for LONG/SHORT setups
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from bot.signal_engine import CandleData, Side


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" or "low"


@dataclass
class DealingRange:
    high: float
    low: float


def detect_swing_points(candles: list[CandleData], lookback: int = 2) -> list[SwingPoint]:
    """
    Identify swing highs/lows using fractal pivots.
    A swing high is a candle whose high > the N candles on each side (default N=2).
    A swing low has a low < the N candles on each side.
    """
    points: list[SwingPoint] = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        # Check swing high
        is_high = all(candles[i].high > candles[i - j].high for j in range(1, lookback + 1)) and \
                  all(candles[i].high > candles[i + j].high for j in range(1, lookback + 1))
        if is_high:
            points.append(SwingPoint(index=i, price=candles[i].high, kind="high"))
        # Check swing low
        is_low = all(candles[i].low < candles[i - j].low for j in range(1, lookback + 1)) and \
                 all(candles[i].low < candles[i + j].low for j in range(1, lookback + 1))
        if is_low:
            points.append(SwingPoint(index=i, price=candles[i].low, kind="low"))
    return points


def find_dealing_range(candles_4h: list[CandleData], candles_15m: list[CandleData]) -> DealingRange:
    """
    Determine the current dealing range from the last significant swing high and low.
    Uses ATR filtering to ignore minor noise - swings must be > 1 ATR in magnitude.
    Falls back to recent high/low if insufficient swings found.
    """
    from bot.signal_engine import calculate_atr
    # Use 4H candles for the structural range
    swings_4h = detect_swing_points(candles_4h, lookback=2)
    atr = calculate_atr(candles_4h)
    # Filter out swings smaller than ATR (noise)
    highs = [s for s in swings_4h if s.kind == "high"]
    lows = [s for s in swings_4h if s.kind == "low"]
    if highs and lows:
        last_high = highs[-1].price
        last_low = lows[-1].price
        if atr > 0 and abs(last_high - last_low) > atr:
            return DealingRange(high=last_high, low=last_low)
    # Fallback: use min/max of recent candles
    recent = candles_4h[-10:] if len(candles_4h) >= 10 else candles_4h
    if not recent:
        recent = candles_15m[-20:] if candles_15m else []
    if not recent:
        return DealingRange(high=0.0, low=0.0)
    return DealingRange(
        high=max(c.high for c in recent),
        low=min(c.low for c in recent),
    )


def find_key_liquidity_level(candles_5m: list[CandleData], side: Side) -> float:
    """
    For LONG: key liquidity = most recent swing low below current price (pool for smart money sweep).
    For SHORT: key liquidity = most recent swing high above current price.
    Falls back to simple min/max if no swing found.
    """
    if not candles_5m:
        return 0.0
    current_price = candles_5m[-1].close
    swings = detect_swing_points(candles_5m, lookback=2)
    if side == Side.LONG:
        lows = [s for s in swings if s.kind == "low" and s.price < current_price]
        if lows:
            return lows[-1].price
        return min(c.low for c in candles_5m[-10:]) if len(candles_5m) >= 10 else min(c.low for c in candles_5m)
    else:
        highs = [s for s in swings if s.kind == "high" and s.price > current_price]
        if highs:
            return highs[-1].price
        return max(c.high for c in candles_5m[-10:]) if len(candles_5m) >= 10 else max(c.high for c in candles_5m)
