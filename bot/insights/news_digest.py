"""
CH5B — Daily News Digest (posts at 08:00 UTC).

Reads upcoming 24-hour events from the NewsCalendar (already populated
by news_fetcher.py) and formats a daily market brief for CH5.
"""
from __future__ import annotations

from datetime import datetime, timezone


def format_news_digest(
    news_calendar: object,
    now: datetime | None = None,
) -> str:
    """
    Build the CH5B daily news digest message.

    Parameters
    ----------
    news_calendar:
        A :class:`bot.news_filter.NewsCalendar` instance. Must expose an
        ``events`` attribute that is a list of dicts with keys:
        ``title``, ``impact``, ``date_event`` (ISO-8601 string).
    now:
        Reference datetime (UTC). Defaults to current UTC time.

    Returns
    -------
    Formatted Telegram message string.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    date_str = now.strftime("%d %b %Y")
    events = getattr(news_calendar, "events", [])

    # Collect events within the next 24 hours
    high_impact = []
    medium_impact = []

    for event in events:
        try:
            raw_date = event.get("date_event") or event.get("date") or ""
            if not raw_date:
                continue
            event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            hours_away = (event_dt - now).total_seconds() / 3600
            if 0 <= hours_away <= 24:
                impact = str(event.get("impact", "")).upper()
                time_str = event_dt.strftime("%H:%M UTC")
                title = event.get("title", event.get("name", "Unknown Event"))
                entry = f"• {time_str} — {title}"
                if impact in ("HIGH", "5", "4"):
                    high_impact.append(entry)
                else:
                    medium_impact.append(entry)
        except Exception:
            continue

    high_section = "\n".join(high_impact) if high_impact else "  None scheduled"
    med_section = "\n".join(medium_impact) if medium_impact else "  None scheduled"

    sentiment = "Caution" if high_impact else "Neutral"

    return (
        f"📰 DAILY MARKET BRIEF — {date_str}\n\n"
        f"⚠️ HIGH IMPACT EVENTS TODAY:\n{high_section}\n\n"
        f"🟡 MEDIUM EVENTS:\n{med_section}\n\n"
        f"📊 Market Sentiment: {sentiment}"
    )
