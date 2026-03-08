"""
Multi-Exchange Signal Formatter
================================
Formats signal messages for copy-trading across multiple exchanges (Binance,
Bybit, OKX) with exchange-specific pair notation and a universal format that
includes all exchange variants in one message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.price_fmt import fmt_price

if TYPE_CHECKING:
    from bot.signal_engine import SignalResult

__all__ = ["MultiExchangeFormatter"]

# Exchange pair format mappings
_BINANCE_FORMAT = "{base}USDT"        # e.g. BTCUSDT
_BYBIT_FORMAT = "{base}USDT"          # e.g. BTCUSDT
_OKX_FORMAT = "{base}-USDT-SWAP"      # e.g. BTC-USDT-SWAP


def _extract_base(symbol: str) -> str:
    """Extract the base asset from a symbol like 'BTC', 'BTC/USDT', or 'BTC/USDT:USDT'."""
    return symbol.split("/")[0].split(":")[0].upper()


class MultiExchangeFormatter:
    """Formats signal messages for copy-trading across multiple exchanges."""

    def format_for_binance(self, signal: "SignalResult") -> str:
        """Format a signal message using Binance pair notation (e.g. BTCUSDT)."""
        pair = _BINANCE_FORMAT.format(base=_extract_base(signal.symbol))
        return self._build_message(signal, pair, exchange="Binance")

    def format_for_bybit(self, signal: "SignalResult") -> str:
        """Format a signal message using Bybit pair notation (e.g. BTCUSDT)."""
        pair = _BYBIT_FORMAT.format(base=_extract_base(signal.symbol))
        return self._build_message(signal, pair, exchange="Bybit")

    def format_for_okx(self, signal: "SignalResult") -> str:
        """Format a signal message using OKX pair notation (e.g. BTC-USDT-SWAP)."""
        pair = _OKX_FORMAT.format(base=_extract_base(signal.symbol))
        return self._build_message(signal, pair, exchange="OKX")

    def format_universal(self, signal: "SignalResult") -> str:
        """
        Format a single message containing exchange-specific pair names for all
        supported exchanges (Binance, Bybit, OKX).
        """
        base = _extract_base(signal.symbol)
        binance_pair = _BINANCE_FORMAT.format(base=base)
        bybit_pair = _BYBIT_FORMAT.format(base=base)
        okx_pair = _OKX_FORMAT.format(base=base)

        direction_emoji = "🟢" if signal.side.value == "LONG" else "🔴"
        confidence_stars = {"High": "⭐⭐⭐", "Medium": "⭐⭐", "Low": "⭐"}.get(
            signal.confidence.value, "⭐"
        )

        return (
            f"{direction_emoji} *360 Eye Signal — {signal.side.value}* {confidence_stars}\n\n"
            f"📊 *Pairs by Exchange*\n"
            f"  Binance: `{binance_pair}`\n"
            f"  Bybit:   `{bybit_pair}`\n"
            f"  OKX:     `{okx_pair}`\n\n"
            f"📍 *Entry Zone:* {fmt_price(signal.entry_low)} – {fmt_price(signal.entry_high)}\n"
            f"🎯 *TP1:* {fmt_price(signal.tp1)}\n"
            f"🎯 *TP2:* {fmt_price(signal.tp2)}\n"
            f"🎯 *TP3:* {fmt_price(signal.tp3)}\n"
            f"🛑 *SL:*  {fmt_price(signal.stop_loss)}\n\n"
            f"📐 Leverage: {signal.leverage_min}x–{signal.leverage_max}x\n"
            f"🔍 {signal.structure_note}\n"
            f"📝 {signal.context_note}"
        )

    @staticmethod
    def _build_message(signal: "SignalResult", pair: str, exchange: str) -> str:
        """Build a single-exchange formatted signal message."""
        direction_emoji = "🟢" if signal.side.value == "LONG" else "🔴"
        confidence_stars = {"High": "⭐⭐⭐", "Medium": "⭐⭐", "Low": "⭐"}.get(
            signal.confidence.value, "⭐"
        )
        return (
            f"{direction_emoji} *{exchange}: {pair} {signal.side.value}* {confidence_stars}\n\n"
            f"📍 *Entry Zone:* {fmt_price(signal.entry_low)} – {fmt_price(signal.entry_high)}\n"
            f"🎯 *TP1:* {fmt_price(signal.tp1)}\n"
            f"🎯 *TP2:* {fmt_price(signal.tp2)}\n"
            f"🎯 *TP3:* {fmt_price(signal.tp3)}\n"
            f"🛑 *SL:*  {fmt_price(signal.stop_loss)}\n\n"
            f"📐 Leverage: {signal.leverage_min}x–{signal.leverage_max}x\n"
            f"🔍 {signal.structure_note}\n"
            f"📝 {signal.context_note}"
        )
