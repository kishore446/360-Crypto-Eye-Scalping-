"""
Tests for bot/exchange_links.py
"""
from __future__ import annotations

import pytest

from bot.exchange_links import (
    EXCHANGE_URL_PATTERNS,
    _build_url,
    build_ref_ids_from_config,
    get_exchange_links_text,
    get_exchange_urls,
)


class TestBuildUrl:
    def test_no_ref_id_returns_base_url(self) -> None:
        url = _build_url("binance", "BTC", "")
        assert url == "https://www.binance.com/en/futures/BTCUSDT"

    def test_ref_id_appended_as_query_param(self) -> None:
        url = _build_url("binance", "BTC", "REF123")
        assert "REF123" in url
        assert "?" in url

    def test_symbol_is_upper_cased(self) -> None:
        url = _build_url("bybit", "btc", "")
        assert "BTC" in url

    def test_all_exchanges_build_urls(self) -> None:
        for exchange in EXCHANGE_URL_PATTERNS:
            url = _build_url(exchange, "ETH", "")
            assert url.startswith("https://")

    def test_bybit_ref_param_name(self) -> None:
        url = _build_url("bybit", "SOL", "MYREF")
        assert "affiliate_id=MYREF" in url

    def test_okx_ref_param_name(self) -> None:
        url = _build_url("okx", "BNB", "OKXREF")
        assert "channelid=OKXREF" in url

    def test_hyperliquid_no_usdt_suffix(self) -> None:
        url = _build_url("hyperliquid", "DOGE", "")
        assert "DOGEUSDT" not in url
        assert "DOGE" in url


class TestGetExchangeUrls:
    def test_returns_all_five_exchanges(self) -> None:
        urls = get_exchange_urls("BTC")
        assert set(urls.keys()) == {"binance", "bybit", "okx", "bitget", "hyperliquid"}

    def test_all_urls_are_strings(self) -> None:
        urls = get_exchange_urls("ETH", {"binance": "REF1"})
        for url in urls.values():
            assert isinstance(url, str)

    def test_ref_id_applied_per_exchange(self) -> None:
        ref_ids = {"binance": "BNREF", "bybit": ""}
        urls = get_exchange_urls("SOL", ref_ids)
        assert "BNREF" in urls["binance"]
        assert "?" not in urls["bybit"]

    def test_no_ref_ids_produces_clean_urls(self) -> None:
        urls = get_exchange_urls("LINK")
        for url in urls.values():
            assert "?" not in url


class TestGetExchangeLinksText:
    def test_returns_formatted_string(self) -> None:
        text = get_exchange_links_text("BTC")
        assert "🔗" in text
        assert "Binance" in text
        assert "Bybit" in text

    def test_all_exchanges_present(self) -> None:
        text = get_exchange_links_text("ETH")
        for name in ["Binance", "Bybit", "OKX", "Bitget", "Hyperliquid"]:
            assert name in text

    def test_telegram_markdown_link_format(self) -> None:
        text = get_exchange_links_text("SOL")
        # Should contain Markdown link syntax: [Label](url)
        assert "[" in text
        assert "](" in text

    def test_ref_ids_embedded_in_links(self) -> None:
        text = get_exchange_links_text("BTC", {"binance": "MYREF"})
        assert "MYREF" in text


class TestBuildRefIdsFromConfig:
    def test_returns_dict_with_all_exchange_keys(self) -> None:
        ref_ids = build_ref_ids_from_config()
        assert set(ref_ids.keys()) == {"binance", "bybit", "okx", "bitget", "hyperliquid"}

    def test_values_are_strings(self) -> None:
        ref_ids = build_ref_ids_from_config()
        for v in ref_ids.values():
            assert isinstance(v, str)
