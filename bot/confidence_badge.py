"""
Signal Confidence Badge
Visual confidence badges and estimated hold-time for signal messages.
"""
from __future__ import annotations


def get_confidence_badge(confidence: str, gates_fired: list[str]) -> str:
    """
    Return a visual confidence badge string.

    *confidence* is one of "HIGH", "MEDIUM", "LOW" (case-insensitive).
    *gates_fired* is the list of gate identifiers that passed for this signal.

    Examples:
      get_confidence_badge("HIGH", ["G1","G2","G3","G4","G5","G6","G7"])
      → "🔥 HIGH (7/7 gates)"
      get_confidence_badge("MEDIUM", ["G1","G2","G3","G4","G5"])
      → "⚡ MEDIUM (5/7 gates)"
    """
    conf_upper = confidence.upper() if confidence else "LOW"
    count = len(gates_fired)
    total = 7  # Standard 7-gate system

    if conf_upper == "HIGH":
        emoji = "🔥"
    elif conf_upper == "MEDIUM":
        emoji = "⚡"
    else:
        emoji = "💡"

    return f"{emoji} {conf_upper} ({count}/{total} gates)"


def get_expected_timeframe(atr: float, entry: float, tp1: float) -> str:
    """
    Return an estimated hold-time string based on ATR distance to TP1.

    Uses the ratio of TP1 distance to ATR to estimate move duration:
    - <= 1× ATR distance → very short (15m–1h)
    - 1–2× ATR → short-medium (1h–4h)
    - 2–4× ATR → medium (4h–24h)
    - > 4× ATR → longer (1d–3d)

    Returns a string like "⏱ Est. Hold: 15m-2h".
    """
    if atr <= 0 or entry <= 0:
        return "⏱ Est. Hold: Unknown"

    distance = abs(tp1 - entry)
    ratio = distance / atr

    if ratio <= 1.0:
        timeframe = "15m-1h"
    elif ratio <= 2.0:
        timeframe = "1h-4h"
    elif ratio <= 4.0:
        timeframe = "4h-24h"
    else:
        timeframe = "1d-3d"

    return f"⏱ Est. Hold: {timeframe}"
