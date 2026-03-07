"""
Session Filter
==============
Restricts signal generation to London and New York trading sessions.
When SESSION_FILTER_ENABLED is False, all hours are treated as active
to support 24/7 crypto scanning.
"""
from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "get_current_session",
    "is_active_session",
    "get_session_confidence_modifier",
]

try:
    from config import SESSION_FILTER_ENABLED
except ImportError:
    SESSION_FILTER_ENABLED = False

# Session hours in UTC
_LONDON_START = 7   # 07:00 UTC
_LONDON_END = 16    # 16:00 UTC
_NYC_START = 12     # 12:00 UTC
_NYC_END = 21       # 21:00 UTC


def get_current_session(now: datetime.datetime | None = None) -> str:
    """
    Return the current trading session name.
    Options: "LONDON", "NEW_YORK", "LONDON+NYC_OVERLAP", "ASIA", "OFF_HOURS"
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    hour = now.hour
    in_london = _LONDON_START <= hour < _LONDON_END
    in_nyc = _NYC_START <= hour < _NYC_END
    if in_london and in_nyc:
        return "LONDON+NYC_OVERLAP"
    if in_london:
        return "LONDON"
    if in_nyc:
        return "NEW_YORK"
    if 0 <= hour < 7:
        return "ASIA"
    return "OFF_HOURS"


def is_active_session(now: datetime.datetime | None = None) -> bool:
    """
    Returns True during London (07:00-16:00 UTC) and New York (12:00-21:00 UTC) sessions,
    or always True when SESSION_FILTER_ENABLED is False (for 24/7 crypto scanning).
    """
    if not SESSION_FILTER_ENABLED:
        return True
    session = get_current_session(now)
    return session in ("LONDON", "NEW_YORK", "LONDON+NYC_OVERLAP")


def get_session_confidence_modifier(now: datetime.datetime | None = None) -> float:
    """
    Return a confidence multiplier based on the current trading session.

    Modifiers
    ---------
    - London + NY Overlap (12:00–16:00 UTC): 1.0  — peak liquidity
    - London (07:00–16:00 UTC):              0.9
    - New York (12:00–21:00 UTC):            0.9
    - Asian (00:00–07:00 UTC):               0.7  — lower liquidity
    - Off-hours (21:00–24:00 UTC):           0.7

    When SESSION_FILTER_ENABLED is False the modifier is always 1.0 so that
    the 24/7 crypto scanning mode is unaffected.
    """
    if not SESSION_FILTER_ENABLED:
        return 1.0
    session = get_current_session(now)
    modifiers = {
        "LONDON+NYC_OVERLAP": 1.0,
        "LONDON": 0.9,
        "NEW_YORK": 0.9,
        "ASIA": 0.7,
        "OFF_HOURS": 0.7,
    }
    return modifiers.get(session, 1.0)
