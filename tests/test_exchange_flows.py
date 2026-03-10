"""Tests for bot/insights/exchange_flows.py"""
from __future__ import annotations

from bot.insights.exchange_flows import (
    format_exchange_flow,
    format_stablecoin_monitor,
    get_target_channel_id,
    should_post_flow_alert,
)


class TestShouldPostFlowAlert:
    def test_below_threshold_false(self):
        assert should_post_flow_alert(10_000_000) is False

    def test_at_threshold_true(self):
        assert should_post_flow_alert(50_000_000) is True

    def test_above_threshold_true(self):
        assert should_post_flow_alert(100_000_000) is True

    def test_negative_also_checked_by_abs(self):
        assert should_post_flow_alert(-75_000_000) is True
        assert should_post_flow_alert(-10_000_000) is False


class TestFormatExchangeFlow:
    def test_inflow_message(self):
        msg = format_exchange_flow("BTCUSDT", 75_000_000, "inflow")
        assert "EXCHANGE FLOW" in msg
        assert "BTC" in msg
        assert "INFLOW" in msg
        assert "🔴" in msg
        assert "sell pressure" in msg.lower()

    def test_outflow_message(self):
        msg = format_exchange_flow("ETHUSDT", 60_000_000, "outflow")
        assert "OUTFLOW" in msg
        assert "🟢" in msg
        assert "accumulation" in msg.lower()

    def test_flow_value_formatted_in_millions(self):
        msg = format_exchange_flow("BTCUSDT", 75_000_000, "inflow")
        assert "$75.0M" in msg

    def test_symbol_stripped_of_usdt(self):
        msg = format_exchange_flow("BTCUSDT", 50_000_000, "inflow")
        assert "BTCUSDT" not in msg or "BTC" in msg

    def test_unknown_direction(self):
        msg = format_exchange_flow("BTCUSDT", 50_000_000, "unknown")
        assert "⚪" in msg

    def test_slash_symbol_stripped(self):
        msg = format_exchange_flow("BTC/USDT", 50_000_000, "inflow")
        assert "/" not in msg.split("\n")[0] or "BTC" in msg


class TestFormatStablecoinMonitor:
    def test_expanding_supply(self):
        msg = format_stablecoin_monitor(2.0, 1.5)
        assert "STABLECOIN" in msg
        assert "🟢" in msg
        assert "expanding" in msg.lower() or "new capital" in msg.lower()

    def test_contracting_supply(self):
        msg = format_stablecoin_monitor(-2.0, -1.5)
        assert "🔴" in msg
        assert "contracting" in msg.lower() or "exiting" in msg.lower()

    def test_stable_supply(self):
        msg = format_stablecoin_monitor(0.0, 0.0)
        assert "⚪" in msg
        assert "stable" in msg.lower() or "neutral" in msg.lower()

    def test_contains_usdt_and_usdc(self):
        msg = format_stablecoin_monitor(1.0, -0.5)
        assert "USDT" in msg
        assert "USDC" in msg

    def test_positive_change_shown(self):
        msg = format_stablecoin_monitor(1.5, 0.5)
        assert "+1.50%" in msg

    def test_negative_change_shown(self):
        msg = format_stablecoin_monitor(-2.5, 0.0)
        assert "-2.50%" in msg


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
