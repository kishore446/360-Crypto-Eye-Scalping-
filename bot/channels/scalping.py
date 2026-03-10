"""
CH1 — Scalping / Quick Trades gate runner.

Implements the institutional Scalping blueprint:
  1. Trend Filter: EMA9, EMA21, EMA50 — EMA9 > EMA21 > EMA50 → Uptrend, reverse for Downtrend
  2. Momentum Filter: RSI5 — RSI <30 → Long, RSI >70 → Short
  3. Volume Filter: Current candle volume ≥ 1.5× last 20-candle average
  4. Volatility Filter: ATR14 > last 20-candle average ATR
  5. Entry Confirmation: Candle bounce from EMA ribbon + momentum alignment
  6. Exit Strategy: TP 0.3–0.6%, SL trailing 0.2–0.3% behind recent swing
  7. Timeframe: 1–5 min candles
  8. Multi-Layer Confirmation: Requires 3 aligned filters minimum
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
    _average_volume,
    calculate_atr,
    calculate_ema,
    calculate_rsi,
    run_confluence_check,
)


def _check_ema_trend(candles: list[CandleData], side: Side) -> bool:
    """Gate 1: EMA9 > EMA21 > EMA50 for LONG; reverse for SHORT."""
    if len(candles) < 55:
        return False
    ema9 = calculate_ema(candles, 9)
    ema21 = calculate_ema(candles, 21)
    ema50 = calculate_ema(candles, 50)
    if side == Side.LONG:
        return ema9 > ema21 > ema50
    return ema9 < ema21 < ema50


def _check_rsi_momentum(candles: list[CandleData], side: Side, period: int = 5) -> bool:
    """Gate 2: RSI5 < 30 for LONG, RSI5 > 70 for SHORT."""
    rsi = calculate_rsi(candles, period=period)
    if side == Side.LONG:
        return rsi < 30
    return rsi > 70


def _check_volume_spike(candles: list[CandleData], multiplier: float = 1.5) -> bool:
    """Gate 3: Current candle volume ≥ 1.5× last 20-candle average."""
    if len(candles) < 21:
        return False
    avg_vol = _average_volume(candles[-20:])
    return avg_vol > 0 and candles[-1].volume >= multiplier * avg_vol


def _check_atr_volatility(candles: list[CandleData], period: int = 14) -> bool:
    """Gate 4: ATR14 > last 20-candle average ATR."""
    if len(candles) < period + 20:
        return False
    current_atr = calculate_atr(candles, period=period)
    # Compute 20-period rolling ATR average using the last 20 ATR estimates
    atr_values = [
        calculate_atr(candles[: -(20 - i) or None], period=period)
        for i in range(20)
    ]
    avg_atr = sum(atr_values) / len(atr_values) if atr_values else 0
    return current_atr > avg_atr


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
    Run the CH1 Scalping gate stack.

    Applies the institutional 5-filter blueprint for 1–5 min fast micro-moves:
      1. EMA9/21/50 trend alignment
      2. RSI5 momentum filter (<30 long, >70 short)
      3. Volume spike ≥ 1.5× 20-candle average
      4. ATR14 > 20-candle average ATR (volatility confirmation)
      5. Full confluence check (7-gate engine) with HIGH confidence required

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

    # Multi-layer confirmation: require at least 3 aligned filters
    filters_passed = 0
    if _check_ema_trend(five_min_candles, side):
        filters_passed += 1
    if _check_rsi_momentum(five_min_candles, side):
        filters_passed += 1
    if _check_volume_spike(five_min_candles):
        filters_passed += 1
    if _check_atr_volatility(five_min_candles):
        filters_passed += 1

    if filters_passed < 3:
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

    # CH1 Scalping only broadcasts HIGH confidence signals
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
