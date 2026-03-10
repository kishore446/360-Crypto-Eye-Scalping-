"""
Tests for BroadcastQueue in bot/broadcast.py
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.broadcast import BroadcastMessage, BroadcastQueue


class TestBroadcastMessage:
    def test_default_parse_mode(self):
        msg = BroadcastMessage(channel_id=123, text="Hello")
        assert msg.parse_mode == "Markdown"
        assert msg.photo_path is None

    def test_custom_fields(self):
        msg = BroadcastMessage(
            channel_id=456,
            text="Signal",
            parse_mode="HTML",
            photo_path="/tmp/chart.png",
        )
        assert msg.channel_id == 456
        assert msg.parse_mode == "HTML"
        assert msg.photo_path == "/tmp/chart.png"


class TestBroadcastQueue:
    @pytest.mark.asyncio
    async def test_put_enqueues_message(self):
        bq = BroadcastQueue()
        await bq.put(channel_id=111, text="Test msg")
        assert bq._queue.qsize() == 1

    def test_put_nowait_enqueues_from_thread(self):
        bq = BroadcastQueue()
        bq.put_nowait(channel_id=222, text="Thread msg")
        assert bq._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_put_nowait_message_fields(self):
        bq = BroadcastQueue()
        bq.put_nowait(channel_id=333, text="Hello", parse_mode="HTML")
        msg = bq._queue.get_nowait()
        assert msg.channel_id == 333
        assert msg.text == "Hello"
        assert msg.parse_mode == "HTML"

    @pytest.mark.asyncio
    async def test_consume_sends_text_message(self):
        bq = BroadcastQueue()
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        await bq.put(channel_id=100, text="Signal!")

        # Run consume for one iteration then cancel
        async def run_one():
            task = asyncio.create_task(bq.consume(mock_bot))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_one()
        mock_bot.send_message.assert_called_once_with(
            chat_id=100,
            text="Signal!",
            parse_mode="Markdown",
        )

    @pytest.mark.asyncio
    async def test_consume_sends_photo_message(self, tmp_path):
        bq = BroadcastQueue()
        mock_bot = AsyncMock()
        mock_bot.send_photo = AsyncMock()

        photo_file = tmp_path / "chart.png"
        photo_file.write_bytes(b"fake-png-data")

        await bq.put(channel_id=200, text="Chart!", photo_path=str(photo_file))

        async def run_one():
            task = asyncio.create_task(bq.consume(mock_bot))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_one()
        assert mock_bot.send_photo.called
        call_kwargs = mock_bot.send_photo.call_args
        assert call_kwargs.kwargs["chat_id"] == 200
        assert call_kwargs.kwargs["caption"] == "Chart!"

    @pytest.mark.asyncio
    async def test_consume_continues_after_error(self):
        """Consumer must not crash when one message fails; next messages still go through."""
        bq = BroadcastQueue()
        mock_bot = AsyncMock()
        # First call raises, second succeeds
        mock_bot.send_message = AsyncMock(
            side_effect=[RuntimeError("Telegram error"), None]
        )

        await bq.put(channel_id=1, text="Msg 1")
        await bq.put(channel_id=2, text="Msg 2")

        async def run_two():
            task = asyncio.create_task(bq.consume(mock_bot))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_two()
        # Both calls should have been attempted despite the first failing
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_puts_and_consumes(self):
        """All queued messages must be delivered."""
        bq = BroadcastQueue()
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        for i in range(5):
            await bq.put(channel_id=i, text=f"msg {i}")

        async def run():
            task = asyncio.create_task(bq.consume(mock_bot))
            await asyncio.sleep(0.5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run()
        assert mock_bot.send_message.call_count == 5
