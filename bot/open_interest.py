"""
Open Interest Monitor
======================
Tracks OI changes across scanned pairs to detect smart money positioning:

  - OI increase + price increase = strong trend continuation (BOOST)
  - OI decrease + price increase = weak rally / distribution (REDUCE)
  - OI increase + price decrease = bearish accumulation (SHORT BOOST)
  - OI decrease + price decrease = capitulation / long squeeze ending (LONG BOOST)

Posts significant OI divergences to the Insights channel (CH5).
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from bot.signal_engine import Side

logger = logging.getLogger(__name__)

_BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"
_TIMEOUT = 5  # seconds

try:
    from config import OI_CHANGE_THRESHOLD
except ImportError:
    OI_CHANGE_THRESHOLD: float = 0.05  # 5% OI change is significant


def fetch_open_interest(symbol: str) -> Optional[float]:
    """
    Fetch current aggregate open interest for *symbol* from Binance Futures.

    Returns None on any error so callers treat a failed fetch as NEUTRAL.
    The symbol is normalised to Binance Futures format (e.g. ``BTCUSDT``).
    """
    clean = symbol.split(":")[0].replace("/", "").upper()
    if not clean.endswith("USDT"):
        clean = clean + "USDT"
    try:
        resp = requests.get(
            _BINANCE_OI_URL,
            params={"symbol": clean},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data["openInterest"])
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed to fetch open interest for %s: %s", symbol, exc)
        return None


def analyze_oi_change(
    current_oi: float,
    previous_oi: float,
    price_change_pct: float,
    side: Side,
) -> str:
    """
    Return ``'BOOST'``, ``'REDUCE'``, or ``'NEUTRAL'`` based on OI dynamics.

    Parameters
    ----------
    current_oi:
        Most recent open interest value.
    previous_oi:
        Prior open interest value to compare against.
    price_change_pct:
        Percentage price change over the same period (positive = price up).
    side:
        The signal direction being evaluated.
    """
    if previous_oi <= 0:
        return "NEUTRAL"

    oi_change_pct = (current_oi - previous_oi) / previous_oi

    # Only act on significant OI changes
    if abs(oi_change_pct) < OI_CHANGE_THRESHOLD:
        return "NEUTRAL"

    oi_up = oi_change_pct > 0
    price_up = price_change_pct > 0

    if oi_up and price_up:
        # Strong trend continuation — BOOST LONG, REDUCE SHORT
        return "BOOST" if side == Side.LONG else "REDUCE"

    if oi_up and not price_up:
        # Bearish accumulation / new shorts opening — BOOST SHORT, REDUCE LONG
        return "BOOST" if side == Side.SHORT else "REDUCE"

    if not oi_up and price_up:
        # Weak rally / short covering / distribution — REDUCE LONG
        return "REDUCE" if side == Side.LONG else "NEUTRAL"

    # not oi_up and not price_up → capitulation / long squeeze ending — BOOST LONG
    return "BOOST" if side == Side.LONG else "NEUTRAL"
