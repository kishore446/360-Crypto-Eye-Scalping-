"""
Regime Adapter
==============
Provides regime-adaptive signal parameters based on the detected market regime
(BULL / BEAR / SIDEWAYS).  The ``market_regime`` state is tracked by
``bot/insights/regime_detector.py``; this module maps that regime to concrete
signal-generation adjustments.
"""
from __future__ import annotations

__all__ = ["get_regime_adjustments", "get_regime_params"]


def get_regime_adjustments(regime: str) -> dict:
    """
    Return a dictionary of signal parameter adjustments for the given *regime*.

    Parameters
    ----------
    regime:
        One of ``"BULL"``, ``"BEAR"``, ``"SIDEWAYS"``, or ``"UNKNOWN"``
        (case-insensitive).  Any other unrecognised value is treated as
        ``"SIDEWAYS"``.

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
    >>> get_regime_adjustments("UNKNOWN")
    {'tp3_rr': 4.0, 'max_signals': 4, 'risk_modifier': 0.85}
    """
    regime_upper = regime.upper() if isinstance(regime, str) else "SIDEWAYS"
    if regime_upper == "BULL":
        return {"tp3_rr": 5.0, "max_signals": 5, "risk_modifier": 1.0}
    if regime_upper == "BEAR":
        return {"tp3_rr": 3.0, "max_signals": 3, "risk_modifier": 0.75}
    if regime_upper == "UNKNOWN":
        # Regime could not be determined (e.g. insufficient data for 200-day SMA).
        # Use neutral/moderate settings to avoid silently throttling signal generation.
        return {"tp3_rr": 4.0, "max_signals": 4, "risk_modifier": 0.85}
    # SIDEWAYS or any other unrecognised value
    return {"tp3_rr": 2.5, "max_signals": 2, "risk_modifier": 0.5}


def get_regime_params(regime: str) -> dict:
    """Return adaptive parameters for the 3-channel system based on *regime*.

    Parameters
    ----------
    regime:
        Market regime string — ``"TRENDING"``, ``"RANGING"``, ``"BEAR"``,
        ``"HIGH_VOL"``, ``"BULL"``, ``"SIDEWAYS"``, or ``"UNKNOWN"``
        (case-insensitive).

    Returns
    -------
    dict with keys:

    - ``min_confluence_ch1`` (int): Minimum score for CH1 Hard Scalp.
    - ``min_confluence_ch2`` (int): Minimum score for CH2 Medium Scalp.
    - ``min_confluence_ch3`` (int): Minimum score for CH3 Easy Breakout.
    - ``max_active_signals`` (int): Maximum concurrent active signals.
    - ``tp1_multiplier`` (float): Multiplier applied to CH TP1.
    - ``tp2_multiplier`` (float): Multiplier applied to CH TP2.
    - ``tp3_multiplier`` (float): Multiplier applied to CH TP3.

    Examples
    --------
    >>> get_regime_params("TRENDING")["min_confluence_ch1"]
    65
    >>> get_regime_params("RANGING")["max_active_signals"]
    2
    """
    regime_upper = regime.upper() if isinstance(regime, str) else "UNKNOWN"
    if regime_upper == "TRENDING":
        return {
            "min_confluence_ch1": 65,
            "min_confluence_ch2": 45,
            "min_confluence_ch3": 30,
            "max_active_signals": 4,
            "tp1_multiplier": 1.0,
            "tp2_multiplier": 1.15,
            "tp3_multiplier": 1.25,
        }
    if regime_upper == "RANGING":
        return {
            "min_confluence_ch1": 75,
            "min_confluence_ch2": 55,
            "min_confluence_ch3": 40,
            "max_active_signals": 2,
            "tp1_multiplier": 0.85,
            "tp2_multiplier": 0.80,
            "tp3_multiplier": 0.75,
        }
    if regime_upper in ("BEAR", "HIGH_VOL"):
        return {
            "min_confluence_ch1": 80,
            "min_confluence_ch2": 60,
            "min_confluence_ch3": 45,
            "max_active_signals": 2,
            "tp1_multiplier": 1.1,
            "tp2_multiplier": 1.2,
            "tp3_multiplier": 1.4,
        }
    # BULL, UNKNOWN, SIDEWAYS, or any other value — neutral/moderate
    return {
        "min_confluence_ch1": 70,
        "min_confluence_ch2": 50,
        "min_confluence_ch3": 35,
        "max_active_signals": 3,
        "tp1_multiplier": 1.0,
        "tp2_multiplier": 1.0,
        "tp3_multiplier": 1.0,
    }
