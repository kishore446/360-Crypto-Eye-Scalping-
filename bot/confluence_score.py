"""
Multi-Timeframe Confluence Score
=================================
Computes a weighted score (0-100) across all confluence factors.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
from bot.signal_engine import CandleData, Side, assess_macro_bias, detect_fair_value_gap, detect_order_block, detect_liquidity_sweep, is_discount_zone, is_premium_zone, detect_market_structure_shift

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFLUENCE_SCORE = 0  # 0 = disabled by default for backward compat


@dataclass
class ConfluenceFactors:
    macro_bias_aligned: bool = False
    in_discount_premium_zone: bool = False
    liquidity_swept: bool = False
    mss_confirmed: bool = False
    fvg_present: bool = False
    ob_present: bool = False
    session_active: bool = False


WEIGHTS = {
    "macro_bias_aligned": 20,
    "in_discount_premium_zone": 15,
    "liquidity_swept": 20,
    "mss_confirmed": 20,
    "fvg_present": 10,
    "ob_present": 10,
    "session_active": 5,
}


def compute_confluence_score(factors: ConfluenceFactors) -> int:
    """
    Compute weighted score 0-100 from the provided factors.
    """
    score = 0
    if factors.macro_bias_aligned:
        score += WEIGHTS["macro_bias_aligned"]
    if factors.in_discount_premium_zone:
        score += WEIGHTS["in_discount_premium_zone"]
    if factors.liquidity_swept:
        score += WEIGHTS["liquidity_swept"]
    if factors.mss_confirmed:
        score += WEIGHTS["mss_confirmed"]
    if factors.fvg_present:
        score += WEIGHTS["fvg_present"]
    if factors.ob_present:
        score += WEIGHTS["ob_present"]
    if factors.session_active:
        score += WEIGHTS["session_active"]
    return score


def build_confluence_factors(
    current_price: float,
    side: Side,
    range_low: float,
    range_high: float,
    key_liquidity_level: float,
    five_min_candles: list[CandleData],
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    session_active: bool = True,
) -> ConfluenceFactors:
    """
    Evaluate all confluence factors and return a ConfluenceFactors instance.
    """
    macro_bias = assess_macro_bias(daily_candles, four_hour_candles)
    macro_aligned = macro_bias == side

    if side == Side.LONG:
        zone_ok = is_discount_zone(current_price, range_low, range_high)
    else:
        zone_ok = is_premium_zone(current_price, range_low, range_high)

    swept = detect_liquidity_sweep(five_min_candles, key_liquidity_level, side)
    mss = detect_market_structure_shift(five_min_candles, side)
    fvg = detect_fair_value_gap(five_min_candles, side)
    ob = detect_order_block(five_min_candles, side)

    return ConfluenceFactors(
        macro_bias_aligned=macro_aligned,
        in_discount_premium_zone=zone_ok,
        liquidity_swept=swept,
        mss_confirmed=mss,
        fvg_present=fvg,
        ob_present=ob,
        session_active=session_active,
    )
