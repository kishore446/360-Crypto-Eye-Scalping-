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
        # BTC_MAJORS group has BTC, ETH — only 2 members, so need max_same_group=2
        signals = [_make_signal("BTC", "LONG"), _make_signal("ETH", "LONG")]
        result = check_correlation_risk(signals, max_same_group=2)
        assert result is not None
        assert "CORRELATION ALERT" in result
        assert "BTC_MAJORS" in result

    def test_different_sides_no_trigger(self):
        # 2 LONG + 1 SHORT — same group but different sides, won't trigger at 3
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("ETH", "LONG"),
            _make_signal("BTC", "SHORT"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_l1_alts_group_trigger(self):
        signals = [
            _make_signal("SOL", "LONG"),
            _make_signal("ADA", "LONG"),
            _make_signal("AVAX", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "L1_ALTS" in result
        assert "LONG" in result

    def test_meme_group_trigger(self):
        signals = [
            _make_signal("DOGE", "SHORT"),
            _make_signal("SHIB", "SHORT"),
            _make_signal("PEPE", "SHORT"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        assert "MEME" in result

    def test_closed_signals_excluded(self):
        signals = [
            _make_signal("SOL", "LONG", closed=True),
            _make_signal("ADA", "LONG", closed=True),
            _make_signal("AVAX", "LONG", closed=False),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is None

    def test_symbols_from_different_groups_no_trigger(self):
        signals = [
            _make_signal("BTC", "LONG"),
            _make_signal("SOL", "LONG"),
            _make_signal("DOGE", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=2)
        # Each symbol in a different group, no group has ≥2 signals
        assert result is None

    def test_alert_message_contains_symbols(self):
        signals = [
            _make_signal("SOL", "LONG"),
            _make_signal("ADA", "LONG"),
            _make_signal("AVAX", "LONG"),
        ]
        result = check_correlation_risk(signals, max_same_group=3)
        assert result is not None
        # At least one of the symbols should appear in the alert
        assert any(sym in result for sym in ("SOL", "ADA", "AVAX"))

    def test_custom_max_same_group(self):
        signals = [_make_signal("MATIC", "SHORT"), _make_signal("ARB", "SHORT")]
        # At max_same_group=2, should trigger
        result = check_correlation_risk(signals, max_same_group=2)
        assert result is not None
        # At max_same_group=3, should not trigger
        result2 = check_correlation_risk(signals, max_same_group=3)
        assert result2 is None


# ── CORRELATION_GROUPS ────────────────────────────────────────────────────────


class TestCorrelationGroups:
    def test_all_expected_groups_present(self):
        expected = {"BTC_MAJORS", "L1_ALTS", "MEME", "DEFI", "L2"}
        assert set(CORRELATION_GROUPS.keys()) == expected

    def test_btc_majors_contains_btc_and_eth(self):
        assert "BTC" in CORRELATION_GROUPS["BTC_MAJORS"]
        assert "ETH" in CORRELATION_GROUPS["BTC_MAJORS"]

    def test_l2_group_has_matic(self):
        assert "MATIC" in CORRELATION_GROUPS["L2"]
