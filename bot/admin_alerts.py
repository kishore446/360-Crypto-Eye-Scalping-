"""
Admin Alerting System
=====================
Sends Telegram DMs to the bot admin when critical operational conditions
are detected:

  - Exchange connection is down for > 5 minutes
  - Win rate drops below the configured threshold over the last N signals
  - Bot encounters an unhandled exception

All alerts are rate-limited to avoid flooding the admin's DMs.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["AdminAlertManager"]

try:
    from config import ADMIN_ALERT_ENABLED, ADMIN_ALERT_WIN_RATE_THRESHOLD, ADMIN_CHAT_ID
except ImportError:
    ADMIN_ALERT_ENABLED: bool = True
    ADMIN_ALERT_WIN_RATE_THRESHOLD: int = 40
    ADMIN_CHAT_ID: int = 0

# Minimum seconds between repeated alerts of the same type (1 hour)
_ALERT_COOLDOWN: float = 3600.0
_WIN_RATE_LOOKBACK: int = 20  # evaluate win rate over the last 20 signals


class AdminAlertManager:
    """
    Tracks operational conditions and sends DM alerts to the admin.

    Usage
    -----
    Wire into the bot's scheduler and call the appropriate ``check_*``
    methods from periodic jobs or exception handlers.
    """

    def __init__(self) -> None:
        self._last_alert: dict[str, float] = {}
        self._exchange_down_since: Optional[float] = None

    # ── internal helpers ──────────────────────────────────────────────────────

    def _should_send(self, alert_key: str) -> bool:
        """Return True if enough time has passed since the last alert of this type."""
        if not ADMIN_ALERT_ENABLED or ADMIN_CHAT_ID == 0:
            return False
        now = time.time()
        last = self._last_alert.get(alert_key, 0.0)
        if now - last >= _ALERT_COOLDOWN:
            self._last_alert[alert_key] = now
            return True
        return False

    async def _send(self, bot_token: str, text: str) -> None:
        """Send a DM to the admin using a fresh Telegram Bot instance."""
        if ADMIN_CHAT_ID == 0 or not bot_token:
            return
        try:
            from telegram import Bot
            async with Bot(token=bot_token) as bot:
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=text,
                    parse_mode="Markdown",
                )
        except Exception as exc:
            logger.warning("AdminAlertManager: failed to send DM to admin: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def notify_exchange_down(self) -> None:
        """Record that the exchange connection is currently unavailable."""
        if self._exchange_down_since is None:
            self._exchange_down_since = time.time()

    def notify_exchange_up(self) -> None:
        """Record that the exchange connection has recovered."""
        self._exchange_down_since = None

    async def check_exchange_health(self, bot_token: str) -> None:
        """
        Send an alert if the exchange has been unreachable for > 5 minutes.

        Call this from a periodic scheduler job (e.g. every 60 seconds).
        """
        if self._exchange_down_since is None:
            return
        down_duration = time.time() - self._exchange_down_since
        if down_duration > 300 and self._should_send("exchange_down"):
            mins = int(down_duration // 60)
            await self._send(
                bot_token,
                f"🚨 *ADMIN ALERT — Exchange Unreachable*\n"
                f"The exchange connection has been down for {mins} minutes.\n"
                f"Please check the bot logs immediately.",
            )

    async def check_win_rate(
        self,
        bot_token: str,
        recent_outcomes: list[str],
    ) -> None:
        """
        Send an alert if the win rate over the last *_WIN_RATE_LOOKBACK* signals
        drops below ``ADMIN_ALERT_WIN_RATE_THRESHOLD`` percent.

        Parameters
        ----------
        bot_token:
            Telegram bot token for sending the DM.
        recent_outcomes:
            List of recent trade outcomes in chronological order.
            Each element must be ``"WIN"``, ``"LOSS"``, or ``"BE"``.
        """
        window = recent_outcomes[-_WIN_RATE_LOOKBACK:]
        if len(window) < _WIN_RATE_LOOKBACK:
            return
        wins = sum(1 for o in window if o == "WIN")
        win_rate_pct = wins / len(window) * 100
        if win_rate_pct < ADMIN_ALERT_WIN_RATE_THRESHOLD and self._should_send("low_win_rate"):
            await self._send(
                bot_token,
                f"🚨 *ADMIN ALERT — Low Win Rate*\n"
                f"Win rate over the last {_WIN_RATE_LOOKBACK} signals: "
                f"*{win_rate_pct:.1f}%* (threshold: {ADMIN_ALERT_WIN_RATE_THRESHOLD}%)\n"
                f"Consider pausing trading and reviewing signal quality.",
            )

    async def notify_exception(self, bot_token: str, context: str, exc: Exception) -> None:
        """
        Send an alert when an unhandled exception occurs.

        Parameters
        ----------
        bot_token:
            Telegram bot token for sending the DM.
        context:
            Short description of where the exception occurred.
        exc:
            The exception that was raised.
        """
        if self._should_send(f"exception_{context}"):
            await self._send(
                bot_token,
                f"🚨 *ADMIN ALERT — Unhandled Exception*\n"
                f"Context: `{context}`\n"
                f"Error: `{type(exc).__name__}: {exc}`\n"
                f"Check the bot logs for the full traceback.",
            )
