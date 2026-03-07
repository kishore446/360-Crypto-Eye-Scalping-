"""Tests for MultiExchangeFormatter."""
from __future__ import annotations

import pytest

from bot.exchange_formatter import MultiExchangeFormatter, _extract_base
from bot.signal_engine import CandleData, Confidence, Side, SignalResult


def _make_signal(symbol: str = "BTC", side: Side = Side.LONG) -> SignalResult:
    return SignalResult(
        symbol=symbol,
        side=side,
        confidence=Confidence.HIGH,
        entry_low=67000.0,
        entry_high=67500.0,
        tp1=68500.0,
        tp2=69500.0,
        tp3=71000.0,
        stop_loss=65000.0,
        structure_note="Order Block",
        context_note="4H bullish bias",
        leverage_min=10,
        leverage_max=20,
        signal_id="test-signal-1",
    )


@pytest.fixture()
def formatter():
    return MultiExchangeFormatter()


# ── _extract_base helper ──────────────────────────────────────────────────────

class TestExtractBase:
    def test_plain_symbol(self):
        assert _extract_base("BTC") == "BTC"

    def test_slash_pair(self):
        assert _extract_base("BTC/USDT") == "BTC"

    def test_ccxt_futures_format(self):
        assert _extract_base("BTC/USDT:USDT") == "BTC"

    def test_lowercase(self):
        assert _extract_base("eth") == "ETH"


# ── format_for_binance ───────────────────────────────────────────────────────

class TestFormatForBinance:
    def test_btc_pair_format(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_for_binance(signal)
        assert "BTCUSDT" in msg
        assert "Binance" in msg

    def test_contains_entry_zone(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_for_binance(signal)
        assert "67000" in msg or "67,000" in msg

    def test_contains_tp_and_sl(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_for_binance(signal)
        assert "TP1" in msg
        assert "SL" in msg

    def test_eth_pair(self, formatter):
        signal = _make_signal("ETH")
        msg = formatter.format_for_binance(signal)
        assert "ETHUSDT" in msg


# ── format_for_bybit ─────────────────────────────────────────────────────────

class TestFormatForBybit:
    def test_btc_pair_format(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_for_bybit(signal)
        assert "BTCUSDT" in msg
        assert "Bybit" in msg

    def test_sol_pair(self, formatter):
        signal = _make_signal("SOL")
        msg = formatter.format_for_bybit(signal)
        assert "SOLUSDT" in msg


# ── format_for_okx ───────────────────────────────────────────────────────────

class TestFormatForOkx:
    def test_btc_swap_format(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_for_okx(signal)
        assert "BTC-USDT-SWAP" in msg
        assert "OKX" in msg

    def test_eth_swap_format(self, formatter):
        signal = _make_signal("ETH")
        msg = formatter.format_for_okx(signal)
        assert "ETH-USDT-SWAP" in msg


# ── format_universal ─────────────────────────────────────────────────────────

class TestFormatUniversal:
    def test_contains_all_exchanges(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_universal(signal)
        assert "Binance" in msg
        assert "Bybit" in msg
        assert "OKX" in msg

    def test_contains_all_pair_formats(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_universal(signal)
        assert "BTCUSDT" in msg
        assert "BTC-USDT-SWAP" in msg

    def test_contains_tp_sl(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_universal(signal)
        assert "TP1" in msg
        assert "SL" in msg

    def test_long_signal_emoji(self, formatter):
        signal = _make_signal("BTC", side=Side.LONG)
        msg = formatter.format_universal(signal)
        assert "🟢" in msg

    def test_short_signal_emoji(self, formatter):
        signal = _make_signal("BTC", side=Side.SHORT)
        msg = formatter.format_universal(signal)
        assert "🔴" in msg

    def test_high_confidence_stars(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_universal(signal)
        assert "⭐⭐⭐" in msg

    def test_structure_note_included(self, formatter):
        signal = _make_signal("BTC")
        msg = formatter.format_universal(signal)
        assert "Order Block" in msg
