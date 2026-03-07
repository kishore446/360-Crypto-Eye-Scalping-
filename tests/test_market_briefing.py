"""Tests for bot/insights/market_briefing.py"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from bot.insights.market_briefing import (
    _fetch_fear_greed,
    _rolling_profit_factor,
    _rolling_trade_count,
    _rolling_win_rate,
    _top_worst_pairs,
    generate_daily_briefing,
)

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_trade(symbol: str, outcome: str, pnl_pct: float, days_ago: float = 1.0):
    """Create a minimal mock TradeResult."""
    t = MagicMock()
    t.symbol = symbol
    t.outcome = outcome
    t.pnl_pct = pnl_pct
    t.closed_at = time.time() - days_ago * 86400
    return t


def _make_dashboard(trades=None):
    db = MagicMock()
    db.get_closed_trades.return_value = trades or []
    return db


def _make_risk_manager(active_signals=None):
    rm = MagicMock()
    rm.active_signals = active_signals or []
    return rm


def _make_bot_state(regime: str = "BULL"):
    bs = MagicMock()
    bs.market_regime = regime
    return bs


# ── FearGreed ──────────────────────────────────────────────────────────────────

class TestFetchFearGreed:
    def test_returns_na_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = _fetch_fear_greed()
        assert result == "N/A"

    def test_parses_valid_response(self):
        import json
        mock_data = json.dumps({
            "data": [{"value": "72", "value_classification": "Greed"}]
        }).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_data)))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_ctx):
            result = _fetch_fear_greed()
        assert "72" in result
        assert "Greed" in result


# ── Rolling stats ──────────────────────────────────────────────────────────────

class TestRollingStats:
    def test_win_rate_empty(self):
        assert _rolling_win_rate(_make_dashboard(), days=7) == 0.0

    def test_win_rate_all_wins(self):
        trades = [_make_trade("BTC", "WIN", 2.0) for _ in range(5)]
        assert _rolling_win_rate(_make_dashboard(trades), days=7) == 100.0

    def test_win_rate_mixed(self):
        trades = [
            _make_trade("BTC", "WIN", 2.0),
            _make_trade("BTC", "LOSS", -1.0),
            _make_trade("BTC", "WIN", 1.5),
            _make_trade("BTC", "LOSS", -0.8),
        ]
        wr = _rolling_win_rate(_make_dashboard(trades), days=7)
        assert wr == pytest.approx(50.0)

    def test_win_rate_ignores_old_trades(self):
        old_trade = _make_trade("BTC", "WIN", 2.0, days_ago=10)
        db = _make_dashboard([old_trade])
        assert _rolling_win_rate(db, days=7) == 0.0

    def test_trade_count(self):
        trades = [_make_trade("BTC", "WIN", 2.0) for _ in range(4)]
        assert _rolling_trade_count(_make_dashboard(trades), days=7) == 4

    def test_profit_factor_no_losses(self):
        trades = [_make_trade("BTC", "WIN", 2.0)]
        assert _rolling_profit_factor(_make_dashboard(trades), days=7) == 2.0

    def test_profit_factor_computed(self):
        trades = [
            _make_trade("BTC", "WIN", 4.0),
            _make_trade("BTC", "LOSS", -2.0),
        ]
        pf = _rolling_profit_factor(_make_dashboard(trades), days=7)
        assert pf == pytest.approx(2.0)


# ── Top/worst pairs ────────────────────────────────────────────────────────────

class TestTopWorstPairs:
    def test_returns_empty_when_no_trades(self):
        top, tp, worst, wp = _top_worst_pairs(_make_dashboard(), days=7)
        assert top == ""
        assert worst == ""

    def test_identifies_top_and_worst(self):
        trades = [
            _make_trade("SOL", "WIN", 5.0),
            _make_trade("SOL", "WIN", 3.0),
            _make_trade("DOGE", "LOSS", -2.0),
            _make_trade("DOGE", "LOSS", -1.0),
        ]
        top, tp, worst, wp = _top_worst_pairs(_make_dashboard(trades), days=7)
        assert top == "SOL"
        assert worst == "DOGE"
        assert tp > 0
        assert wp < 0


# ── Full generate_daily_briefing ───────────────────────────────────────────────

class TestGenerateDailyBriefing:
    def test_returns_string(self):
        with patch(
            "bot.insights.market_briefing._fetch_fear_greed",
            return_value="65 (Greed)",
        ):
            result = generate_daily_briefing(
                dashboard=_make_dashboard(),
                risk_manager=_make_risk_manager(),
                bot_state=_make_bot_state("BULL"),
            )
        assert isinstance(result, str)
        assert "DAILY BRIEFING" in result

    def test_contains_regime(self):
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value="N/A"):
            result = generate_daily_briefing(
                _make_dashboard(), _make_risk_manager(), _make_bot_state("BEAR")
            )
        assert "BEAR" in result

    def test_counts_active_signals(self):
        sig_long = MagicMock()
        sig_long.result.side.value = "LONG"
        sig_short = MagicMock()
        sig_short.result.side.value = "SHORT"

        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value="N/A"):
            result = generate_daily_briefing(
                _make_dashboard(),
                _make_risk_manager([sig_long, sig_short]),
                _make_bot_state(),
            )
        assert "2 (1 LONG, 1 SHORT)" in result

    def test_shows_fear_greed_na_on_failure(self):
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value="N/A"):
            result = generate_daily_briefing(
                _make_dashboard(), _make_risk_manager(), _make_bot_state()
            )
        assert "N/A" in result

    def test_includes_next_briefing_line(self):
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value="N/A"):
            result = generate_daily_briefing(
                _make_dashboard(), _make_risk_manager(), _make_bot_state()
            )
        assert "08:00 UTC" in result
