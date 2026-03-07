"""
Portfolio Correlation Guard
============================
Warns when too many active signals are on correlated assets, helping
subscribers avoid over-concentration risk.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.risk_manager import ActiveSignal

__all__ = ["check_correlation_risk", "CORRELATION_GROUPS"]

CORRELATION_GROUPS: dict[str, list[str]] = {
    "BTC_MAJORS": ["BTC", "ETH", "SOL"],
    "L1_ALTS": ["ADA", "AVAX", "DOT", "ATOM", "NEAR", "SUI"],
    "MEME": ["DOGE", "SHIB", "PEPE", "WIF", "FLOKI", "BONK"],
    "DEFI": ["LINK", "UNI", "AAVE", "MKR", "SNX"],
    "L2": ["MATIC", "ARB", "OP", "STRK", "ZK"],
}


def _get_correlation_group(symbol: str) -> Optional[str]:
    """Return the correlation group name for *symbol*, or None if not mapped."""
    base = symbol.upper().replace("/USDT", "").replace("USDT", "")
    for group, members in CORRELATION_GROUPS.items():
        if base in members:
            return group
    return None


def check_correlation_risk(
    active_signals: "list[ActiveSignal]",
    max_same_group: int = 3,
) -> Optional[str]:
    """
    Check whether too many active signals are concentrated in a single
    correlation group on the same side.

    Parameters
    ----------
    active_signals:
        List of currently active (non-closed) signals.
    max_same_group:
        Maximum allowed signals per group/side before a warning is issued.

    Returns
    -------
    Optional[str]
        A warning message string if the threshold is breached, else None.
    """
    # Build {(group, side): [symbol, ...]} mapping
    group_side_map: dict[tuple[str, str], list[str]] = {}
    for sig in active_signals:
        if sig.closed:
            continue
        group = _get_correlation_group(sig.result.symbol)
        if group is None:
            continue
        side = sig.result.side.value
        key = (group, side)
        group_side_map.setdefault(key, []).append(sig.result.symbol)

    for (group, side), symbols in group_side_map.items():
        if len(symbols) >= max_same_group:
            pairs_str = ", ".join(sorted(set(symbols)))
            return (
                f"⚠️ CORRELATION RISK: {len(symbols)} {side} signals in "
                f"{group} group ({pairs_str}). Consider reducing exposure."
            )

    return None
