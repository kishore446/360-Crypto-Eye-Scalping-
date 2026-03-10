"""
Multi-Timeframe Confluence Score
=================================
Computes a weighted score normalised to **0-100** across all confluence factors.

The raw weights below sum to 150 (``MAX_RAW_SCORE``).  ``compute_confluence_score``
divides the raw sum by 1.5 so the returned value is always in the range [0, 100].
All minimum-score thresholds in config (``CH1_MIN_CONFLUENCE``, etc.) are on the
normalised 0-100 scale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.signal_engine import (
    CandleData,
    Side,
    assess_macro_bias,
    assess_macro_bias_relaxed,
    detect_bollinger_squeeze,
    detect_cvd_confirmation,
    detect_ema_ribbon_alignment,
    detect_fair_value_gap,
    detect_liquidity_sweep,
    detect_macd_confirmation,
    detect_market_structure_shift,
    detect_order_block,
    is_discount_zone,
    is_premium_zone,
)

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
    macd_confirmed: bool = False
    bb_squeeze: bool = False
    cvd_confirmed: bool = False
    ema_ribbon_aligned: bool = False
    # Tracked for future use — weight is 0 and does not contribute to score
    funding_favorable: bool = False
    oi_divergence: bool = False
    btc_correlated: bool = False
    rsi_divergence: bool = False
    vwap_favorable: bool = False


WEIGHTS = {
    "macro_bias_aligned": 20,
    "in_discount_premium_zone": 20,
    "liquidity_swept": 20,
    "mss_confirmed": 20,
    "fvg_present": 10,
    "ob_present": 10,
    "session_active": 10,
    "macd_confirmed": 10,
    "bb_squeeze": 10,
    "cvd_confirmed": 10,
    "ema_ribbon_aligned": 10,
    # Below are tracked but not included in the scored total
    "funding_favorable": 0,
    "oi_divergence": 0,
    "btc_correlated": 0,
    "rsi_divergence": 0,
    "vwap_favorable": 0,
}

# Sum of all non-zero weights — used to normalise the raw score to 0-100.
MAX_RAW_SCORE: int = sum(v for v in WEIGHTS.values() if v > 0)  # 150


def compute_confluence_score(factors: ConfluenceFactors) -> int:
    """
    Compute weighted confluence score normalised to 0-100.

    The raw weights sum to 150 (``MAX_RAW_SCORE``).  The raw total is divided
    by 1.5 and rounded so the returned value is always in [0, 100].  This
    ensures the minimum-score config thresholds (e.g. ``CH1_MIN_CONFLUENCE=70``)
    represent 70 % signal quality, not the misleading 47 % of the old raw scale.
    """
    raw = 0
    if factors.macro_bias_aligned:
        raw += WEIGHTS["macro_bias_aligned"]
    if factors.in_discount_premium_zone:
        raw += WEIGHTS["in_discount_premium_zone"]
    if factors.liquidity_swept:
        raw += WEIGHTS["liquidity_swept"]
    if factors.mss_confirmed:
        raw += WEIGHTS["mss_confirmed"]
    if factors.fvg_present:
        raw += WEIGHTS["fvg_present"]
    if factors.ob_present:
        raw += WEIGHTS["ob_present"]
    if factors.session_active:
        raw += WEIGHTS["session_active"]
    if factors.macd_confirmed:
        raw += WEIGHTS["macd_confirmed"]
    if factors.bb_squeeze:
        raw += WEIGHTS["bb_squeeze"]
    if factors.cvd_confirmed:
        raw += WEIGHTS["cvd_confirmed"]
    if factors.ema_ribbon_aligned:
        raw += WEIGHTS["ema_ribbon_aligned"]
    return round(raw * 100 / MAX_RAW_SCORE)


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
    relaxed: bool = False,
) -> ConfluenceFactors:
    """
    Evaluate all confluence factors and return a ConfluenceFactors instance.

    Parameters
    ----------
    relaxed:
        When ``True``, evaluate macro bias using only 4H candles (suitable for
        CH2/CH3 signals that do not require full 1D+4H alignment).
    """
    if relaxed:
        macro_bias = assess_macro_bias_relaxed(four_hour_candles)
    else:
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
    macd_ok = detect_macd_confirmation(five_min_candles, side)
    bb_sq = detect_bollinger_squeeze(five_min_candles)
    cvd_ok = detect_cvd_confirmation(five_min_candles, side)
    ribbon_ok = detect_ema_ribbon_alignment(five_min_candles, side)

    return ConfluenceFactors(
        macro_bias_aligned=macro_aligned,
        in_discount_premium_zone=zone_ok,
        liquidity_swept=swept,
        mss_confirmed=mss,
        fvg_present=fvg,
        ob_present=ob,
        session_active=session_active,
        macd_confirmed=macd_ok,
        bb_squeeze=bb_sq,
        cvd_confirmed=cvd_ok,
        ema_ribbon_aligned=ribbon_ok,
    )
