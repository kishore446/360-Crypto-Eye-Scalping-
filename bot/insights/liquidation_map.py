"""
Liquidation Monitor — CH5 Insights (CH5H)
==========================================
Monitors liquidation clusters and extreme funding rates, posting cascade
alerts to CH5 Market Insights when significant liquidation events occur.

When COINGLASS_API_KEY is configured, uses the real Coinglass API to fetch
live liquidation history.  Falls back to a volume-proxy approach otherwise.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from bot.exchange import ResilientExchange

logger = logging.getLogger(__name__)

__all__ = ["LiquidationMonitor"]

# Threshold in USD for a "significant" liquidation event
_LIQUIDATION_THRESHOLD_USD = 50_000_000.0  # $50M in 1h
_COINGLASS_API_URL = "https://open-api.coinglass.com/public/v2/liquidation_history"
_TIMEOUT = 8  # seconds

try:
    from config import COINGLASS_API_KEY
except ImportError:
    COINGLASS_API_KEY = ""


class LiquidationMonitor:
    """Monitors liquidation clusters and extreme funding rates."""

    async def check_liquidations(
        self, exchange: "ResilientExchange"
    ) -> Optional[str]:
        """
        Check for mass liquidation events.

        If COINGLASS_API_KEY is configured, fetches real liquidation data from
        the Coinglass API.  Falls back to a volume-proxy approach otherwise.

        Parameters
        ----------
        exchange:
            ``ResilientExchange`` instance for fetching market data (used in
            fallback mode only).

        Returns
        -------
        str or None
            Formatted alert message if a significant liquidation event is detected,
            else ``None``.
        """
        if COINGLASS_API_KEY:
            return await self._check_via_api()
        return await self._check_via_volume_proxy(exchange)

    async def _check_via_api(self) -> Optional[str]:
        """Fetch real liquidation data from the Coinglass API."""
        try:
            resp = requests.get(
                _COINGLASS_API_URL,
                headers={"coinglassSecret": COINGLASS_API_KEY},
                params={"symbol": "BTC", "interval": "1h"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data") or []
            if not records:
                return None
            # Use the most recent record
            latest = records[-1] if isinstance(records, list) else records
            long_liq = float(latest.get("longLiquidationUsd", 0))
            short_liq = float(latest.get("shortLiquidationUsd", 0))
            total_liq = long_liq + short_liq
            if total_liq < _LIQUIDATION_THRESHOLD_USD:
                return None
            dominant_side = "LONGS" if long_liq >= short_liq else "SHORTS"
            dominant_pct = (long_liq / total_liq * 100) if dominant_side == "LONGS" else (short_liq / total_liq * 100)
            return self.format_liquidation_alert(
                total_liquidated_usd=total_liq,
                dominant_side=dominant_side,
                top_pairs=[("BTC", total_liq)],
                dominant_pct=dominant_pct,
                is_estimated=False,
            )
        except Exception as exc:
            logger.warning("LiquidationMonitor Coinglass API call failed: %s", exc)
            return None

    async def _check_via_volume_proxy(self, exchange: "ResilientExchange") -> Optional[str]:
        """Fallback: approximate liquidations via 24h exchange volume spikes."""
        try:
            tickers = exchange.fetch_tickers()
            total_liquidated = 0.0
            long_liquidated = 0.0
            top_pairs: list[tuple[str, float]] = []

            for symbol, ticker in (tickers or {}).items():
                base = symbol.split("/")[0]
                quote_volume = ticker.get("quoteVolume") or 0.0
                price_change = ticker.get("percentage") or 0.0
                if quote_volume > 0:
                    total_liquidated += quote_volume
                    if price_change < -2.0:
                        long_liquidated += quote_volume
                    top_pairs.append((base, quote_volume))

            if total_liquidated < _LIQUIDATION_THRESHOLD_USD:
                return None

            top_pairs.sort(key=lambda x: x[1], reverse=True)
            dominant_pct = long_liquidated / total_liquidated * 100 if total_liquidated > 0 else 50.0
            dominant_side = "LONGS" if dominant_pct > 50 else "SHORTS"
            return self.format_liquidation_alert(
                total_liquidated_usd=total_liquidated,
                dominant_side=dominant_side,
                top_pairs=top_pairs[:3],
                dominant_pct=dominant_pct if dominant_side == "LONGS" else 100 - dominant_pct,
                is_estimated=True,
            )
        except Exception as exc:
            logger.warning("LiquidationMonitor.check_liquidations failed: %s", exc)
        return None

    def format_liquidation_alert(
        self,
        total_liquidated_usd: float,
        dominant_side: str,
        top_pairs: list,
        dominant_pct: float = 50.0,
        is_estimated: bool = False,
    ) -> str:
        """
        Format a liquidation cascade alert message for Telegram.

        Parameters
        ----------
        total_liquidated_usd:
            Total USD value liquidated in the last hour.
        dominant_side:
            ``"LONGS"`` or ``"SHORTS"`` — whichever side was hit more.
        top_pairs:
            List of ``(symbol, usd_amount)`` tuples for top liquidated pairs.
        dominant_pct:
            Percentage of liquidations on the dominant side.
        is_estimated:
            When True, labels as "Estimated Liquidation Alert" to distinguish
            proxy estimates from confirmed Coinglass data.
        """
        total_m = total_liquidated_usd / 1_000_000
        pairs_str = ", ".join(
            f"{sym} (${amt / 1_000_000:.0f}M)" for sym, amt in top_pairs
        )
        label = "ESTIMATED LIQUIDATION ALERT" if is_estimated else "LIQUIDATION CASCADE"
        return (
            f"💥 *{label}*\n"
            f"Total Liquidated (1H): ${total_m:.1f}M\n"
            f"Dominant Side: {dominant_side} ({dominant_pct:.0f}%)\n"
            f"Top Pairs: {pairs_str}\n"
            f"⚠️ Cascading liquidations — avoid entries for 30min."
        )
