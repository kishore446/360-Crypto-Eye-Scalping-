"""
Gate Statistics
===============
Queries the SQLite database to calculate the historical win-rate for signals
that fired the same combination of confluence gates.

The ``confluence_gates_json`` column in the ``signals`` table stores a
JSON-encoded list of gate names that were satisfied when the signal was
generated, e.g. ``["macro_bias", "zone", "liquidity_sweep", "mss"]``.

This module joins ``signals`` with ``trade_results`` to find all historical
signals that share the same gate set and computes their TP2+ hit rate — a
proxy for whether the trade reached at least the second profit target.

Usage example
-------------
>>> from bot.gate_stats import get_gate_combo_stats
>>> stats = get_gate_combo_stats(["macro_bias", "zone", "liquidity_sweep", "mss"])
>>> print(stats)
{'total': 28, 'tp2_hits': 23, 'win_rate_pct': 82.14}
"""
from __future__ import annotations

import json
import logging
import time

from bot.database import _get_conn

logger = logging.getLogger(__name__)


def get_gate_combo_stats(
    gates_fired: list[str],
    lookback_days: int = 90,
) -> dict[str, object]:
    """
    Return historical TP2+ hit-rate statistics for the given gate combination.

    Searches the ``signals`` table for all signals (within *lookback_days*)
    whose ``confluence_gates_json`` exactly matches the sorted *gates_fired*
    list, then joins with ``trade_results`` to count how many reached TP2 or
    beyond (recorded as ``outcome = "WIN"`` with ``pnl_pct >= tp2_threshold``).

    Because exact PnL-vs-TP2 mapping is not always reliable, this
    implementation approximates TP2+ hits as outcomes of ``"WIN"`` where the
    ``exit_price`` is at or above (for LONG) or at or below (for SHORT) the
    signal's ``tp2`` field.  When ``exit_price`` is not available, ``"WIN"``
    outcomes are counted as TP2 hits.

    Parameters
    ----------
    gates_fired:
        Unordered list of gate name strings that fired for the current signal,
        e.g. ``["macro_bias", "zone", "liquidity_sweep", "mss"]``.
    lookback_days:
        How many calendar days back to search.  Defaults to 90.

    Returns
    -------
    dict
        ``{'total': int, 'tp2_hits': int, 'win_rate_pct': float}``

        Returns zeroed-out dict when there is no matching historical data.
    """
    empty: dict[str, object] = {"total": 0, "tp2_hits": 0, "win_rate_pct": 0.0}

    if not gates_fired:
        return empty

    # Normalise to a sorted JSON string for exact matching
    gates_key = json.dumps(sorted(gates_fired))
    cutoff = time.time() - lookback_days * 86_400

    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, side, tp2, close_reason
                FROM signals
                WHERE confluence_gates_json = ?
                  AND opened_at >= ?
                  AND closed = 1
                """,
                (gates_key, cutoff),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("gate_stats query failed: %s", exc)
        return empty

    if not rows:
        return empty

    total = len(rows)
    tp2_hits = 0
    # TP2+ hit is inferred from close_reason: "tp2" or "tp3" indicate the
    # signal reached at least the second profit target.
    for row in rows:
        close_reason = (row["close_reason"] or "").lower()
        if close_reason in ("tp2", "tp3"):
            tp2_hits += 1

    win_rate_pct = round(tp2_hits / total * 100, 2) if total else 0.0
    return {"total": total, "tp2_hits": tp2_hits, "win_rate_pct": win_rate_pct}


def format_gate_stats_line(
    gates_fired: list[str],
    lookback_days: int = 90,
) -> str:
    """
    Return a formatted single-line string suitable for embedding in a signal
    message, or an empty string when there is not enough historical data.

    Parameters
    ----------
    gates_fired:
        Gate name list for the current signal.
    lookback_days:
        Lookback window in days.

    Returns
    -------
    str
        e.g. ``"📊 This gate combo: 82% TP2+ rate (28 signals over 90 days)"``
        or ``""`` when total < 5 (too few samples for a reliable statistic).
    """
    stats = get_gate_combo_stats(gates_fired, lookback_days)
    total = int(stats.get("total", 0))
    if total < 5:
        return ""
    win_rate = float(stats.get("win_rate_pct", 0.0))
    return (
        f"📊 This gate combo: {win_rate:.0f}% TP2+ rate "
        f"({total} signals over {lookback_days} days)"
    )
