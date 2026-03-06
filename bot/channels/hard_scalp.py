"""
CH1 — Hard Scalp gate runner.

Runs the full 7-gate confluence check (including FVG and Order Block) and
only passes signals with HIGH confidence to the channel.
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
    run_confluence_check,
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
    Run the CH1 Hard Scalp gate stack.

    Parameters
    ----------
    market_regime:
        Current market regime from BotState. In BEAR regime, LONG signals
        are suppressed.

    Returns
    -------
    A :class:`SignalResult` with HIGH confidence, or None.
    """
    # Regime gate — suppress LONG signals in BEAR regime
    if market_regime == "BEAR" and side == Side.LONG:
        return None

    if not risk_manager.can_open_signal(side):
        return None

    result = run_confluence_check(
        symbol=symbol,
        current_price=current_price,
        side=side,
        range_low=range_low,
        range_high=range_high,
        key_liquidity_level=key_liquidity_level,
        five_min_candles=five_min_candles,
        daily_candles=daily_candles,
        four_hour_candles=four_hour_candles,
        news_in_window=news_calendar.is_high_impact_imminent(),
        stop_loss=stop_loss,
        check_fvg=True,
        check_order_block=True,
    )

    if result is None:
        return None

    # CH1 only broadcasts HIGH confidence signals
    if result.confidence != Confidence.HIGH:
        return None

    return result
