"""Tests for bot/commands.py (user-facing commands: /market, /signals, /learn, /risk, /sectors)"""
from __future__ import annotations

from bot.commands import (
    format_learn_command,
    format_market_command,
    format_risk_command,
    format_sectors_command,
    format_signals_command,
)


class TestFormatMarketCommand:
    def test_basic_structure(self):
        msg = format_market_command(
            btc_price=95000.0,
            btc_change_24h=2.5,
            market_regime="BULL",
            fear_greed_score=65,
            fear_greed_label="Greed",
        )
        assert "MARKET OVERVIEW" in msg
        assert "BTC" in msg
        assert "$95,000.00" in msg
        assert "+2.5%" in msg

    def test_shows_regime(self):
        msg = format_market_command(market_regime="BEAR")
        assert "BEAR" in msg

    def test_shows_fear_greed(self):
        msg = format_market_command(fear_greed_score=80, fear_greed_label="Extreme Greed")
        assert "80" in msg
        assert "Extreme Greed" in msg

    def test_shows_top_movers(self):
        movers = [
            {"symbol": "SOLUSDT", "change_24h": 15.0},
            {"symbol": "BNBUSDT", "change_24h": -5.0},
        ]
        msg = format_market_command(top_movers=movers)
        assert "SOL" in msg
        assert "+15.0%" in msg

    def test_negative_change(self):
        msg = format_market_command(btc_change_24h=-3.5)
        assert "-3.5%" in msg

    def test_default_args_returns_string(self):
        msg = format_market_command()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_extreme_fear_emoji(self):
        msg = format_market_command(fear_greed_score=10)
        assert "😱" in msg

    def test_extreme_greed_emoji(self):
        msg = format_market_command(fear_greed_score=90)
        assert "🤑" in msg

    def test_bull_emoji(self):
        msg = format_market_command(market_regime="BULL")
        assert "🐂" in msg

    def test_bear_emoji(self):
        msg = format_market_command(market_regime="BEAR")
        assert "🐻" in msg


class TestFormatSignalsCommand:
    def test_no_signals(self):
        msg = format_signals_command(active_count=0)
        assert "No active signals" in msg

    def test_shows_count(self):
        msg = format_signals_command(active_count=3)
        assert "3" in msg

    def test_shows_symbol_and_side(self):
        signals = [{"symbol": "BTCUSDT", "side": "LONG", "pnl_pct": 2.5}]
        msg = format_signals_command(active_count=1, signals=signals)
        assert "BTC" in msg
        assert "LONG" in msg
        assert "+2.5%" in msg

    def test_shows_loss(self):
        signals = [{"symbol": "ETHUSDT", "side": "SHORT", "pnl_pct": -1.5}]
        msg = format_signals_command(active_count=1, signals=signals)
        assert "-1.5%" in msg

    def test_signal_without_pnl(self):
        signals = [{"symbol": "SOLUSDT", "side": "LONG"}]
        msg = format_signals_command(active_count=1, signals=signals)
        assert "SOL" in msg

    def test_max_10_shown(self):
        signals = [{"symbol": f"TOKEN{i}USDT", "side": "LONG"} for i in range(15)]
        msg = format_signals_command(active_count=15, signals=signals)
        # At most 10 tokens shown
        shown = sum(1 for i in range(15) if f"TOKEN{i}" in msg)
        assert shown <= 10


class TestFormatLearnCommand:
    def test_known_term_fvg(self):
        msg = format_learn_command("FVG")
        assert "FVG" in msg
        assert "Fair Value Gap" in msg or "imbalance" in msg.lower()

    def test_known_term_lowercase(self):
        msg = format_learn_command("ob")
        assert "OB" in msg
        assert "Order Block" in msg

    def test_unknown_term(self):
        msg = format_learn_command("XYZINVALIDTERM")
        assert "Unknown" in msg or "unknown" in msg.lower()
        assert "/learn" in msg

    def test_known_term_rsi(self):
        msg = format_learn_command("RSI")
        assert "RSI" in msg

    def test_known_term_with_spaces(self):
        msg = format_learn_command("  MSS  ")
        assert "MSS" in msg


class TestFormatRiskCommand:
    def test_basic_calculation(self):
        msg = format_risk_command(
            balance=1000.0,
            entry=95000.0,
            stop_loss=93000.0,
        )
        assert "RISK CALCULATOR" in msg
        assert "1,000" in msg or "1000" in msg

    def test_with_symbol(self):
        msg = format_risk_command(
            balance=1000.0, entry=95000.0, stop_loss=93000.0, symbol="BTC"
        )
        assert "BTC" in msg

    def test_invalid_entry_shows_error(self):
        msg = format_risk_command(balance=1000.0, entry=0.0, stop_loss=90.0)
        assert "error" in msg.lower() or "⚠️" in msg

    def test_equal_entry_sl_shows_error(self):
        msg = format_risk_command(balance=1000.0, entry=100.0, stop_loss=100.0)
        assert "error" in msg.lower() or "⚠️" in msg


class TestFormatSectorsCommand:
    def test_no_data(self):
        msg = format_sectors_command(None)
        assert "No sector data" in msg

    def test_with_data(self):
        returns = {"DeFi": 10.0, "L2": 5.0, "Meme": -3.0}
        msg = format_sectors_command(returns)
        assert "DeFi" in msg
        assert "L2" in msg
        assert "Meme" in msg

    def test_empty_dict(self):
        msg = format_sectors_command({})
        assert "No sector data" in msg or "SECTOR" in msg
