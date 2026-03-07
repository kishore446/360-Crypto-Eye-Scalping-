"""
News Fetcher
============
Fetches high-impact crypto events from the CoinMarketCal public REST API
and loads them into a NewsCalendar instance.

API docs: https://developers.coinmarketcal.com/
Free tier: 500 requests/day — polling every 30 min = ~48 req/day.

Required environment variable:
    COINMARKETCAL_API_KEY — API key from https://coinmarketcal.com/en/api
"""

from __future__ import annotations

import datetime
import logging

import requests

from bot.news_filter import NewsCalendar, NewsEvent
from config import COINMARKETCAL_API_KEY

logger = logging.getLogger(__name__)

# CoinMarketCal v1 API base URL
_BASE_URL = "https://developers.coinmarketcal.com/v1/events"

# Request timeout in seconds
_TIMEOUT = 10

# Only load events within the next N hours to keep the list small
_LOOKAHEAD_HOURS = 24


def fetch_coinmarketcal_events() -> list[NewsEvent]:
    """
    Fetch upcoming high-impact crypto events from CoinMarketCal.

    Returns an empty list (never raises) so a network failure never
    crashes the bot — the news filter will simply allow all signals
    until the next successful refresh.
    """
    if not COINMARKETCAL_API_KEY:
        logger.warning(
            "COINMARKETCAL_API_KEY is not set — news filter will be inactive."
        )
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    date_from = now.strftime("%d/%m/%Y")
    date_to = (now + datetime.timedelta(hours=_LOOKAHEAD_HOURS)).strftime("%d/%m/%Y")

    headers = {
        "x-api-key": COINMARKETCAL_API_KEY,
        "Accept-Encoding": "deflate, gzip",
        "Accept": "application/json",
    }

    params = {
        "dateRangeStart": date_from,
        "dateRangeEnd": date_to,
        "significanceScoreMin": "75",   # only high-significance events (0-100 scale)
        "page": 1,
        "max": 150,                     # max events per request
        "showOnly": "hot_events",       # trending / high-impact only
    }

    try:
        resp = requests.get(_BASE_URL, headers=headers, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("CoinMarketCal API request failed: %s", exc)
        return []
    except ValueError as exc:
        logger.error("CoinMarketCal API returned invalid JSON: %s", exc)
        return []

    body = data.get("body", [])
    if not isinstance(body, list):
        logger.warning("CoinMarketCal API response body is not a list: %s", type(body))
        return []

    events: list[NewsEvent] = []
    for item in body:
        try:
            # Parse the event datetime — CoinMarketCal uses ISO 8601 UTC
            date_str = item.get("date_event", "")
            if not date_str:
                continue

            # Handle both "YYYY-MM-DDTHH:MM:SS+00:00" and "YYYY-MM-DD" formats
            try:
                dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").replace(
                    tzinfo=datetime.timezone.utc
                )

            timestamp = dt.timestamp()

            # Determine the primary currency/coin for this event
            coins = item.get("coins", [])
            currency = coins[0].get("symbol", "CRYPTO").upper() if coins else "CRYPTO"

            title = item.get("title", {})
            if isinstance(title, dict):
                title_str = title.get("en", str(title))
            else:
                title_str = str(title)

            events.append(
                NewsEvent(
                    title=title_str,
                    timestamp=timestamp,
                    impact="HIGH",       # we only fetch high-significance events
                    currency=currency,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping malformed CoinMarketCal event: %s — %s", item, exc)
            continue

    logger.info("CoinMarketCal: loaded %d high-impact events.", len(events))
    return events


def fetch_and_reload(calendar: NewsCalendar) -> None:
    """
    Fetch fresh events from CoinMarketCal and atomically reload *calendar*.

    This is the function called by the APScheduler background job.
    It never raises — any error is logged and the calendar is left unchanged.
    """
    if not COINMARKETCAL_API_KEY:
        logger.info(
            "COINMARKETCAL_API_KEY is not set — news filtering disabled, signals allowed."
        )
        return  # Do NOT call mark_fetch_failed() — that would freeze signals
    try:
        events = fetch_coinmarketcal_events()
        if events is not None:
            calendar.load_events(events)
            logger.info(
                "NewsCalendar refreshed: %d HIGH-impact event(s) loaded.", len(events)
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error refreshing NewsCalendar: %s", exc)
