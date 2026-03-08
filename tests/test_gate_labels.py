"""Tests for bot/gate_labels.py — unified gate label registry."""
from bot.gate_labels import GATE_KEYS, GATE_LABELS, GATE_SYMBOLS, gate_symbols_str


class TestGateLabels:
    def test_all_keys_have_labels(self):
        for attr in dir(GATE_KEYS):
            if attr.startswith("_"):
                continue
            key = getattr(GATE_KEYS, attr)
            assert key in GATE_LABELS, f"Missing label for gate key: {key}"

    def test_all_keys_have_symbols(self):
        for attr in dir(GATE_KEYS):
            if attr.startswith("_"):
                continue
            key = getattr(GATE_KEYS, attr)
            assert key in GATE_SYMBOLS, f"Missing symbol for gate key: {key}"

    def test_gate_symbols_str(self):
        result = gate_symbols_str(["macro_bias", "zone", "sweep", "mss"])
        assert result == "①②③④"

    def test_gate_symbols_str_empty(self):
        assert gate_symbols_str([]) == ""

    def test_unknown_gate_passes_through(self):
        result = gate_symbols_str(["macro_bias", "unknown_gate"])
        assert "①" in result
        assert "unknown_gate" in result
