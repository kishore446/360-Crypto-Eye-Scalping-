"""
Regime Adapter
==============
Provides regime-adaptive signal parameters based on the detected market regime
(BULL / BEAR / SIDEWAYS).  The ``market_regime`` state is tracked by
``bot/insights/regime_detector.py``; this module maps that regime to concrete
signal-generation adjustments.
"""
from __future__ import annotations

__all__ = ["get_regime_adjustments"]


def get_regime_adjustments(regime: str) -> dict:
    """
    Return a dictionary of signal parameter adjustments for the given *regime*.

    Parameters
    ----------
    regime:
        One of ``"BULL"``, ``"BEAR"``, or ``"SIDEWAYS"`` (case-insensitive).
        Any unrecognised value is treated as ``"SIDEWAYS"``.

    Returns
    -------
    dict with keys:

    - ``tp3_rr`` (float): TP3 Risk:Reward ratio.
    - ``max_signals`` (int): Maximum concurrent same-side signals.
    - ``risk_modifier`` (float): Multiplier applied to position risk (1.0 = no change).

    Examples
    --------
    >>> get_regime_adjustments("BULL")
    {'tp3_rr': 5.0, 'max_signals': 5, 'risk_modifier': 1.0}
    >>> get_regime_adjustments("BEAR")
    {'tp3_rr': 3.0, 'max_signals': 3, 'risk_modifier': 0.75}
    >>> get_regime_adjustments("SIDEWAYS")
    {'tp3_rr': 2.5, 'max_signals': 2, 'risk_modifier': 0.5}
    """
    regime_upper = regime.upper() if isinstance(regime, str) else "SIDEWAYS"
    if regime_upper == "BULL":
        return {"tp3_rr": 5.0, "max_signals": 5, "risk_modifier": 1.0}
    if regime_upper == "BEAR":
        return {"tp3_rr": 3.0, "max_signals": 3, "risk_modifier": 0.75}
    # SIDEWAYS or unknown
    return {"tp3_rr": 2.5, "max_signals": 2, "risk_modifier": 0.5}
