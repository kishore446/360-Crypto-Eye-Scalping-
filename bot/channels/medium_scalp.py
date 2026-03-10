"""
CH2 — Medium Scalp gate runner.

Runs the relaxed confluence check (4H-only bias, wider sweep/MSS windows,
30-min news window) and passes HIGH and MEDIUM confidence signals.
"""
from __future__ import annotations

from typing import Optional

from bot.news_filter import NewsCalendar
from bot.risk_manager import RiskManager
from bot.signal_engine import (
    CandleData,
    Confidence,
    Side,
    SignalResult,
    run_confluence_check_relaxed,
)

try:
    from config import CH2_NEWS_WINDOW_MINUTES as _CH2_NEWS_WINDOW
except Exception:  # pragma: no cover
    _CH2_NEWS_WINDOW = 30


def run(
    symbol: str,
    current_price: float,
    side: Side,
    five_min_candles: list[CandleData],
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    news_calendar: NewsCalendar,
    risk_manager: RiskManager,
    range_low: float,
    range_high: float,
    key_liquidity_level: float,
    stop_loss: float,
    market_regime: str = "UNKNOWN",
    fifteen_min_candles: Optional[list[CandleData]] = None,
    funding_rate: Optional[float] = None,
    cooldown_manager=None,
) -> Optional[SignalResult]:
    """
    Run the CH2 Medium Scalp gate stack.

    Uses relaxed gates:
    - 4H-only macro bias (no 1D required)
    - 10-candle sweep window
    - 10-candle MSS window
    - 30-minute news blackout window
    - FVG and Order Block checks disabled

    Parameters
    ----------
    fifteen_min_candles:
        Optional 15m candles for FVG / OB scoring per Blueprint §2.1.
    funding_rate:
        Optional current funding rate for score adjustment.
    cooldown_manager:
        Optional LossStreakCooldown instance for hot-streak bonus.

    Returns HIGH or MEDIUM confidence signals only.
    """
    # Regime gate — suppress counter-trend signals
    if market_regime == "BEAR" and side == Side.LONG:
        return None
    if market_regime == "BULL" and side == Side.SHORT:
        return None

    if not risk_manager.can_open_signal(side):
        return None

    # Use public API instead of private _events — respects the 30-min window
    news_in_window = news_calendar.is_high_impact_in_window(_CH2_NEWS_WINDOW)

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
        news_window_minutes=_CH2_NEWS_WINDOW,
        sweep_window=10,
        mss_window=10,
        min_displacement_pct=0.08,
        fifteen_min_candles=fifteen_min_candles,
        funding_rate=funding_rate,
    )

    if result is None:
        return None

    # CH2 passes HIGH and MEDIUM confidence signals
    if result.confidence == Confidence.LOW:
        return None

    # Apply session confidence modifier
    if result.confluence_score > 0:
        from bot.session_filter import get_session_confidence_modifier
        session_mod = get_session_confidence_modifier()
        result.confluence_score = int(result.confluence_score * session_mod)

    # Apply hot streak bonus if cooldown manager is provided
    if cooldown_manager is not None:
        bonus = cooldown_manager.get_hot_streak_bonus()
        if bonus > 0:
            result.confluence_score += bonus

    return result
