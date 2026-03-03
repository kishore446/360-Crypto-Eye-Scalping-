"""
News Fetcher — CoinMarketCal Integration
=========================================
Fetches high-impact crypto events from the CoinMarketCal public API
and populates the shared NewsCalendar instance.

API Docs: https://coinmarketcal.com/en/api
Free tier: 500 requests/day — more than enough for 30-min polling.

Required environment variable:
    COINMARKETCAL_API_KEY — API key from https://coinmarketcal.com/en/api
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

import requests

from bot.news_filter import NewsCalendar, NewsEvent
from config import COINMARKETCAL_API_KEY

logger = logging.getLogger(__name__)

# CoinMarketCal v1 base URL
_BASE_URL = "https://developers.coinmarketcal.com/v1/events"

# Only fetch events with these importance ratings (CoinMarketCal scale: 0–100)
_MIN_IMPORTANCE = 70  # 70+ = major event

# How many days ahead to fetch events for
_DAYS_AHEAD = 1


def fetch_coinmarketcal_events() -> list[NewsEvent]:
    """
    Fetch upcoming HIGH-impact crypto events from CoinMarketCal API.

    Returns a list of :class:`NewsEvent` objects with impact="HIGH".
    Returns an empty list on any error (so the bot continues operating).
    """
    if not COINMARKETCAL_API_KEY:
        logger.warning(
            "COINMARKETCAL_API_KEY is not set — news filter will be inactive. "
            "Get a free key at https://coinmarketcal.com/en/api"
        )
        return []

    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=_DAYS_AHEAD)

    params = {
        "dateRangeStart": today.strftime("%d/%m/%Y"),
        "dateRangeEnd": tomorrow.strftime("%d/%m/%Y"),
        "showOnly": "significant_events",
        "sortBy": "importance",
        "page": 1,
        "max": 50,
    }

    headers = {
        "x-api-key": COINMARKETCAL_API_KEY,
        "Accept-Encoding": "deflate, gzip",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(_BASE_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("CoinMarketCal API request failed: %s", exc)
        return []
    except ValueError as exc:
        logger.error("CoinMarketCal API returned invalid JSON: %s", exc)
        return []

    events: list[NewsEvent] = []
    raw_events = data.get("body", [])

    for item in raw_events:
        try:
            # Parse the event date — CoinMarketCal returns ISO 8601
            date_str = item.get("date_event", "")
            if not date_str:
                continue

            # Convert to Unix timestamp (UTC)
            dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            ts = dt.timestamp()

            # Skip past events
            if ts < time.time():
                continue

            # Determine impact from importance score (0–100)
            importance = float(item.get("percentage", 0))
            if importance >= _MIN_IMPORTANCE:
                impact = "HIGH"
            elif importance >= 40:
                impact = "MEDIUM"
            else:
                impact = "LOW"

            # Extract coin/currency
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
                    timestamp=ts,
                    impact=impact,
                    currency=currency,
                )
            )

        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Skipping malformed CoinMarketCal event: %s", exc)
            continue

    logger.info(
        "CoinMarketCal: loaded %d events (%d HIGH-impact) for %s→%s",
        len(events),
        sum(1 for e in events if e.impact == "HIGH"),
        today,
        tomorrow,
    )
    return events


def refresh_news_calendar(calendar: NewsCalendar) -> None:
    """
    Fetch fresh events from CoinMarketCal and load them into *calendar*.
    Safe to call from a background thread — replaces the event list atomically.
    """
    events = fetch_coinmarketcal_events()
    calendar.load_events(events)
    logger.info("NewsCalendar refreshed: %d events loaded.", len(events))
