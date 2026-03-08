"""
Unified Gate Label Registry
============================
Single source of truth for gate keys and display labels used across
narrative.py, postmortem.py, and any future gate-related modules.
"""
from __future__ import annotations

__all__ = ["GATE_KEYS", "GATE_LABELS", "GATE_SYMBOLS", "gate_symbols_str"]


# Canonical gate keys — used throughout the codebase
class GATE_KEYS:
    MACRO_BIAS = "macro_bias"
    ZONE = "zone"
    SWEEP = "sweep"
    MSS = "mss"
    NEWS = "news"
    FVG = "fvg"
    ORDER_BLOCK = "order_block"
    CONFLUENCE_SCORE = "confluence_score"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    SESSION_FILTER = "session_filter"


# Human-readable labels
GATE_LABELS: dict[str, str] = {
    GATE_KEYS.MACRO_BIAS: "Macro Bias (Gate ①)",
    GATE_KEYS.ZONE: "Discount/Premium Zone (Gate ②)",
    GATE_KEYS.SWEEP: "Liquidity Sweep (Gate ③)",
    GATE_KEYS.MSS: "Market Structure Shift (Gate ④)",
    GATE_KEYS.NEWS: "News Filter (Gate ⑤)",
    GATE_KEYS.FVG: "Fair Value Gap (Gate ⑥)",
    GATE_KEYS.ORDER_BLOCK: "Order Block (Gate ⑦)",
    GATE_KEYS.CONFLUENCE_SCORE: "Confluence Score",
    GATE_KEYS.FUNDING_RATE: "Funding Rate",
    GATE_KEYS.OPEN_INTEREST: "Open Interest",
    GATE_KEYS.SESSION_FILTER: "Session Filter",
}

# Circled number symbols for compact display
GATE_SYMBOLS: dict[str, str] = {
    GATE_KEYS.MACRO_BIAS: "①",
    GATE_KEYS.ZONE: "②",
    GATE_KEYS.SWEEP: "③",
    GATE_KEYS.MSS: "④",
    GATE_KEYS.NEWS: "⑤",
    GATE_KEYS.FVG: "⑥",
    GATE_KEYS.ORDER_BLOCK: "⑦",
    GATE_KEYS.CONFLUENCE_SCORE: "④",
    GATE_KEYS.FUNDING_RATE: "⑤",
    GATE_KEYS.OPEN_INTEREST: "⑥",
    GATE_KEYS.SESSION_FILTER: "⑦",
}


def gate_symbols_str(gates_fired: list[str]) -> str:
    """Format a list of gate keys to '①②③④' style string."""
    symbols = [GATE_SYMBOLS.get(g, g) for g in gates_fired]
    return "".join(symbols)
