"""
Funding Rate Sentiment Gate (Gate ⑧)
=====================================
Fetches real-time funding rates from Binance Futures to add a contrarian
sentiment edge to signals:

  - Extremely negative funding (<-0.01%) + LONG signal = contrarian edge → boost confidence
  - Extremely positive funding (>0.05%) + SHORT signal = contrarian edge → boost confidence
  - Funding aligned with signal direction = crowded trade → reduce confidence

This is an OPTIONAL gate — it does not block signals, but adjusts confidence
scoring by one tier when extreme conditions are detected.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from bot.signal_engine import Side

logger = logging.getLogger(__name__)

_BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_TIMEOUT = 5  # seconds

try:
    from config import FUNDING_EXTREME_NEGATIVE, FUNDING_EXTREME_POSITIVE
except ImportError:
    FUNDING_EXTREME_NEGATIVE: float = -0.0001  # -0.01%
    FUNDING_EXTREME_POSITIVE: float = 0.0005   # 0.05%


def fetch_funding_rate(symbol: str) -> Optional[float]:
    """
    Fetch the current funding rate for *symbol* from Binance Futures.

    Returns None on any error so callers can treat a failed fetch as NEUTRAL.
    The symbol is normalised to Binance Futures format (e.g. ``BTCUSDT``).
    """
    # Normalise symbol: "BTC/USDT:USDT" or "BTC/USDT" or "BTC" → "BTCUSDT"
    clean = symbol.split(":")[0].replace("/", "").upper()
    if not clean.endswith("USDT"):
        clean = clean + "USDT"
    try:
        resp = requests.get(
            _BINANCE_FUNDING_URL,
            params={"symbol": clean},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data["lastFundingRate"])
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed to fetch funding rate for %s: %s", symbol, exc)
        return None


def get_funding_sentiment(funding_rate: Optional[float], side: Side) -> str:
    """
    Return ``'BOOST'``, ``'REDUCE'``, or ``'NEUTRAL'`` based on funding rate
    vs signal direction.

    Contrarian edge (BOOST):
      - Extreme negative funding + LONG: shorts are paying longs, crowded short
      - Extreme positive funding + SHORT: longs are paying shorts, crowded long

    Crowded trade (REDUCE):
      - Extreme positive funding + LONG: everyone is long, unwind risk
      - Extreme negative funding + SHORT: everyone is short, squeeze risk
    """
    if funding_rate is None:
        return "NEUTRAL"

    if funding_rate < FUNDING_EXTREME_NEGATIVE:
        # Shorts are dominating — contrarian edge for LONG, caution for SHORT
        return "BOOST" if side == Side.LONG else "REDUCE"

    if funding_rate > FUNDING_EXTREME_POSITIVE:
        # Longs are dominating — contrarian edge for SHORT, caution for LONG
        return "BOOST" if side == Side.SHORT else "REDUCE"

    return "NEUTRAL"
