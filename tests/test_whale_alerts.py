"""Tests for whale alert, liquidation, and funding dashboard formatters."""
from __future__ import annotations

import pytest

from bot.insights.whale_alerts import WhaleAlertMonitor
from bot.insights.liquidation_map import LiquidationMonitor
from bot.insights.funding_dashboard import format_funding_dashboard


# ── Whale Alert ──────────────────────────────────────────────────────────────

class TestWhaleAlertMonitor:
    @pytest.fixture()
    def monitor(self):
        return WhaleAlertMonitor()

    def test_format_whale_alert_inflow(self, monitor):
        msg = monitor.format_whale_alert(
            symbol="BTC",
            direction="Exchange Inflow (bearish signal)",
            amount_usd=47_200_000.0,
            exchange_name="Binance",
            amount_units=682,
        )
        assert "🐋" in msg
        assert "BTC" in msg
        assert "Inflow" in msg
        assert "47.2M" in msg
        assert "682 BTC" in msg
        assert "Binance" in msg
        assert "inflows" in msg.lower()

    def test_format_whale_alert_outflow(self, monitor):
        msg = monitor.format_whale_alert(
            symbol="ETH",
            direction="Exchange Outflow (bullish signal)",
            amount_usd=20_000_000.0,
            exchange_name="Coinbase",
        )
        assert "Outflow" in msg
        assert "ETH" in msg
        assert "outflows" in msg.lower() or "accumulation" in msg.lower()

    def test_format_whale_alert_no_units(self, monitor):
        msg = monitor.format_whale_alert(
            symbol="SOL",
            direction="Exchange Inflow (bearish signal)",
            amount_usd=10_000_000.0,
            exchange_name="Kraken",
            amount_units=0.0,
        )
        # No unit count when 0
        assert "SOL" in msg
        assert "Kraken" in msg

    def test_bearish_warning_for_inflow(self, monitor):
        msg = monitor.format_whale_alert(
            symbol="BTC",
            direction="Exchange Inflow (bearish signal)",
            amount_usd=50_000_000.0,
            exchange_name="Binance",
        )
        assert "sell pressure" in msg.lower() or "inflow" in msg.lower()

    def test_bullish_note_for_outflow(self, monitor):
        msg = monitor.format_whale_alert(
            symbol="BTC",
            direction="Exchange Outflow (bullish signal)",
            amount_usd=50_000_000.0,
            exchange_name="Binance",
        )
        assert "accumulation" in msg.lower() or "outflow" in msg.lower()


# ── Liquidation Monitor ──────────────────────────────────────────────────────

class TestLiquidationMonitor:
    @pytest.fixture()
    def monitor(self):
        return LiquidationMonitor()

    def test_format_liquidation_alert_basic(self, monitor):
        msg = monitor.format_liquidation_alert(
            total_liquidated_usd=142_300_000.0,
            dominant_side="LONGS",
            top_pairs=[("BTC", 52_000_000), ("ETH", 38_000_000), ("SOL", 12_000_000)],
            dominant_pct=78.0,
        )
        assert "💥" in msg
        assert "142.3M" in msg
        assert "LONGS" in msg
        assert "78%" in msg
        assert "BTC" in msg
        assert "ETH" in msg

    def test_format_liquidation_alert_shorts_dominant(self, monitor):
        msg = monitor.format_liquidation_alert(
            total_liquidated_usd=80_000_000.0,
            dominant_side="SHORTS",
            top_pairs=[("BTC", 40_000_000)],
            dominant_pct=65.0,
        )
        assert "SHORTS" in msg
        assert "65%" in msg

    def test_format_liquidation_alert_avoid_warning(self, monitor):
        msg = monitor.format_liquidation_alert(
            total_liquidated_usd=100_000_000.0,
            dominant_side="LONGS",
            top_pairs=[],
        )
        assert "avoid" in msg.lower() or "30min" in msg.lower()

    def test_format_liquidation_alert_empty_pairs(self, monitor):
        msg = monitor.format_liquidation_alert(
            total_liquidated_usd=50_000_000.0,
            dominant_side="LONGS",
            top_pairs=[],
        )
        assert "💥" in msg


# ── Funding Dashboard ────────────────────────────────────────────────────────

class TestFundingDashboard:
    def test_format_basic(self):
        rates = {
            "BTC": 0.0521,
            "ETH": 0.0312,
            "DOGE": -0.0342,
            "SOL": -0.0189,
        }
        msg = format_funding_dashboard(rates)
        assert "💰" in msg
        assert "BTC" in msg
        assert "DOGE" in msg
        assert "🔴" in msg  # negative / short-crowded
        assert "🟢" in msg  # positive / long-crowded

    def test_format_shows_rates(self):
        rates = {"BTC": 0.0521}
        msg = format_funding_dashboard(rates)
        assert "0.0521" in msg

    def test_format_empty_rates(self):
        msg = format_funding_dashboard({})
        assert "No data" in msg

    def test_format_squeeze_warning(self):
        rates = {"BTC": 0.1, "ETH": -0.1}
        msg = format_funding_dashboard(rates)
        assert "squeeze" in msg.lower() or "extreme" in msg.lower()

    def test_format_only_positive(self):
        rates = {"BTC": 0.05, "ETH": 0.03}
        msg = format_funding_dashboard(rates)
        assert "🟢" in msg

    def test_format_only_negative(self):
        rates = {"DOGE": -0.03, "SOL": -0.01}
        msg = format_funding_dashboard(rates)
        assert "🔴" in msg
