"""
CH5C — Market Regime Detector (posts daily at 09:00 UTC).

Classifies the market into BULL / BEAR / SIDEWAYS using:
  - BTC price vs 200-day SMA
  - Fear & Greed Index (free API from alternative.me)

Stores regime in BotState so CH1/CH2 can read it and suppress LONG
signals in BEAR regime.

Regime rules:
  BULL    = price > 200d SMA AND Fear & Greed > 50
  BEAR    = price < 200d SMA AND Fear & Greed < 40
  SIDEWAYS = anything else

In BEAR regime, CH1 and CH2 automatically suppress new LONG signals.
CH4 (Spot) and CH3 (Easy Breakout) are never suppressed by regime.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from bot.signal_engine import CandleData

logger = logging.getLogger(__name__)

try:
    from config import BTC_FEAR_GREED_URL as _FNG_URL
except Exception:  # pragma: no cover
    _FNG_URL = "https://api.alternative.me/fng/"


def fetch_fear_and_greed(url: str = _FNG_URL, timeout: int = 10) -> Optional[int]:
    """
    Fetch the current Fear & Greed Index value from alternative.me.

    Returns the index value (0–100) or None on failure.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        value = int(data["data"][0]["value"])
        return value
    except Exception as exc:
        logger.warning("Failed to fetch Fear & Greed index: %s", exc)
        return None


def classify_regime(
    daily_candles: list[CandleData],
    current_price: float,
    fear_and_greed: Optional[int],
) -> str:
    """
    Classify market regime from BTC 1D candles and Fear & Greed index.

    Parameters
    ----------
    daily_candles:
        1D BTC candles (most-recent last). Needs at least 200 candles for
        full accuracy; falls back to 50-day SMA when 50–199 candles are
        available.
    current_price:
        Current BTC price.
    fear_and_greed:
        Fear & Greed index value (0–100), or None if unavailable.

    Returns
    -------
    One of: 'BULL', 'BEAR', 'SIDEWAYS', or 'UNKNOWN'.
    """
    if len(daily_candles) < 50:
        return "UNKNOWN"

    if len(daily_candles) >= 200:
        sma = sum(c.close for c in daily_candles[-200:]) / 200
    else:
        # Graceful degradation: use 50-day SMA when fewer than 200 candles available
        sma = sum(c.close for c in daily_candles[-50:]) / 50
        logger.debug(
            "Regime detector: only %d daily candles available; using 50-day SMA fallback.",
            len(daily_candles),
        )

    above_sma = current_price > sma

    if fear_and_greed is None:
        # Fall back to SMA-only classification
        return "BULL" if above_sma else "BEAR"

    if above_sma and fear_and_greed > 50:
        return "BULL"
    if not above_sma and fear_and_greed < 40:
        return "BEAR"
    return "SIDEWAYS"


def format_regime_message(
    daily_candles: list[CandleData],
    current_price: float,
    fear_and_greed: Optional[int],
    regime: str,
) -> str:
    """Build the CH5C regime post message."""
    if len(daily_candles) < 50:
        return f"🌍 MARKET REGIME: {regime}\nInsufficient data for SMA calculation."

    using_fallback = len(daily_candles) < 200
    if using_fallback:
        sma = sum(c.close for c in daily_candles[-50:]) / 50
        sma_label = "50D SMA (fallback)"
    else:
        sma = sum(c.close for c in daily_candles[-200:]) / 200
        sma_label = "200D SMA"

    sma_pct = (current_price - sma) / sma * 100

    regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "SIDEWAYS": "🟡"}.get(regime, "⚪")

    fg_label = str(fear_and_greed) if fear_and_greed is not None else "N/A"
    fg_sentiment = ""
    if fear_and_greed is not None:
        if fear_and_greed >= 75:
            fg_sentiment = " (Extreme Greed)"
        elif fear_and_greed >= 55:
            fg_sentiment = " (Greed)"
        elif fear_and_greed >= 45:
            fg_sentiment = " (Neutral)"
        elif fear_and_greed >= 25:
            fg_sentiment = " (Fear)"
        else:
            fg_sentiment = " (Extreme Fear)"

    if regime == "BEAR":
        action = "Action: LONG signals SUSPENDED across all scalp channels.\nShort setups only until regime shifts."
    elif regime == "BULL":
        action = "Action: Full signal generation active. Bias favors LONG setups."
    else:
        action = "Action: Both directions active. Trade setups on their own merit."

    return (
        f"🌍 MARKET REGIME: {regime} {regime_emoji}\n"
        f"BTC vs {sma_label}: {sma_pct:+.1f}%\n"
        f"Fear & Greed: {fg_label}{fg_sentiment}\n"
        f"{action}"
    )


def run(
    daily_candles: list[CandleData],
    current_price: float,
    bot_state: object,
    url: str = _FNG_URL,
) -> str:
    """
    Run the regime detector and update bot_state.market_regime.

    Parameters
    ----------
    daily_candles:
        1D BTC OHLCV candles.
    current_price:
        Current BTC price.
    bot_state:
        BotState instance (must have a ``market_regime`` property).
    url:
        Fear & Greed API URL.

    Returns
    -------
    Formatted regime post message string.
    """
    fg = fetch_fear_and_greed(url)
    regime = classify_regime(daily_candles, current_price, fg)

    # Store in bot state so CH1/CH2 can read it
    try:
        bot_state.market_regime = regime  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("Failed to set market_regime on bot_state: %s", exc)

    return format_regime_message(daily_candles, current_price, fg, regime)
