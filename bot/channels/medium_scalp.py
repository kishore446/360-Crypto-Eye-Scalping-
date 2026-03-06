"""
CH2 — Medium Scalp gate runner.

Runs the relaxed confluence check (4H-only bias, wider sweep/MSS windows,
30-min news window) and passes HIGH and MEDIUM confidence signals.
"""
from __future__ import annotations

import time
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


def _is_news_imminent(news_calendar: NewsCalendar, window_minutes: int) -> bool:
    """Check if any high-impact news falls within *window_minutes* from now."""
    now = time.time()
    cutoff = now + window_minutes * 60
    events = getattr(news_calendar, "_events", [])
    return any(
        getattr(e, "impact", None) == "HIGH" and now <= getattr(e, "timestamp", 0) <= cutoff
        for e in events
    )


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
) -> Optional[SignalResult]:
    """
    Run the CH2 Medium Scalp gate stack.

    Uses relaxed gates:
    - 4H-only macro bias (no 1D required)
    - 10-candle sweep window
    - 10-candle MSS window
    - 30-minute news blackout window
    - FVG and Order Block checks disabled

    Returns HIGH or MEDIUM confidence signals only.
    """
    # Regime gate — suppress LONG signals in BEAR regime
    if market_regime == "BEAR" and side == Side.LONG:
        return None

    if not risk_manager.can_open_signal(side):
        return None

    # Use relaxed 30-min news window
    news_in_window = _is_news_imminent(news_calendar, _CH2_NEWS_WINDOW)

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
    )

    if result is None:
        return None

    # CH2 passes HIGH and MEDIUM confidence signals
    if result.confidence == Confidence.LOW:
        return None

    return result
