"""
CH2 — Intraday / Swing gate runner.

Implements the institutional Intraday blueprint:
  1. Trend Filter: EMA50 & EMA200 crossover
  2. Momentum Filter: MACD histogram + RSI14
  3. Support/Resistance Filter: Fibonacci 38–61% / Pivot points
  4. Volume Filter: Candle volume ≥ 1.3× last 20-candle average
  5. Volatility Filter: ATR > median ATR of last 50 candles
  6. Entry Confirmation: Trend + Momentum + S/R alignment; avoid chasing breakouts
  7. Exit Strategy: TP 1–2× ATR14, SL below/above nearest S/R
  8. Timeframe: 15–60 min candles
  9. Signal Frequency: Every 5–15 min
 10. Multi-Layer Confirmation: Requires 4 aligned filters minimum
"""
from __future__ import annotations

import statistics
from typing import Optional

from bot.news_filter import NewsCalendar
from bot.risk_manager import RiskManager
from bot.signal_engine import (
    CandleData,
    Confidence,
    Side,
    SignalResult,
    _average_volume,
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    run_confluence_check_relaxed,
)

try:
    from config import CH2_NEWS_WINDOW_MINUTES as _CH2_NEWS_WINDOW
except Exception:  # pragma: no cover
    _CH2_NEWS_WINDOW = 30


def _check_ema_trend(candles: list[CandleData], side: Side) -> bool:
    """Gate 1: EMA50 & EMA200 crossover — EMA50 > EMA200 for LONG, < for SHORT."""
    if len(candles) < 205:
        return False
    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)
    if side == Side.LONG:
        return ema50 > ema200
    return ema50 < ema200


def _check_macd_rsi_momentum(candles: list[CandleData], side: Side) -> bool:
    """Gate 2: MACD histogram direction + RSI14 momentum alignment."""
    if len(candles) < 35:
        return False
    macd_line, signal_line, histogram = calculate_macd(candles)
    rsi = calculate_rsi(candles, period=14)
    if side == Side.LONG:
        return histogram > 0 and rsi > 40
    return histogram < 0 and rsi < 60


def _check_fibonacci_sr(
    candles: list[CandleData],
    current_price: float,
    side: Side,
    lookback: int = 50,
) -> bool:
    """
    Gate 3: Price is near Fibonacci 38–61% retracement / Pivot support-resistance.

    Uses the last *lookback* candles to establish the swing high/low, then checks
    whether the current price is within the 38–61% Fibonacci retracement zone
    (a common intraday S/R zone). For LONG, price should be above the 38% level;
    for SHORT, price should be below the 62% level.
    """
    if len(candles) < lookback:
        return False
    window = candles[-lookback:]
    swing_high = max(c.high for c in window)
    swing_low = min(c.low for c in window)
    span = swing_high - swing_low
    if span <= 0:
        return False
    fib_38 = swing_high - 0.382 * span
    fib_62 = swing_high - 0.618 * span
    if side == Side.LONG:
        return current_price >= fib_62
    return current_price <= fib_38


def _check_volume(candles: list[CandleData], multiplier: float = 1.3) -> bool:
    """Gate 4: Candle volume ≥ 1.3× last 20-candle average."""
    if len(candles) < 21:
        return False
    avg_vol = _average_volume(candles[-20:])
    return avg_vol > 0 and candles[-1].volume >= multiplier * avg_vol


def _check_atr_volatility(candles: list[CandleData], lookback: int = 50) -> bool:
    """Gate 5: ATR > median ATR of last 50 candles."""
    if len(candles) < lookback + 14:
        return False
    current_atr = calculate_atr(candles)
    atr_series = [
        calculate_atr(candles[: -(lookback - i) or None])
        for i in range(lookback)
    ]
    median_atr = statistics.median(atr_series)
    return current_atr > median_atr


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
    Run the CH2 Intraday / Swing gate stack.

    Applies the institutional 5-filter blueprint for 15–60 min multi-hour moves:
      1. EMA50 & EMA200 crossover trend filter
      2. MACD histogram direction + RSI14 momentum
      3. Fibonacci 38–61% S/R alignment (avoid chasing breakouts)
      4. Volume ≥ 1.3× 20-candle average
      5. ATR > median ATR of last 50 candles
    Requires 4 of 5 filters aligned (relaxed gate check).

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

    # Multi-layer confirmation: require at least 4 aligned filters
    # Use 15m candles when available (better for intraday S/R detection)
    analysis_candles = fifteen_min_candles if fifteen_min_candles else five_min_candles
    filters_passed = 0
    if _check_ema_trend(analysis_candles, side):
        filters_passed += 1
    if _check_macd_rsi_momentum(analysis_candles, side):
        filters_passed += 1
    if _check_fibonacci_sr(analysis_candles, current_price, side):
        filters_passed += 1
    if _check_volume(analysis_candles):
        filters_passed += 1
    if _check_atr_volatility(analysis_candles):
        filters_passed += 1

    if filters_passed < 4:
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

    # CH2 Intraday passes HIGH and MEDIUM confidence signals
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
