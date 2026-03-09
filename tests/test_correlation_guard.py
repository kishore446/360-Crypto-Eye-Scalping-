"""
Tests for bot/correlation_guard.py
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.correlation_guard import CORRELATION_GROUPS, check_correlation_risk

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(symbol: str, side: str = "LONG", closed: bool = False) -> MagicMock:
    sig = MagicMock()
    sig.result.symbol = symbol.upper()
    sig.result.side.value = side
    sig.closed = closed
    return sig


# ── check_correlation_risk ────────────────────────────────────────────────────


class TestCheckCorrelationRisk:
    def test_empty_signals_returns_none(self):
        assert check_correlation_risk([]) is None

    def test_below_threshold_returns_none(self):
        signals = [_make_signal("BTC", "LONG"), _make_signal("ETH", "LONG")]
        assert check_correlation_risk(signals, max_same_group=3) is None

    def test_triggers_when_at_threshold(self):
        # BTC_GROUP has BTC, ETH, SOL, AVAX, NEAR — check BTC + ETH at max_same_group=2
        signals = [_make_signal("BTC", "LONG"), _make_signal("ETH", "LONG")]
        result = check_correlation_risk(signals, max_same_group=2)
        assert result is not None
        assert "CORRELATION ALERT" in result
        assert "BTC_GROUP" in result

    def test_different_sides_no_trigger(self):
        # 2 LONG + 1 SHORT — same group but different sides, won't trigger at 3
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("ETH", "LONG"),
            _make_signal("BTC", "SHORT"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_btc_group_trigger(self):
        # BTC_GROUP expanded: BTC, ETH, SOL, AVAX, NEAR
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("SOL", "LONG"),
            _make_signal("AVAX", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "BTC_GROUP" in result
        assert "LONG" in result

    def test_meme_group_trigger(self):
        signals = [
            _make_signal("DOGE", "SHORT"),
            _make_signal("SHIB", "SHORT"),
            _make_signal("PEPE", "SHORT"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "MEME_GROUP" in result

    def test_closed_signals_excluded(self):
        signals = [
            _make_signal("BTC", "LONG", closed=True),
            _make_signal("ETH", "LONG", closed=True),
            _make_signal("SOL", "LONG", closed=False),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_symbols_from_different_groups_no_trigger(self):
        # BTC in BTC_GROUP, DOGE in MEME_GROUP, ARB in L2_GROUP — each in a different group
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("DOGE", "LONG"),
            _make_signal("ARB", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=2)
        # Each symbol in a different group, no group has >=2 signals
        assert result is None

    def test_alert_message_contains_symbols(self):
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("SOL", "LONG"),
            _make_signal("AVAX", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        # At least one of the symbols should appear in the alert
        assert any(sym in result for sym in ("BTC", "SOL", "AVAX"))

    def test_custom_max_same_group(self):
        signals = [_make_signal("MATIC", "SHORT"), _make_signal("ARB", "SHORT")]
        # At max_same_group=2, should trigger (both in L2_GROUP)
        result = check_correlation_risk(signals, max_same_group=2)
        assert result is not None
        # At max_same_group=3, should not trigger
        result2 = check_correlation_risk(signals, max_same_group=3)
        assert result2 is None


# ── CORRELATION_GROUPS ────────────────────────────────────────────────────────


class TestCorrelationGroups:
    def test_all_expected_groups_present(self):
        expected = {"BTC_GROUP", "MEME_GROUP", "L2_GROUP", "DEFI_GROUP"}
        assert set(CORRELATION_GROUPS.keys()) == expected

    def test_btc_group_contains_btc_eth_sol(self):
        assert "BTC" in CORRELATION_GROUPS["BTC_GROUP"]
        assert "ETH" in CORRELATION_GROUPS["BTC_GROUP"]
        assert "SOL" in CORRELATION_GROUPS["BTC_GROUP"]

    def test_l2_group_has_matic_and_arb(self):
        assert "MATIC" in CORRELATION_GROUPS["L2_GROUP"]
        assert "ARB" in CORRELATION_GROUPS["L2_GROUP"]

