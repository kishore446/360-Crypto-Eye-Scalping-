"""Tests for bot/btc_correlation.py"""
from __future__ import annotations
import pytest
from unittest.mock import patch
from bot.signal_engine import CandleData, Side
from bot.btc_correlation import btc_correlation_check


def _bullish_candles(n: int = 20) -> list[CandleData]:
    return [
        CandleData(open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.5 + i, volume=1000.0)
        for i in range(n)
    ]


def _bearish_candles(n: int = 20) -> list[CandleData]:
    return [
        CandleData(open=200.0 - i, high=201.0 - i, low=198.0 - i, close=198.5 - i, volume=1000.0)
        for i in range(n)
    ]


class TestBtcCorrelationCheck:
    def test_no_btc_candles_allows_signal(self):
        assert btc_correlation_check([], [], Side.LONG) is True
        assert btc_correlation_check([], [], Side.SHORT) is True

    def test_btc_bullish_blocks_short(self):
        with patch("bot.btc_correlation.assess_macro_bias", return_value=Side.LONG):
            result = btc_correlation_check(_bullish_candles(), _bullish_candles(5), Side.SHORT)
        assert result is False

    def test_btc_bullish_allows_long(self):
        with patch("bot.btc_correlation.assess_macro_bias", return_value=Side.LONG):
            result = btc_correlation_check(_bullish_candles(), _bullish_candles(5), Side.LONG)
        assert result is True

    def test_btc_bearish_blocks_long(self):
        with patch("bot.btc_correlation.assess_macro_bias", return_value=Side.SHORT):
            result = btc_correlation_check(_bearish_candles(), _bearish_candles(5), Side.LONG)
        assert result is False

    def test_btc_bearish_allows_short(self):
        with patch("bot.btc_correlation.assess_macro_bias", return_value=Side.SHORT):
            result = btc_correlation_check(_bearish_candles(), _bearish_candles(5), Side.SHORT)
        assert result is True

    def test_btc_conflicting_bias_allows_all(self):
        with patch("bot.btc_correlation.assess_macro_bias", return_value=None):
            assert btc_correlation_check(_bullish_candles(), _bullish_candles(5), Side.LONG) is True
            assert btc_correlation_check(_bullish_candles(), _bullish_candles(5), Side.SHORT) is True
