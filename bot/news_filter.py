"""
News Filter
===========
Determines whether a high-impact economic event falls within the
60-minute look-ahead window defined in the master blueprint.

In production the ``NewsCalendar`` class should be wired to a live
economic-calendar API (e.g. ForexFactory, Investing.com, or CoinMarketCal).
The interface is designed so that the rest of the system remains unchanged
regardless of the data-source backing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from config import NEWS_SKIP_WINDOW_MINUTES


@dataclass
class NewsEvent:
    """Represents a single scheduled high-impact economic event."""

    title: str
    timestamp: float   # Unix UTC timestamp of the event
    impact: str        # "HIGH" | "MEDIUM" | "LOW"
    currency: str      # e.g. "USD", "BTC"

    @classmethod
    def from_dict(cls, data: dict) -> "NewsEvent":
        return cls(
            title=data["title"],
            timestamp=float(data["timestamp"]),
            impact=data.get("impact", "HIGH").upper(),
            currency=data.get("currency", "USD").upper(),
        )


class NewsCalendar:
    """
    In-memory news calendar with configurable high-impact event detection.

    Usage example
    -------------
    >>> calendar = NewsCalendar()
    >>> calendar.load_events([
    ...     NewsEvent("FOMC Rate Decision", time.time() + 1800, "HIGH", "USD"),
    ... ])
    >>> calendar.is_high_impact_imminent()
    True
    """

    def __init__(self, skip_window_minutes: int = NEWS_SKIP_WINDOW_MINUTES, fail_safe_window_minutes: int = 60) -> None:
        self._events: list[NewsEvent] = []
        self._skip_window_seconds = skip_window_minutes * 60
        self.fail_safe_window_minutes = fail_safe_window_minutes
        self.last_successful_refresh: float = 0.0

    # ── data loading ─────────────────────────────────────────────────────────

    def load_events(self, events: Sequence[NewsEvent]) -> None:
        """Replace the internal event list with *events*."""
        self._events = list(events)
        self.last_successful_refresh = time.time()

    def add_event(self, event: NewsEvent) -> None:
        """Append a single event to the calendar."""
        self._events.append(event)

    def clear(self) -> None:
        """Remove all events."""
        self._events = []

    def is_stale(self) -> bool:
        """
        Returns True if the calendar data is stale (last successful refresh was > 2 hours ago).
        Returns False if the calendar has never been loaded (last_successful_refresh == 0.0).
        """
        if self.last_successful_refresh == 0.0:
            return False
        return time.time() - self.last_successful_refresh > 2 * 3600

    def mark_fetch_failed(self) -> None:
        """Mark that a fetch attempt failed by setting a very old timestamp."""
        self.last_successful_refresh = 1.0

    # ── query ─────────────────────────────────────────────────────────────────

    def is_high_impact_imminent(self, now: float | None = None) -> bool:
        """
        Return True if any HIGH-impact event is scheduled within the
        look-ahead window defined by *skip_window_minutes*, or if
        the calendar data is stale.

        Parameters
        ----------
        now:
            Override the current time (Unix timestamp). Defaults to
            ``time.time()``.
        """
        if self.is_stale():
            return True
        now = now if now is not None else time.time()
        cutoff = now + self._skip_window_seconds
        return any(
            e.impact == "HIGH" and now <= e.timestamp <= cutoff
            for e in self._events
        )

    def upcoming_high_impact(self, now: float | None = None) -> list[NewsEvent]:
        """
        Return all HIGH-impact events within the look-ahead window,
        sorted by timestamp ascending.
        """
        now = now if now is not None else time.time()
        cutoff = now + self._skip_window_seconds
        return sorted(
            (e for e in self._events if e.impact == "HIGH" and now <= e.timestamp <= cutoff),
            key=lambda e: e.timestamp,
        )

    def format_caution_message(self, now: float | None = None) -> str:
        """
        Return a human-readable caution message listing imminent events,
        ready for Telegram broadcast.
        """
        events = self.upcoming_high_impact(now)
        if not events:
            return "✅ No high-impact news in the next 60 minutes. Trade freely."

        lines = ["⚠️ HIGH-IMPACT NEWS ALERT — New signals are FROZEN.\n"]
        for e in events:
            import datetime
            dt = datetime.datetime.fromtimestamp(e.timestamp, tz=datetime.timezone.utc).strftime("%H:%M UTC")
            lines.append(f"  • {e.title} ({e.currency}) @ {dt}")
        lines.append("\nConsider closing partial positions to reduce exposure.")
        return "\n".join(lines)
