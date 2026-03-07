"""
Whale Alert Monitor — CH5 Insights (CH5G)
==========================================
Monitors for unusually large exchange inflows/outflows and posts formatted
alerts to CH5 Market Insights channel.

When WHALE_ALERT_API_KEY is configured, uses the real Whale Alert REST API
(https://docs.whale-alert.io/) to fetch large on-chain transactions > $1M.
Falls back to a volume-proxy approach when no API key is set.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from bot.exchange import ResilientExchange

logger = logging.getLogger(__name__)

__all__ = ["WhaleAlertMonitor"]

# Threshold for what counts as a "whale" move (USD)
_WHALE_THRESHOLD_USD = 10_000_000.0  # $10M
_WHALE_ALERT_API_URL = "https://api.whale-alert.io/v1/transactions"
_WHALE_API_MIN_VALUE = 1_000_000  # $1M minimum for API query
_TIMEOUT = 8  # seconds

try:
    from config import WHALE_ALERT_API_KEY
except ImportError:
    WHALE_ALERT_API_KEY = ""


class WhaleAlertMonitor:
    """Monitors large exchange inflows/outflows and posts to CH5 Insights."""

    async def check_whale_movements(
        self, exchange: "ResilientExchange"
    ) -> Optional[str]:
        """
        Check for unusual large transfers and format an alert message.

        If WHALE_ALERT_API_KEY is configured, fetches real on-chain transaction
        data from the Whale Alert API.  Falls back to a volume-proxy approach
        when no API key is available.

        Parameters
        ----------
        exchange:
            ``ResilientExchange`` instance for fetching market data (used in
            fallback mode only).

        Returns
        -------
        str or None
            Formatted alert message if a whale movement is detected, else ``None``.
        """
        if WHALE_ALERT_API_KEY:
            return await self._check_via_api()
        return await self._check_via_volume_proxy(exchange)

    async def _check_via_api(self) -> Optional[str]:
        """Fetch real whale transactions from the Whale Alert API."""
        try:
            start_ts = int(time.time()) - 3600  # last hour
            resp = requests.get(
                _WHALE_ALERT_API_URL,
                params={
                    "api_key": WHALE_ALERT_API_KEY,
                    "min_value": _WHALE_API_MIN_VALUE,
                    "start": start_ts,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            transactions = data.get("transactions") or []
            if not transactions:
                return None
            # Pick the largest transaction
            tx = max(transactions, key=lambda t: t.get("amount_usd", 0))
            symbol = tx.get("symbol", "UNKNOWN").upper()
            amount_usd = float(tx.get("amount_usd", 0))
            if amount_usd < _WHALE_THRESHOLD_USD:
                return None
            tx_type = tx.get("transaction_type", "")
            if "exchange" in tx_type.lower() and "deposit" in tx_type.lower():
                direction = "Exchange Inflow (bearish signal)"
            elif "exchange" in tx_type.lower() and "withdrawal" in tx_type.lower():
                direction = "Exchange Outflow (bullish signal)"
            else:
                direction = tx_type or "Large Transfer"
            amount_units = float(tx.get("amount", 0))
            return self.format_whale_alert(
                symbol=symbol,
                direction=direction,
                amount_usd=amount_usd,
                exchange_name=tx.get("to", {}).get("owner_type", "On-Chain"),
                amount_units=amount_units,
            )
        except Exception as exc:
            logger.warning("WhaleAlertMonitor API call failed: %s", exc)
            return None

    async def _check_via_volume_proxy(self, exchange: "ResilientExchange") -> Optional[str]:
        """Fallback: approximate whale moves via 24h exchange volume spikes."""
        try:
            tickers = exchange.fetch_tickers()
            for symbol, ticker in (tickers or {}).items():
                base = symbol.split("/")[0]
                quote_volume = ticker.get("quoteVolume") or 0.0
                if quote_volume < _WHALE_THRESHOLD_USD:
                    continue
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
                    is_estimated=True,
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
        is_estimated: bool = False,
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
        is_estimated:
            When True, labels the alert as "Unusual Volume Alert" instead of
            "Whale Alert" to distinguish proxy estimates from confirmed on-chain data.
        """
        amount_m = amount_usd / 1_000_000
        units_str = f" ({amount_units:,.0f} {symbol})" if amount_units > 0 else ""
        bearish_note = "⚠️ Large inflows often precede sell pressure."
        bullish_note = "⚠️ Large outflows may signal accumulation."
        note = bearish_note if "inflow" in direction.lower() else bullish_note
        alert_type = "UNUSUAL VOLUME ALERT" if is_estimated else "WHALE ALERT"
        return (
            f"🐋 *{alert_type} — {symbol}*\n"
            f"Direction: {direction}\n"
            f"Amount: ${amount_m:.1f}M{units_str}\n"
            f"Exchange: {exchange_name}\n"
            f"{note}"
        )
