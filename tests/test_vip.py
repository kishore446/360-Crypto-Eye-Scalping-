"""Tests for bot/channels/vip.py"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import bot.channels.vip as vip_mod
from bot.channels.vip import (
    add_alert,
    add_position,
    calculate_risk,
    check_alerts,
    format_risk_calculator,
    format_signal_replay,
    get_portfolio_summary,
    get_target_channel_id,
    remove_alert,
    remove_position,
)


@pytest.fixture(autouse=True)
def _clear_state():
    """Reset in-memory portfolio and alerts between tests."""
    vip_mod._portfolios.clear()
    vip_mod._alerts.clear()
    yield
    vip_mod._portfolios.clear()
    vip_mod._alerts.clear()


# ── Portfolio CRUD ────────────────────────────────────────────────────────────


class TestPortfolioCRUD:
    def test_add_position(self):
        add_position(chat_id=1, symbol="BTC", quantity=0.5, entry_price=95000.0)
        entries = vip_mod._portfolios[1]
        assert len(entries) == 1
        assert entries[0].symbol == "BTC"
        assert entries[0].quantity == pytest.approx(0.5)

    def test_add_position_normalises_symbol_uppercase(self):
        add_position(chat_id=1, symbol="btcusdt", quantity=1.0, entry_price=90000.0)
        assert vip_mod._portfolios[1][0].symbol == "BTCUSDT"

    def test_update_existing_position(self):
        add_position(chat_id=1, symbol="ETH", quantity=5.0, entry_price=3000.0)
        add_position(chat_id=1, symbol="ETH", quantity=10.0, entry_price=3200.0)
        entries = vip_mod._portfolios[1]
        assert len(entries) == 1  # updated, not duplicated
        assert entries[0].quantity == pytest.approx(10.0)
        assert entries[0].entry_price == pytest.approx(3200.0)

    def test_remove_existing_position(self):
        add_position(chat_id=1, symbol="BTC", quantity=1.0, entry_price=95000.0)
        result = remove_position(chat_id=1, symbol="BTC")
        assert result is True
        assert len(vip_mod._portfolios[1]) == 0

    def test_remove_nonexistent_position(self):
        result = remove_position(chat_id=1, symbol="NONEXISTENT")
        assert result is False

    def test_portfolio_limit(self, monkeypatch):
        monkeypatch.setattr(vip_mod, "VIP_MAX_PORTFOLIO_ENTRIES", 2)
        add_position(chat_id=1, symbol="BTC", quantity=1.0, entry_price=95000.0)
        add_position(chat_id=1, symbol="ETH", quantity=1.0, entry_price=3000.0)
        with pytest.raises(ValueError, match="Portfolio limit"):
            add_position(chat_id=1, symbol="SOL", quantity=10.0, entry_price=200.0)


# ── Portfolio summary ─────────────────────────────────────────────────────────


class TestPortfolioSummary:
    def test_empty_portfolio_message(self):
        msg = get_portfolio_summary(chat_id=1, current_prices={})
        assert "empty" in msg.lower()

    def test_summary_with_profit(self):
        add_position(chat_id=1, symbol="BTC", quantity=0.5, entry_price=95000.0)
        msg = get_portfolio_summary(chat_id=1, current_prices={"BTCUSDT": 97500.0})
        assert "BTC" in msg
        assert "✅" in msg
        assert "+2.63%" in msg or "+2.6" in msg

    def test_summary_with_loss(self):
        add_position(chat_id=1, symbol="ETH", quantity=5.0, entry_price=3200.0)
        msg = get_portfolio_summary(chat_id=1, current_prices={"ETHUSDT": 3150.0})
        assert "🔻" in msg

    def test_summary_total_pnl(self):
        add_position(chat_id=1, symbol="BTC", quantity=1.0, entry_price=100.0)
        add_position(chat_id=1, symbol="ETHUSDT", quantity=1.0, entry_price=100.0)
        msg = get_portfolio_summary(
            chat_id=1,
            current_prices={"BTCUSDT": 110.0, "ETHUSDT": 110.0},
        )
        assert "Total P&L" in msg
        assert "+$20.00" in msg

    def test_summary_uses_fallback_price(self):
        """If BTCUSDT not in prices but BTC is, use BTC price."""
        add_position(chat_id=1, symbol="BTC", quantity=1.0, entry_price=100.0)
        msg = get_portfolio_summary(chat_id=1, current_prices={"BTC": 110.0})
        assert "BTC" in msg


# ── Risk calculator ───────────────────────────────────────────────────────────


class TestRiskCalculator:
    def test_basic_calculation(self):
        result = calculate_risk(
            balance=1000.0,
            entry_price=95000.0,
            stop_loss=93000.0,
            risk_pct=1.0,
        )
        assert result["risk_amount"] == pytest.approx(10.0)
        assert result["position_size"] == pytest.approx(475.0)
        assert abs(result["quantity"] - 0.005) < 1e-6

    def test_with_take_profit(self):
        result = calculate_risk(
            balance=1000.0,
            entry_price=100.0,
            stop_loss=90.0,
            risk_pct=1.0,
            take_profit=120.0,
        )
        assert result["risk_reward"] == pytest.approx(2.0)

    def test_invalid_entry_price(self):
        with pytest.raises(ValueError, match="entry_price"):
            calculate_risk(1000.0, 0.0, 90.0)

    def test_invalid_stop_loss(self):
        with pytest.raises(ValueError, match="stop_loss"):
            calculate_risk(1000.0, 100.0, 0.0)

    def test_invalid_balance(self):
        with pytest.raises(ValueError, match="balance"):
            calculate_risk(0.0, 100.0, 90.0)

    def test_equal_entry_and_sl(self):
        with pytest.raises(ValueError, match="equal"):
            calculate_risk(1000.0, 100.0, 100.0)

    def test_risk_pct_zero(self):
        with pytest.raises(ValueError, match="risk_pct"):
            calculate_risk(1000.0, 100.0, 90.0, risk_pct=0.0)

    def test_format_risk_calculator(self):
        msg = format_risk_calculator(
            balance=1000.0,
            entry_price=95000.0,
            stop_loss=93000.0,
            risk_pct=1.0,
            symbol="BTC",
        )
        assert "RISK CALCULATOR" in msg
        assert "$1,000.00" in msg
        assert "$95,000.00" in msg
        assert "BTC" in msg

    def test_format_with_tp(self):
        msg = format_risk_calculator(
            balance=1000.0,
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
        )
        assert "R:R" in msg


# ── Price alerts ──────────────────────────────────────────────────────────────


class TestPriceAlerts:
    def test_add_alert_above(self):
        add_alert(chat_id=1, symbol="BTC", direction="above", target_price=100000.0)
        assert len(vip_mod._alerts[1]) == 1

    def test_add_alert_below(self):
        add_alert(chat_id=1, symbol="BTC", direction="below", target_price=80000.0)
        assert len(vip_mod._alerts[1]) == 1

    def test_invalid_direction(self):
        with pytest.raises(ValueError, match="direction"):
            add_alert(chat_id=1, symbol="BTC", direction="sideways", target_price=100000.0)

    def test_alert_limit(self, monkeypatch):
        monkeypatch.setattr(vip_mod, "VIP_MAX_ALERTS_PER_USER", 2)
        add_alert(chat_id=1, symbol="BTC", direction="above", target_price=100000.0)
        add_alert(chat_id=1, symbol="ETH", direction="below", target_price=2000.0)
        with pytest.raises(ValueError, match="Alert limit"):
            add_alert(chat_id=1, symbol="SOL", direction="above", target_price=300.0)

    def test_remove_alert(self):
        add_alert(chat_id=1, symbol="BTC", direction="above", target_price=100000.0)
        result = remove_alert(chat_id=1, symbol="BTC")
        assert result is True
        assert len(vip_mod._alerts[1]) == 0

    def test_remove_nonexistent_alert(self):
        result = remove_alert(chat_id=1, symbol="NONEXISTENT")
        assert result is False

    def test_check_alert_above_triggered(self):
        add_alert(chat_id=1, symbol="BTC", direction="above", target_price=95000.0)
        triggered = check_alerts({"BTCUSDT": 96000.0})
        assert len(triggered) == 1
        assert triggered[0].chat_id == 1
        assert triggered[0].alert.symbol == "BTC"
        # Alert should be removed after triggering
        assert len(vip_mod._alerts.get(1, [])) == 0

    def test_check_alert_below_triggered(self):
        add_alert(chat_id=1, symbol="ETH", direction="below", target_price=3000.0)
        triggered = check_alerts({"ETHUSDT": 2900.0})
        assert len(triggered) == 1

    def test_check_alert_not_triggered(self):
        add_alert(chat_id=1, symbol="BTC", direction="above", target_price=100000.0)
        triggered = check_alerts({"BTCUSDT": 95000.0})
        assert len(triggered) == 0
        # Alert should still be there
        assert len(vip_mod._alerts[1]) == 1

    def test_check_alert_missing_price_skipped(self):
        add_alert(chat_id=1, symbol="XYZ", direction="above", target_price=100.0)
        triggered = check_alerts({"BTCUSDT": 95000.0})
        assert len(triggered) == 0
        # Alert stays
        assert len(vip_mod._alerts[1]) == 1


# ── Signal performance replay ─────────────────────────────────────────────────


class TestSignalReplay:
    def _make_dashboard(self, trades: list) -> MagicMock:
        dash = MagicMock()
        dash.trades = trades
        return dash

    def _make_trade(self, symbol: str, pnl: float, days_ago: int, side: str = "LONG"):
        trade = MagicMock()
        trade.symbol = symbol
        trade.pnl_pct = pnl
        trade.side = side
        trade.closed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return trade

    def test_empty_dashboard(self):
        dash = self._make_dashboard([])
        msg = format_signal_replay(dash, days=7)
        assert "No signals" in msg or "No closed" in msg

    def test_replay_with_trades(self):
        trades = [
            self._make_trade("BTCUSDT", 5.0, 1),
            self._make_trade("ETHUSDT", -2.0, 2),
        ]
        dash = self._make_dashboard(trades)
        msg = format_signal_replay(dash, days=7)
        assert "SIGNAL REPLAY" in msg
        assert "BTC" in msg or "BTCUSDT" in msg
        assert "Win Rate" in msg

    def test_replay_filters_by_days(self):
        trades = [
            self._make_trade("BTCUSDT", 5.0, 1),
            self._make_trade("ETHUSDT", 3.0, 10),  # older than 7 days
        ]
        dash = self._make_dashboard(trades)
        msg = format_signal_replay(dash, days=7)
        assert "BTCUSDT" in msg or "BTC" in msg

    def test_replay_no_trades_attr(self):
        dash = MagicMock(spec=[])  # no trades attr
        msg = format_signal_replay(dash, days=7)
        assert "No signal history" in msg or "No signals" in msg


# ── Channel ID guard ──────────────────────────────────────────────────────────


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
