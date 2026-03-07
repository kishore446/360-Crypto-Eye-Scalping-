"""
BTC Correlation Gate
====================
Blocks altcoin signals when BTC macro bias conflicts with the signal direction.
"""
from __future__ import annotations

import logging

from bot.signal_engine import CandleData, Side, assess_macro_bias

logger = logging.getLogger(__name__)


def btc_correlation_check(
    btc_candles_daily: list[CandleData],
    btc_candles_4h: list[CandleData],
    signal_side: Side,
) -> bool:
    """
    Check if BTC macro bias allows the given signal side.
    Returns True when the signal is ALLOWED, False when BLOCKED.
    Logic:
    - BTC BEARISH → block altcoin LONG signals
    - BTC BULLISH → block altcoin SHORT signals
    - BTC None (conflicting) → allow altcoin signals to proceed
    """
    if not btc_candles_daily or not btc_candles_4h:
        logger.debug("btc_correlation_check: no BTC candles available — allowing signal.")
        return True

    btc_bias = assess_macro_bias(btc_candles_daily, btc_candles_4h)
    if btc_bias is None:
        logger.debug("btc_correlation_check: BTC bias conflicting — allowing signal.")
        return True
    if btc_bias == Side.SHORT and signal_side == Side.LONG:
        logger.info("btc_correlation_check: BTC BEARISH — blocking LONG signal.")
        return False
    if btc_bias == Side.LONG and signal_side == Side.SHORT:
        logger.info("btc_correlation_check: BTC BULLISH — blocking SHORT signal.")
        return False
    return True
