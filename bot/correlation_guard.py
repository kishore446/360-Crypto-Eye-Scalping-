"""
Correlation Guard
=================
Detects over-concentration of same-side signals in a correlated asset group.

Groups:
  BTC_MAJORS : BTC, ETH
  L1_ALTS    : SOL, ADA, AVAX, DOT, LINK
  MEME       : DOGE, SHIB, PEPE, FLOKI, WIF, BONK
  DEFI       : UNI, AAVE, MKR, CRV, SUSHI
  L2         : MATIC, ARB, OP, STRK, MANTA

Fires a warning when ≥ max_same_group same-side signals concentrate in one group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.risk_manager import ActiveSignal

__all__ = ["check_correlation_risk", "CORRELATION_GROUPS"]

CORRELATION_GROUPS: dict[str, list[str]] = {
    "BTC_GROUP": ["BTC", "ETH", "SOL", "AVAX", "NEAR"],
    "MEME_GROUP": ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK"],
    "L2_GROUP": ["ARB", "OP", "MATIC", "MANTA", "STRK"],
    "DEFI_GROUP": ["UNI", "AAVE", "LINK", "MKR", "SNX"],
}


def check_correlation_risk(
    active_signals: list["ActiveSignal"],
    max_same_group: int = 3,
) -> Optional[str]:
    """
    Check whether same-side signals are over-concentrated in one correlation group.

    Parameters
    ----------
    active_signals:
        List of open (not closed) ActiveSignal instances.
    max_same_group:
        Threshold of same-side signals in one group before a warning is fired.
        Default is 3.

    Returns
    -------
    Warning message string if a threshold is exceeded, else None.
    """
    if not active_signals:
        return None

    for group_name, members in CORRELATION_GROUPS.items():
        members_upper = [m.upper() for m in members]
        for side in ("LONG", "SHORT"):
            matching = [
                s
                for s in active_signals
                if not s.closed
                and s.result.side.value == side
                and s.result.symbol.upper() in members_upper
            ]
            if len(matching) >= max_same_group:
                symbols = ", ".join(s.result.symbol for s in matching)
                return (
                    f"⚠️ CORRELATION ALERT — {group_name} ({side})\n"
                    f"{len(matching)} same-side signals in correlated group: {symbols}\n"
                    f"Consider reducing position size or avoiding new entries in this group."
                )

    return None
