"""
CH5B — Fear & Greed Index Dashboard
=====================================
Posts the current Crypto Fear & Greed Index to the Insights channel every
6 hours.

Data source: https://api.alternative.me/fng/
Format:
  🌡️ CRYPTO FEAR & GREED INDEX
  ─────────────────────────────
  Score: 72 — GREED 🟢
  Yesterday: 68 — GREED
  Last Week: 45 — FEAR

  📊 What this means:
  • Greed zones often precede corrections
  • Consider tighter stop-losses on LONG positions
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.alternative.me/fng/"
_TIMEOUT = 10  # seconds

# Emoji labels per zone
_LABELS: dict[str, str] = {
    "Extreme Fear": "🔴",
    "Fear": "🟠",
    "Neutral": "🟡",
    "Greed": "🟢",
    "Extreme Greed": "🟣",
}


def fetch_fear_greed_index() -> Optional[dict]:
    """
    Fetch current and historical Fear & Greed data from Alternative.me API.

    Returns a dict with keys ``current``, ``yesterday``, ``last_week``,
    each containing ``{"value": int, "label": str}``.
    Returns None on any error.
    """
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                _API_URL,
                params={"limit": 7, "format": "json"},
            )
            resp.raise_for_status()
            body = resp.json().get("data", [])
        if not body:
            return None

        def _parse(entry: dict) -> dict:
            return {
                "value": int(entry["value"]),
                "label": entry.get("value_classification", "Unknown"),
            }

        result: dict = {"current": _parse(body[0])}
        if len(body) >= 2:
            result["yesterday"] = _parse(body[1])
        if len(body) >= 7:
            result["last_week"] = _parse(body[6])
        return result

    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed to fetch Fear & Greed index: %s", exc)
        return None


def format_fear_greed_message(data: dict) -> str:
    """
    Format the Fear & Greed data into a Telegram-friendly message.

    Parameters
    ----------
    data:
        Dict as returned by :func:`fetch_fear_greed_index`.
    """
    current = data["current"]
    score = current["value"]
    label = current["label"]
    emoji = _LABELS.get(label, "⚪")

    lines = [
        "🌡️ CRYPTO FEAR & GREED INDEX",
        "─────────────────────────────",
        f"Score: {score} — {label} {emoji}",
    ]

    if "yesterday" in data:
        y = data["yesterday"]
        lines.append(f"Yesterday: {y['value']} — {y['label']}")

    if "last_week" in data:
        lw = data["last_week"]
        lines.append(f"Last Week: {lw['value']} — {lw['label']}")

    lines.append("")
    lines.append("📊 What this means:")

    if score >= 75:
        lines.append("• Extreme greed — market may be overheated, corrections likely")
        lines.append("• Consider tighter stop-losses on LONG positions")
    elif score >= 55:
        lines.append("• Greed zones often precede corrections")
        lines.append("• Consider tighter stop-losses on LONG positions")
    elif score <= 25:
        lines.append("• Extreme fear — historically a buying opportunity")
        lines.append("• Watch for LONG setups with strong confluence")
    elif score <= 45:
        lines.append("• Fear in the market — potential contrarian LONG opportunities")
    else:
        lines.append("• Neutral sentiment — trade the technical setup")

    return "\n".join(lines)
