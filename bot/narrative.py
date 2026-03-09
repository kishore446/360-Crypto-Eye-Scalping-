"""
Narrative Generator
===================
Generates context-rich signal narrative descriptions that replace generic
``structure_note`` / ``context_note`` templates with specifics about which
confluence gates fired strongest, the pattern detected, and the market regime.
"""
from __future__ import annotations

from typing import Optional

from bot.gate_labels import GATE_LABELS as _GATE_LABELS

__all__ = ["generate_signal_narrative"]


def generate_signal_narrative(
    symbol: str,
    side: str,
    confidence: str,
    gates_fired: list[str],
    regime: Optional[str] = None,
    confluence_score: int = 0,
    structure_detail: Optional[str] = None,
) -> tuple[str, str]:
    """
    Generate a ``(structure_note, context_note)`` pair describing the signal.

    Parameters
    ----------
    symbol:
        Trading pair symbol (e.g. ``"BTC"``).
    side:
        ``"LONG"`` or ``"SHORT"``.
    confidence:
        ``"High"``, ``"Medium"``, or ``"Low"``.
    gates_fired:
        List of gate keys that passed (e.g. ``["macro_bias", "zone", "sweep",
        "mss", "fvg"]``).  Keys must match those in ``_GATE_LABELS``.
    regime:
        Current market regime string (``"BULL"``, ``"BEAR"``, ``"SIDEWAYS"``).
        When ``None`` the regime context is omitted.
    confluence_score:
        Numeric weighted confluence score (0–100).
    structure_detail:
        Optional specific structural observation to embed in the note
        (e.g. ``"4H bullish OB at 42,500"``).

    Returns
    -------
    Tuple of ``(structure_note, context_note)`` ready for use in
    :class:`~bot.signal_engine.SignalResult`.
    """
    direction = "Bullish" if side == "LONG" else "Bearish"
    gate_names = [_GATE_LABELS.get(g, g) for g in gates_fired if g in _GATE_LABELS]

    # Build structure note
    if structure_detail:
        structure_note = f"{direction} setup — {structure_detail}."
    elif gate_names:
        top_gates = ", ".join(gate_names[:3])
        structure_note = f"{direction} confluence via {top_gates}."
    else:
        structure_note = f"{direction} multi-gate confluence confirmed."

    if len(gates_fired) > 3:
        structure_note += f" All {len(gates_fired)} gates aligned."

    # Build context note
    parts: list[str] = [f"#{symbol}/USDT {side} — {confidence} confidence"]
    if confluence_score > 0:
        parts.append(f"score {confluence_score}/100")
    if regime:
        regime_label = {
            "BULL": "bullish macro regime",
            "BEAR": "bearish macro regime",
            "SIDEWAYS": "ranging/sideways market",
        }.get(regime.upper(), f"{regime} regime")
        parts.append(f"{regime_label}")

    context_note = " | ".join(parts) + "."
    return structure_note, context_note
