"""
Broadcast Queue
===============
Thread-safe queue that decouples signal generation (which happens in
APScheduler threads or WebSocket callbacks) from Telegram message delivery
(which requires the async event loop).

The ``BroadcastQueue`` replaces the fragile pattern of checking for a live
event-loop reference (``_main_loop``) that was repeated throughout ``bot.py``.

Usage
-----
At startup::

    from bot.broadcast import BroadcastQueue
    bq = BroadcastQueue()
    # Register the consumer task in the async event loop
    asyncio.create_task(bq.consume(application.bot))

From any thread (scheduler jobs, scanners, etc.)::

    bq.put_nowait(channel_id=CHANNEL_ID, text="Signal fired!")

From async code::

    await bq.put(channel_id=CHANNEL_ID, text="Signal fired!")
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["BroadcastMessage", "BroadcastQueue"]

# Telegram's documented rate limit is 30 messages/second for a single bot.
# We stay well below it with a 50 ms inter-message delay.
_RATE_LIMIT_SLEEP = 0.05


@dataclass
class BroadcastMessage:
    """A single message to be delivered to a Telegram channel or chat.

    Attributes
    ----------
    channel_id:
        Telegram chat/channel ID to send the message to.
    text:
        Message text (Markdown or HTML depending on ``parse_mode``).
    parse_mode:
        Telegram parse mode — ``"Markdown"`` (default) or ``"HTML"``.
    photo_path:
        Optional filesystem path to a PNG/JPEG image.  When set, the
        message is sent as a photo with the text as its caption.
    """

    channel_id: int
    text: str
    parse_mode: str = "Markdown"
    photo_path: Optional[str] = None


class BroadcastQueue:
    """Thread-safe queue that buffers outgoing Telegram messages.

    The queue bridges synchronous contexts (APScheduler threads, scanner
    threads) with the async Telegram bot via two entry points:

    * ``put_nowait()`` — safe to call from any thread without ``await``.
    * ``put()`` — async coroutine for callers that already hold the event loop.

    The ``consume()`` coroutine must be started as an ``asyncio.Task`` once the
    ``telegram.Bot`` instance is available (typically inside ``main()``).
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[BroadcastMessage] = asyncio.Queue()

    async def put(
        self,
        channel_id: int,
        text: str,
        parse_mode: str = "Markdown",
        photo_path: Optional[str] = None,
    ) -> None:
        """Enqueue a message from an async context.

        Parameters
        ----------
        channel_id:
            Target Telegram chat/channel ID.
        text:
            Message body or photo caption.
        parse_mode:
            Telegram formatting mode (``"Markdown"`` or ``"HTML"``).
        photo_path:
            Optional path to an image file; triggers a photo send.
        """
        await self._queue.put(
            BroadcastMessage(channel_id, text, parse_mode, photo_path)
        )

    def put_nowait(
        self,
        channel_id: int,
        text: str,
        parse_mode: str = "Markdown",
        photo_path: Optional[str] = None,
    ) -> None:
        """Enqueue a message from a *non-async* context (e.g. a scheduler thread).

        Uses ``asyncio.Queue.put_nowait`` which is safe to call from any thread
        as long as the queue was created on the main event loop.  If the queue
        is full ``asyncio.QueueFull`` is raised, but the default queue is
        unbounded so this should not occur in practice.

        Parameters
        ----------
        channel_id:
            Target Telegram chat/channel ID.
        text:
            Message body or photo caption.
        parse_mode:
            Telegram formatting mode.
        photo_path:
            Optional path to an image file.
        """
        self._queue.put_nowait(
            BroadcastMessage(channel_id, text, parse_mode, photo_path)
        )

    async def consume(self, bot: object) -> None:  # bot: telegram.Bot
        """Long-running consumer coroutine — deliver queued messages with rate limiting.

        Should be started as a background ``asyncio.Task`` after the bot is
        initialised::

            asyncio.create_task(broadcast_queue.consume(application.bot))

        Parameters
        ----------
        bot:
            A ``telegram.Bot`` instance (or any object with compatible
            ``send_message`` / ``send_photo`` async methods).
        """
        while True:
            msg = await self._queue.get()
            try:
                if msg.photo_path:
                    with open(msg.photo_path, "rb") as photo_fp:  # noqa: WPS515
                        await bot.send_photo(  # type: ignore[attr-defined]
                            chat_id=msg.channel_id,
                            photo=photo_fp,
                            caption=msg.text,
                            parse_mode=msg.parse_mode,
                        )
                else:
                    await bot.send_message(  # type: ignore[attr-defined]
                        chat_id=msg.channel_id,
                        text=msg.text,
                        parse_mode=msg.parse_mode,
                    )
                # Rate-limit: stay well below Telegram's 30 msg/sec cap
                await asyncio.sleep(_RATE_LIMIT_SLEEP)
            except Exception as exc:
                logger.error(
                    "Broadcast failed to %s: %s",
                    msg.channel_id,
                    exc,
                )
            finally:
                self._queue.task_done()
