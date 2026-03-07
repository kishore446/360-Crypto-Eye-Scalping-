"""
Tests for bot/insights/market_briefing.py
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from bot.insights.market_briefing import (
    _fetch_fear_greed,
    _rolling_profit_factor,
    _rolling_win_rate,
    _top_worst_pairs,
    generate_daily_briefing,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_dashboard(trades: list[dict] | None = None) -> MagicMock:
    """Return a mock Dashboard with configurable trade data."""
    db = MagicMock()
    if trades is None:
        trades = []

    from bot.dashboard import TradeResult

    results = [
        TradeResult(
            symbol=t["symbol"],
            side=t.get("side", "LONG"),
            entry_price=t.get("entry_price", 100.0),
            exit_price=t.get("exit_price"),
            stop_loss=t.get("stop_loss", 95.0),
            tp1=t.get("tp1", 105.0),
            tp2=t.get("tp2", 110.0),
            tp3=t.get("tp3", 120.0),
            opened_at=t.get("opened_at", time.time() - 86400),
            closed_at=t.get("closed_at", time.time()),
            outcome=t["outcome"],
            pnl_pct=t["pnl_pct"],
            timeframe=t.get("timeframe", "5m"),
        )
        for t in trades
    ]
    db.get_closed_trades.return_value = results
    return db


def _make_risk_manager(active: list[dict] | None = None) -> MagicMock:
    """Return a mock RiskManager with configurable active signals."""
    rm = MagicMock()
    signals = []
    if active:
        from bot.signal_engine import Side

        for a in active:
            sig = MagicMock()
            sig.result.side.value = a.get("side", "LONG")
            sig.result.side = Side.LONG if a.get("side", "LONG") == "LONG" else Side.SHORT
            signals.append(sig)
    rm.active_signals = signals
    return rm


def _make_bot_state(regime: str = "BULL") -> MagicMock:
    state = MagicMock()
    state.market_regime = regime
    return state


# ── _fetch_fear_greed ─────────────────────────────────────────────────────────


class TestFetchFearGreed:
    def test_returns_na_on_network_error(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.side_effect = Exception("network error")
            value, label = _fetch_fear_greed()
        assert value == "N/A"
        assert label == "N/A"

    def test_returns_na_on_http_error(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = mock_client_cls.return_value.__enter__.return_value
            mock_ctx.get.side_effect = Exception("timeout")
            value, label = _fetch_fear_greed()
        assert value == "N/A"
        assert label == "N/A"

    def test_parses_response_correctly(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"value": "42", "value_classification": "Fear"}]
        }
        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = mock_client_cls.return_value.__enter__.return_value
            mock_ctx.get.return_value = mock_response
            value, label = _fetch_fear_greed()
        assert value == "42"
        assert label == "Fear"


# ── _rolling_win_rate ─────────────────────────────────────────────────────────


class TestRollingWinRate:
    def test_empty_dashboard(self):
        db = _make_dashboard([])
        wr, n = _rolling_win_rate(db, 7)
        assert wr == 0.0
        assert n == 0

    def test_all_wins(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 2.0, "opened_at": now - 86400},
            {"symbol": "ETH", "outcome": "WIN", "pnl_pct": 1.5, "opened_at": now - 86400},
        ])
        wr, n = _rolling_win_rate(db, 7)
        assert wr == 100.0
        assert n == 2

    def test_mixed_outcomes(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 2.0, "opened_at": now - 86400},
            {"symbol": "ETH", "outcome": "LOSS", "pnl_pct": -1.0, "opened_at": now - 86400},
            {"symbol": "SOL", "outcome": "WIN", "pnl_pct": 1.5, "opened_at": now - 86400},
            {"symbol": "ADA", "outcome": "LOSS", "pnl_pct": -0.5, "opened_at": now - 86400},
        ])
        wr, n = _rolling_win_rate(db, 7)
        assert wr == 50.0
        assert n == 4

    def test_excludes_old_trades(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 2.0, "opened_at": now - 10 * 86400},  # older than 7d
            {"symbol": "ETH", "outcome": "LOSS", "pnl_pct": -1.0, "opened_at": now - 86400},
        ])
        wr, n = _rolling_win_rate(db, 7)
        assert n == 1
        assert wr == 0.0


# ── _rolling_profit_factor ────────────────────────────────────────────────────


class TestRollingProfitFactor:
    def test_no_losses(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 2.0, "opened_at": now - 86400},
        ])
        pf = _rolling_profit_factor(db, 30)
        assert pf == 0.0  # gross_loss = 0, returns 0.0

    def test_with_wins_and_losses(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 3.0, "opened_at": now - 86400},
            {"symbol": "ETH", "outcome": "LOSS", "pnl_pct": -1.0, "opened_at": now - 86400},
        ])
        pf = _rolling_profit_factor(db, 30)
        assert pf == 3.0


# ── _top_worst_pairs ──────────────────────────────────────────────────────────


class TestTopWorstPairs:
    def test_empty_returns_na(self):
        db = _make_dashboard([])
        top, worst, tp, wp = _top_worst_pairs(db, 7)
        assert top == "N/A"
        assert worst == "N/A"

    def test_single_pair(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 2.5, "opened_at": now - 86400},
        ])
        top, worst, tp, wp = _top_worst_pairs(db, 7)
        assert top == "BTC"
        assert worst == "BTC"

    def test_multiple_pairs(self):
        now = time.time()
        db = _make_dashboard([
            {"symbol": "BTC", "outcome": "WIN", "pnl_pct": 3.0, "opened_at": now - 86400},
            {"symbol": "ETH", "outcome": "LOSS", "pnl_pct": -2.0, "opened_at": now - 86400},
            {"symbol": "SOL", "outcome": "WIN", "pnl_pct": 1.0, "opened_at": now - 86400},
        ])
        top, worst, tp, wp = _top_worst_pairs(db, 7)
        assert top == "BTC"
        assert worst == "ETH"
        assert tp == 3.0
        assert wp == -2.0


# ── generate_daily_briefing ───────────────────────────────────────────────────


class TestGenerateDailyBriefing:
    def test_returns_string(self):
        db = _make_dashboard([])
        rm = _make_risk_manager([])
        state = _make_bot_state("BULL")
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value=("50", "Neutral")):
            result = generate_daily_briefing(db, rm, state)
        assert isinstance(result, str)

    def test_contains_key_sections(self):
        db = _make_dashboard([])
        rm = _make_risk_manager([])
        state = _make_bot_state("BULL")
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value=("50", "Neutral")):
            result = generate_daily_briefing(db, rm, state)
        assert "DAILY BRIEFING" in result
        assert "Market Regime" in result
        assert "Fear & Greed" in result
        assert "Active Signals" in result
        assert "Performance" in result
        assert "Next briefing" in result

    def test_includes_regime(self):
        db = _make_dashboard([])
        rm = _make_risk_manager([])
        state = _make_bot_state("BEARISH_TREND")
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value=("20", "Extreme Fear")):
            result = generate_daily_briefing(db, rm, state)
        assert "BEARISH_TREND" in result
        assert "20" in result

    def test_active_signals_counted(self):
        db = _make_dashboard([])
        rm = _make_risk_manager([{"side": "LONG"}, {"side": "LONG"}, {"side": "SHORT"}])
        state = _make_bot_state()
        with patch("bot.insights.market_briefing._fetch_fear_greed", return_value=("N/A", "N/A")):
            result = generate_daily_briefing(db, rm, state)
        assert "3 (2 LONG, 1 SHORT)" in result
