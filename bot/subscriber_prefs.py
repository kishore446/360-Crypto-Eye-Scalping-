"""
Subscriber Preferences
======================
Manages per-subscriber notification mode preferences stored in the SQLite
database.  Each subscriber can choose one of three alert modes:

  • ``"all"``       — receive every signal as it fires (default).
  • ``"high_only"`` — receive only HIGH-confidence signals.
  • ``"digest"``    — receive one daily summary at 09:00 UTC instead of
                      individual alerts.

This module also provides a digest formatter that aggregates the day's signals
into a single readable Telegram message.

Database table
--------------
The ``subscriber_preferences`` table is created by :func:`bot.database.init_db`
via the following DDL (safe to run on an existing database)::

    CREATE TABLE IF NOT EXISTS subscriber_preferences (
        user_id    INTEGER PRIMARY KEY,
        mode       TEXT    NOT NULL DEFAULT 'all',
        updated_at REAL    NOT NULL
    );
"""
from __future__ import annotations

import time
from typing import Optional

from bot.database import _get_conn

VALID_MODES: frozenset[str] = frozenset({"all", "high_only", "digest"})


# ── CRUD helpers ──────────────────────────────────────────────────────────────


def set_preference(user_id: int, mode: str) -> None:
    """
    Upsert the notification mode for *user_id*.

    Parameters
    ----------
    user_id:
        Telegram user identifier.
    mode:
        One of ``"all"``, ``"high_only"``, or ``"digest"``.

    Raises
    ------
    ValueError
        When *mode* is not one of the recognised values.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode '{mode}'. Choose from: {', '.join(sorted(VALID_MODES))}."
        )
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO subscriber_preferences (user_id, mode, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                mode       = excluded.mode,
                updated_at = excluded.updated_at
            """,
            (user_id, mode, time.time()),
        )


def get_preference(user_id: int) -> str:
    """
    Return the stored notification mode for *user_id*.

    Falls back to ``"all"`` when the user has not set a preference.

    Parameters
    ----------
    user_id:
        Telegram user identifier.

    Returns
    -------
    str
        One of ``"all"``, ``"high_only"``, or ``"digest"``.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT mode FROM subscriber_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row["mode"] if row else "all"


def get_users_for_mode(mode: str) -> list[int]:
    """
    Return a list of user IDs whose preference matches *mode*.

    Parameters
    ----------
    mode:
        One of ``"all"``, ``"high_only"``, or ``"digest"``.

    Returns
    -------
    list[int]
        Telegram user identifiers.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM subscriber_preferences WHERE mode = ?",
            (mode,),
        ).fetchall()
    return [row["user_id"] for row in rows]


# ── Digest formatter ──────────────────────────────────────────────────────────


def format_daily_digest(signals: list[dict]) -> str:
    """
    Format a daily digest summary message from a list of signal dictionaries.

    Each dictionary should have keys: ``symbol``, ``side``, ``confidence``,
    ``tp1``, ``tp2``, ``tp3``, ``stop_loss``, and optionally ``pnl_pct``
    and ``outcome``.

    Parameters
    ----------
    signals:
        List of signal summary dicts for the day.

    Returns
    -------
    str
        Telegram-ready digest message.
    """
    today = time.strftime("%d %b %Y", time.gmtime())
    if not signals:
        return (
            f"📋 *360 Eye Daily Digest — {today}*\n\n"
            "No signals were generated today."
        )

    lines = [f"📋 *360 Eye Daily Digest — {today}*", ""]
    for i, sig in enumerate(signals, start=1):
        symbol = sig.get("symbol", "?")
        side = sig.get("side", "?")
        confidence = sig.get("confidence", "?")
        tp1 = sig.get("tp1", 0.0)
        sl = sig.get("stop_loss", 0.0)
        outcome = sig.get("outcome", "OPEN")
        pnl = sig.get("pnl_pct", 0.0)

        outcome_icon = {"WIN": "✅", "LOSS": "❌", "BE": "🔒", "OPEN": "🟡"}.get(
            outcome.upper(), "🟡"
        )
        lines.append(
            f"{i}. {outcome_icon} #{symbol}/USDT {side} [{confidence}] "
            f"TP1 {tp1:.4f} | SL {sl:.4f}"
        )
        if outcome != "OPEN":
            sign = "+" if pnl >= 0 else ""
            lines.append(f"   PnL: {sign}{pnl:.2f}%")

    lines.append("")
    lines.append(f"Total signals today: {len(signals)}")
    return "\n".join(lines)


# ── Human-readable mode labels ────────────────────────────────────────────────

MODE_LABELS: dict[str, str] = {
    "all": "All Signals 🔔",
    "high_only": "HIGH Confidence Only ⭐⭐⭐",
    "digest": "Daily Digest (09:00 UTC) 📋",
}


def describe_mode(mode: str) -> str:
    """
    Return a human-readable label for *mode*.

    Parameters
    ----------
    mode:
        A valid preference mode string.

    Returns
    -------
    str
        Friendly label for display in Telegram messages.
    """
    return MODE_LABELS.get(mode, mode)
