"""Tests for bot/price_fmt.py — adaptive price formatting."""
from bot.price_fmt import fmt_price


class TestFmtPrice:
    def test_large_price_btc(self):
        result = fmt_price(90000.0)
        assert result == "90,000.00"

    def test_medium_price_eth(self):
        result = fmt_price(3500.50)
        assert result == "3,500.50"

    def test_small_price_sol(self):
        result = fmt_price(25.1234)
        assert result == "25.1234"

    def test_sub_dollar(self):
        result = fmt_price(0.5678)
        assert result == "0.5678"

    def test_sub_cent(self):
        result = fmt_price(0.001234)
        assert result == "0.001234"

    def test_micro_cap(self):
        result = fmt_price(0.00001234)
        assert result == "0.00001234"

    def test_zero(self):
        result = fmt_price(0.0)
        assert result == "0.00000000"
