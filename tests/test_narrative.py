"""
Tests for bot/narrative.py — signal narrative generator.
"""
from __future__ import annotations

from bot.narrative import generate_signal_narrative


class TestGenerateSignalNarrative:
    def test_returns_two_strings(self):
        structure, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias", "zone", "sweep", "mss"],
        )
        assert isinstance(structure, str)
        assert isinstance(context, str)

    def test_structure_note_contains_direction(self):
        structure, _ = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias"],
        )
        assert "Bullish" in structure

    def test_structure_note_bearish(self):
        structure, _ = generate_signal_narrative(
            symbol="ETH",
            side="SHORT",
            confidence="Medium",
            gates_fired=["macro_bias"],
        )
        assert "Bearish" in structure

    def test_context_note_includes_symbol_and_confidence(self):
        _, context = generate_signal_narrative(
            symbol="SOL",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias", "zone"],
        )
        assert "SOL" in context
        assert "High" in context

    def test_context_note_includes_regime_when_provided(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias"],
            regime="BULL",
        )
        assert "bull" in context.lower()

    def test_bear_regime_in_context(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="SHORT",
            confidence="Medium",
            gates_fired=["macro_bias"],
            regime="BEAR",
        )
        assert "bear" in context.lower()

    def test_sideways_regime_in_context(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="Low",
            gates_fired=["zone"],
            regime="SIDEWAYS",
        )
        assert "sideways" in context.lower() or "ranging" in context.lower()

    def test_no_regime_omits_regime_from_context(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias"],
            regime=None,
        )
        assert "regime" not in context.lower()

    def test_confluence_score_included_when_positive(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias"],
            confluence_score=75,
        )
        assert "75" in context

    def test_zero_confluence_score_omitted(self):
        _, context = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias"],
            confluence_score=0,
        )
        assert "/100" not in context

    def test_structure_detail_used_when_provided(self):
        structure, _ = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=[],
            structure_detail="4H bullish OB at 42500",
        )
        assert "4H bullish OB at 42500" in structure

    def test_many_gates_mentions_count(self):
        structure, _ = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=["macro_bias", "zone", "sweep", "mss", "fvg", "order_block"],
        )
        assert "6" in structure or "gates" in structure.lower()

    def test_empty_gates_produces_generic_note(self):
        structure, _ = generate_signal_narrative(
            symbol="BTC",
            side="LONG",
            confidence="High",
            gates_fired=[],
        )
        assert "Bullish" in structure
        assert isinstance(structure, str) and len(structure) > 0
