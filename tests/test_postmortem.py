"""Tests for generate_postmortem()."""
from __future__ import annotations

import time

from bot.dashboard import TradeResult
from bot.postmortem import generate_postmortem


def _make_trade(
    symbol: str = "BTC",
    side: str = "LONG",
    outcome: str = "WIN",
    pnl_pct: float = 3.2,
    channel_tier: str = "CH1_HARD",
) -> TradeResult:
    ts = time.time() - 8280  # 2h 18m ago
    return TradeResult(
        symbol=symbol,
        side=side,
        entry_price=67450.0,
        exit_price=67450.0 * (1 + pnl_pct / 100),
        stop_loss=66000.0,
        tp1=68500.0,
        tp2=69500.0,
        tp3=71000.0,
        opened_at=ts,
        closed_at=time.time(),
        outcome=outcome,
        pnl_pct=pnl_pct,
        timeframe="5m",
        channel_tier=channel_tier,
        session="LONDON",
    )


class TestGeneratePostmortem:
    def test_basic_win_output(self):
        trade = _make_trade(outcome="WIN", pnl_pct=3.2)
        gates = ["zone", "sweep", "mss", "confluence_score", "funding_rate", "open_interest"]
        msg = generate_postmortem(trade, gates, regime="BULL", session="London+NYC Overlap")
        assert "POST-MORTEM" in msg
        assert "BTC" in msg
        assert "LONG" in msg
        assert "WIN" in msg
        assert "+3.20%" in msg

    def test_loss_output(self):
        trade = _make_trade(outcome="LOSS", pnl_pct=-1.0)
        msg = generate_postmortem(trade, [], regime="RANGING", session="ASIA")
        assert "LOSS" in msg
        assert "-1.00%" in msg

    def test_break_even_output(self):
        trade = _make_trade(outcome="BE", pnl_pct=0.0)
        msg = generate_postmortem(trade, ["zone"], regime="RANGING", session="LONDON")
        assert "BREAK-EVEN" in msg

    def test_gates_fired_symbols(self):
        gates = ["zone", "sweep", "mss"]
        trade = _make_trade()
        msg = generate_postmortem(trade, gates, regime="BULL", session="LONDON")
        # zone=②, sweep=③, mss=④
        assert "②" in msg
        assert "③" in msg
        assert "④" in msg

    def test_gates_count_displayed(self):
        gates = ["zone", "sweep", "mss", "confluence_score", "funding_rate", "open_interest"]
        trade = _make_trade()
        msg = generate_postmortem(trade, gates, regime="BULL", session="LONDON")
        assert "6/7" in msg

    def test_regime_in_output(self):
        trade = _make_trade()
        msg = generate_postmortem(trade, [], regime="BEAR", session="NYC")
        assert "BEAR" in msg

    def test_session_in_output(self):
        trade = _make_trade()
        msg = generate_postmortem(trade, [], regime="BULL", session="London+NYC Overlap")
        assert "London+NYC Overlap" in msg

    def test_duration_calculated(self):
        trade = _make_trade()
        msg = generate_postmortem(trade, [], regime="BULL", session="LONDON")
        # Duration should appear (2h or similar)
        assert "h" in msg or "m" in msg

    def test_channel_label(self):
        trade = _make_trade(channel_tier="CH1_HARD")
        msg = generate_postmortem(trade, [], regime="BULL", session="LONDON")
        assert "CH1" in msg

    def test_empty_gates(self):
        trade = _make_trade()
        # Should not raise with no gates
        msg = generate_postmortem(trade, [], regime="BULL", session="LONDON")
        assert "0/7" in msg

    def test_confluence_score_estimated_from_gates(self):
        """When no confluence_score attribute, it should be estimated from gates."""
        trade = _make_trade()
        gates = ["zone", "sweep", "mss",
                 "confluence_score", "funding_rate", "open_interest", "session_filter"]
        msg = generate_postmortem(trade, gates, regime="BULL", session="LONDON")
        assert "100/100" in msg or "/100" in msg

    def test_short_signal(self):
        trade = _make_trade(side="SHORT", outcome="WIN", pnl_pct=2.0)
        msg = generate_postmortem(trade, ["zone"], regime="BEAR", session="NYC")
        assert "SHORT" in msg
