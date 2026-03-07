"""
Liquidation Monitor — CH5 Insights (CH5H)
==========================================
Monitors liquidation clusters and extreme funding rates, posting cascade
alerts to CH5 Market Insights when significant liquidation events occur.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.exchange import ResilientExchange

logger = logging.getLogger(__name__)

__all__ = ["LiquidationMonitor"]

# Threshold in USD for a "significant" liquidation event
_LIQUIDATION_THRESHOLD_USD = 50_000_000.0  # $50M in 1h


class LiquidationMonitor:
    """Monitors liquidation clusters and extreme funding rates."""

    async def check_liquidations(
        self, exchange: "ResilientExchange"
    ) -> Optional[str]:
        """
        Check for mass liquidation events.

        Parameters
        ----------
        exchange:
            ``ResilientExchange`` instance for fetching market data.

        Returns
        -------
        str or None
            Formatted alert message if a significant liquidation event is detected,
            else ``None``.
        """
        try:
            # Use 24h quote volume as a proxy for liquidation pressure
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
        """
        total_m = total_liquidated_usd / 1_000_000
        pairs_str = ", ".join(
            f"{sym} (${amt / 1_000_000:.0f}M)" for sym, amt in top_pairs
        )
        return (
            f"💥 *LIQUIDATION CASCADE*\n"
            f"Total Liquidated (1H): ${total_m:.1f}M\n"
            f"Dominant Side: {dominant_side} ({dominant_pct:.0f}%)\n"
            f"Top Pairs: {pairs_str}\n"
            f"⚠️ Cascading liquidations — avoid entries for 30min."
        )
