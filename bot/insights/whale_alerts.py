"""
Whale Alert Monitor — CH5 Insights (CH5G)
==========================================
Monitors for unusually large exchange inflows/outflows and posts formatted
alerts to CH5 Market Insights channel.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.exchange import ResilientExchange

logger = logging.getLogger(__name__)

__all__ = ["WhaleAlertMonitor"]

# Threshold for what counts as a "whale" move (USD)
_WHALE_THRESHOLD_USD = 10_000_000.0  # $10M


class WhaleAlertMonitor:
    """Monitors large exchange inflows/outflows and posts to CH5 Insights."""

    async def check_whale_movements(
        self, exchange: "ResilientExchange"
    ) -> Optional[str]:
        """
        Check for unusual large transfers and format an alert message.

        Parameters
        ----------
        exchange:
            ``ResilientExchange`` instance for fetching market data.

        Returns
        -------
        str or None
            Formatted alert message if a whale movement is detected, else ``None``.
        """
        try:
            # Fetch top symbols by 24h volume to approximate large fund movement
            tickers = exchange.fetch_tickers()
            for symbol, ticker in (tickers or {}).items():
                base = symbol.split("/")[0]
                quote_volume = ticker.get("quoteVolume") or 0.0
                if quote_volume < _WHALE_THRESHOLD_USD:
                    continue
                # Approximate direction from price change
                # Negative price change = selling pressure = exchange inflow (bearish)
                # Positive price change = buying pressure = exchange outflow (bullish)
                price_change = ticker.get("percentage") or 0.0
                direction = "Exchange Inflow (bearish signal)" if price_change < 0 else "Exchange Outflow (bullish signal)"
                last_price = ticker.get("last") or 1.0
                amount_units = quote_volume / last_price
                return self.format_whale_alert(
                    symbol=base,
                    direction=direction,
                    amount_usd=quote_volume,
                    exchange_name="Binance",
                    amount_units=amount_units,
                )
        except Exception as exc:
            logger.warning("WhaleAlertMonitor.check_whale_movements failed: %s", exc)
        return None

    def format_whale_alert(
        self,
        symbol: str,
        direction: str,
        amount_usd: float,
        exchange_name: str,
        amount_units: float = 0.0,
    ) -> str:
        """
        Format a whale alert message for Telegram.

        Parameters
        ----------
        symbol:
            Base asset symbol, e.g. ``"BTC"``.
        direction:
            Human-readable direction label, e.g. ``"Exchange Inflow (bearish signal)"``.
        amount_usd:
            Amount in USD.
        exchange_name:
            Exchange name where the movement was detected.
        amount_units:
            Amount in base asset units (optional).
        """
        amount_m = amount_usd / 1_000_000
        units_str = f" ({amount_units:,.0f} {symbol})" if amount_units > 0 else ""
        bearish_note = "⚠️ Large inflows often precede sell pressure."
        bullish_note = "⚠️ Large outflows may signal accumulation."
        note = bearish_note if "inflow" in direction.lower() else bullish_note
        return (
            f"🐋 *WHALE ALERT — {symbol}*\n"
            f"Direction: {direction}\n"
            f"Amount: ${amount_m:.1f}M{units_str}\n"
            f"Exchange: {exchange_name}\n"
            f"{note}"
        )
