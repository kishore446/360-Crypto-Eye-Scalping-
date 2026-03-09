"""
Signal Post-Mortem
==================
Generates retrospective analysis messages after each signal closes.

These are posted to CH5 Insights after every auto-close event to provide
subscribers with educational context about what worked or did not work.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from bot.gate_labels import gate_symbols_str

if TYPE_CHECKING:
    from bot.dashboard import TradeResult

__all__ = ["generate_postmortem"]

_OUTCOME_LABELS = {
    "WIN": "WIN ✅",
    "LOSS": "LOSS ❌",
    "BE": "BREAK-EVEN ➖",
}


def _gates_fired_str(gates_fired: list[str]) -> str:
    """Format a list of gate keys to '①②③④' style string."""
    return gate_symbols_str(gates_fired)


def _what_worked(trade_result: "TradeResult", gates_fired: list[str], regime: str) -> str:
    """Produce a brief 'What Worked' note based on available data."""
    fired_set = set(gates_fired)
    notes: list[str] = []
    if "mss" in fired_set and "zone" in fired_set:
        notes.append("Perfect OB + MSS alignment")
    if "sweep" in fired_set:
        notes.append("Clean liquidity sweep")
    if regime in ("BULL", "BEAR"):
        notes.append(f"Aligned with {regime} macro regime")
    if not notes:
        notes.append("Standard confluence setup")
    return " | ".join(notes)


def generate_postmortem(
    trade_result: "TradeResult",
    gates_fired: list[str],
    regime: str,
    session: str,
) -> str:
    """
    Generate a post-mortem analysis message for a closed signal.

    Parameters
    ----------
    trade_result:
        The completed ``TradeResult`` from the dashboard.
    gates_fired:
        List of gate names that passed (e.g. ``["discount_zone", "liquidity_sweep"]``).
    regime:
        Market regime string, e.g. ``"BULL"``, ``"BEAR"``, ``"RANGING"``.
    session:
        Session name, e.g. ``"LONDON"``, ``"NYC"``, ``"OVERLAP"``.

    Returns
    -------
    str
        Telegram-formatted post-mortem message.
    """
    outcome_label = _OUTCOME_LABELS.get(trade_result.outcome, trade_result.outcome)
    gates_str = _gates_fired_str(gates_fired)
    total_gates = 7
    fired_count = len(gates_fired)

    pnl_sign = "+" if trade_result.pnl_pct >= 0 else ""
    pnl_str = f"{pnl_sign}{trade_result.pnl_pct:.2f}%"

    # Duration
    duration_secs = 0.0
    if trade_result.closed_at is not None and trade_result.opened_at is not None:
        duration_secs = trade_result.closed_at - trade_result.opened_at
    h = int(duration_secs // 3600)
    m = int((duration_secs % 3600) // 60)
    duration_str = f"{h}h {m}m" if h > 0 else f"{m}m"

    # Confluence score → percentage label
    confluence_score = getattr(trade_result, "confluence_score", None)
    if confluence_score is None:
        # Estimate from gates fired
        confluence_score = math.floor(fired_count / total_gates * 100)

    channel_label = trade_result.channel_tier.replace("_", " ")
    what_worked = _what_worked(trade_result, gates_fired, regime)

    return (
        f"📋 *SIGNAL POST-MORTEM — #{trade_result.symbol}/USDT {trade_result.side}*\n"
        f"Outcome: {outcome_label} | {pnl_str}\n"
        f"Gates Fired: {gates_str} ({fired_count}/{total_gates})\n"
        f"Confluence Score: {confluence_score}/100\n"
        f"Market Regime: {regime}\n"
        f"Session: {session}\n"
        f"Duration: {duration_str}\n"
        f"What Worked: {what_worked}\n"
        f"Channel: {channel_label}"
    )
