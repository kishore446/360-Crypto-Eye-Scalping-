"""
CH1 — Hard Scalp gate runner.

Runs the full 7-gate confluence check (including FVG and Order Block) and
only passes signals with HIGH confidence to the channel.
"""
from __future__ import annotations

from typing import Optional

from bot.news_filter import NewsCalendar
from bot.regime_adapter import get_regime_adjustments
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
    fifteen_min_candles: Optional[list[CandleData]] = None,
    funding_rate: Optional[float] = None,
    cooldown_manager=None,
) -> Optional[SignalResult]:
    """
    Run the CH1 Hard Scalp gate stack.

    Parameters
    ----------
    market_regime:
        Current market regime from BotState. In BEAR regime, LONG signals
        are suppressed. In BULL regime, SHORT signals are suppressed.
    fifteen_min_candles:
        Optional 15m candles for FVG / OB scoring per Blueprint §2.1.
    funding_rate:
        Optional current funding rate for score adjustment.
    cooldown_manager:
        Optional LossStreakCooldown instance for hot-streak bonus.

    Returns
    -------
    A :class:`SignalResult` with HIGH confidence, or None.
    """
    # Regime gate — suppress counter-trend signals
    if market_regime == "BEAR" and side == Side.LONG:
        return None
    if market_regime == "BULL" and side == Side.SHORT:
        return None

    # Use regime-adaptive max signals instead of global constant
    regime_adj = get_regime_adjustments(market_regime)
    if not risk_manager.can_open_signal(side, max_override=regime_adj.get("max_signals")):
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
        fifteen_min_candles=fifteen_min_candles,
        funding_rate=funding_rate,
    )

    if result is None:
        return None

    # CH1 only broadcasts HIGH confidence signals
    if result.confidence != Confidence.HIGH:
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
