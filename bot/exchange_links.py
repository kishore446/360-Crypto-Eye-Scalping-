"""
Exchange Links
==============
Generates trade-page deep-link URLs for the five major exchanges supported by
360 Crypto Eye: Binance, Bybit, OKX, Bitget, and Hyperliquid.

When referral IDs are configured the links include the relevant affiliate
parameter so the channel earns commission on trades opened through the link.

All referral IDs are optional and default to an empty string so that
existing deployments continue working without any configuration changes.

Configuration keys (environment variables / pydantic settings)
--------------------------------------------------------------
``BINANCE_REF_ID``, ``BYBIT_REF_ID``, ``OKX_REF_ID``,
``BITGET_REF_ID``, ``HYPERLIQUID_REF_ID``

Usage
-----
>>> from bot.exchange_links import get_exchange_links_text
>>> print(get_exchange_links_text("BTC"))
🔗 Trade on: [Binance](https://…) | [Bybit](https://…) | [OKX](https://…)
"""
from __future__ import annotations

from typing import Optional

# ── URL patterns ──────────────────────────────────────────────────────────────

EXCHANGE_URL_PATTERNS: dict[str, str] = {
    "binance": "https://www.binance.com/en/futures/{symbol}USDT",
    "bybit": "https://www.bybit.com/trade/usdt/{symbol}USDT",
    "okx": "https://www.okx.com/trade-futures/{symbol}-usdt-swap",
    "bitget": "https://www.bitget.com/futures/usdt/{symbol}USDT",
    "hyperliquid": "https://app.hyperliquid.xyz/trade/{symbol}",
}

# Referral query-parameter name per exchange
_REF_PARAMS: dict[str, str] = {
    "binance": "ref",
    "bybit": "affiliate_id",
    "okx": "channelid",
    "bitget": "channelCode",
    "hyperliquid": "ref",
}

# Display names for Telegram link labels
_EXCHANGE_LABELS: dict[str, str] = {
    "binance": "Binance",
    "bybit": "Bybit",
    "okx": "OKX",
    "bitget": "Bitget",
    "hyperliquid": "Hyperliquid",
}


def _build_url(exchange: str, symbol: str, ref_id: str) -> str:
    """
    Build the trade-page URL for *exchange* and *symbol*, appending the
    referral parameter when *ref_id* is non-empty.

    Parameters
    ----------
    exchange:
        Lower-case exchange key from :data:`EXCHANGE_URL_PATTERNS`.
    symbol:
        Base asset ticker (upper-case), e.g. ``"BTC"``.
    ref_id:
        Referral / affiliate ID.  Pass an empty string to omit the parameter.

    Returns
    -------
    str
        Full URL string.
    """
    base_url = EXCHANGE_URL_PATTERNS[exchange].format(symbol=symbol.upper())
    if ref_id:
        param = _REF_PARAMS.get(exchange, "ref")
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{param}={ref_id}"
    return base_url


def get_exchange_urls(symbol: str, ref_ids: Optional[dict[str, str]] = None) -> dict[str, str]:
    """
    Return a mapping of exchange name → trade URL for *symbol*.

    Parameters
    ----------
    symbol:
        Base asset ticker, e.g. ``"BTC"``.
    ref_ids:
        Optional dict mapping exchange keys to referral IDs.  Keys not
        present (or empty strings) produce links without a referral parameter.
        Defaults to an empty dict (no referral IDs).

    Returns
    -------
    dict[str, str]
        ``{"binance": "https://…", "bybit": "https://…", …}``
    """
    if ref_ids is None:
        ref_ids = {}
    return {
        exchange: _build_url(exchange, symbol, ref_ids.get(exchange, ""))
        for exchange in EXCHANGE_URL_PATTERNS
    }


def get_exchange_links_text(
    symbol: str,
    ref_ids: Optional[dict[str, str]] = None,
) -> str:
    """
    Return a Telegram-formatted line of clickable exchange links for *symbol*.

    Only exchanges for which a URL can be built are included.  When all
    referral IDs are empty the links still appear (just without tracking).

    Parameters
    ----------
    symbol:
        Base asset ticker, e.g. ``"BTC"``.
    ref_ids:
        Optional dict of referral IDs keyed by exchange name.

    Returns
    -------
    str
        A single line such as::

            🔗 Trade on: [Binance](https://…) | [Bybit](https://…) | …
    """
    urls = get_exchange_urls(symbol, ref_ids)
    parts = [
        f"[{_EXCHANGE_LABELS[exchange]}]({url})"
        for exchange, url in urls.items()
    ]
    return "🔗 Trade on: " + " | ".join(parts)


def build_ref_ids_from_config() -> dict[str, str]:
    """
    Read referral IDs from the central config module and return them as a
    dict suitable for passing to :func:`get_exchange_urls`.

    Returns an empty dict for each exchange whose referral ID is not set,
    so the helper functions remain safe to call unconditionally.

    Returns
    -------
    dict[str, str]
        ``{"binance": "…", "bybit": "…", "okx": "…", "bitget": "…",
           "hyperliquid": "…"}``
    """
    try:
        from config import (  # noqa: PLC0415
            BINANCE_REF_ID,
            BYBIT_REF_ID,
            BITGET_REF_ID,
            HYPERLIQUID_REF_ID,
            OKX_REF_ID,
        )
    except ImportError:
        return {k: "" for k in EXCHANGE_URL_PATTERNS}

    return {
        "binance": BINANCE_REF_ID,
        "bybit": BYBIT_REF_ID,
        "okx": OKX_REF_ID,
        "bitget": BITGET_REF_ID,
        "hyperliquid": HYPERLIQUID_REF_ID,
    }
