"""
Tests for updated toggle commands and new /status, /health commands.

Covers:
- /auto_scan on  → sets state to active
- /auto_scan off → sets state to inactive
- /auto_scan (no arg) → shows current state, no change
- /auto_scan invalid → shows usage hint
- Same pattern for /trail_sl and /news_caution
- /status → returns message with key status indicators
- /health → returns message with diagnostic info
- All commands are admin-only (non-admin gets "⛔ Admin only.")
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_update(user_id: int, text: str = "/cmd") -> MagicMock:
    """Return a minimal Update-like mock."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(*args: str) -> MagicMock:
    """Return a context mock with the given args list."""
    ctx = MagicMock()
    ctx.args = list(args)
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


ADMIN_ID = 999
NON_ADMIN_ID = 123


# ── Fixture: patch bot globals ────────────────────────────────────────────────

@pytest.fixture()
def bot_env(monkeypatch):
    """Patch module-level bot globals so each test runs in isolation."""
    import bot.bot as _bot
    import bot.state as _state_mod

    # Reset BotState singleton
    _state_mod.BotState._instance = None
    state = _state_mod.BotState()
    state.auto_scan_active = True
    state.trail_active = False
    state.news_freeze = False
    monkeypatch.setattr(_bot, "_bot_state", state)

    # Patch ADMIN_CHAT_ID
    monkeypatch.setattr(_bot, "ADMIN_CHAT_ID", ADMIN_ID)

    # Patch ws_manager
    ws = MagicMock()
    ws.is_healthy.return_value = True
    ws.is_connected = True
    ws.last_message_at = time.monotonic() - 3.0
    ws._tasks = []
    monkeypatch.setattr(_bot, "ws_manager", ws)

    # Patch _dynamic_pairs
    monkeypatch.setattr(_bot, "_dynamic_pairs", list(range(10)))

    # Patch risk_manager
    rm = MagicMock()
    rm.active_signals = []
    monkeypatch.setattr(_bot, "risk_manager", rm)

    # Patch news_calendar
    nc = MagicMock()
    nc.format_caution_message.return_value = ""
    monkeypatch.setattr(_bot, "news_calendar", nc)

    # Patch TELEGRAM_CHANNEL_ID
    monkeypatch.setattr(_bot, "TELEGRAM_CHANNEL_ID", -1)
    monkeypatch.setattr(_bot, "TELEGRAM_BOT_TOKEN", "fake_token")

    # Patch _scheduler
    scheduler = MagicMock()
    scheduler.running = True
    scheduler.get_jobs.return_value = [MagicMock(id="job1"), MagicMock(id="job2")]
    monkeypatch.setattr(_bot, "_scheduler", scheduler)

    yield state, _bot

    _state_mod.BotState._instance = None


# ── /auto_scan tests ──────────────────────────────────────────────────────────

class TestAutoScanCommand:
    def test_on_sets_active(self, bot_env):
        state, _bot = bot_env
        state.auto_scan_active = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_auto_scan(update, ctx))
        assert state.auto_scan_active is True

    def test_off_sets_inactive(self, bot_env):
        state, _bot = bot_env
        state.auto_scan_active = True
        update = _make_update(ADMIN_ID)
        ctx = _make_context("off")
        _run(_bot.cmd_auto_scan(update, ctx))
        assert state.auto_scan_active is False

    def test_no_arg_shows_state_without_change(self, bot_env):
        state, _bot = bot_env
        state.auto_scan_active = True
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_auto_scan(update, ctx))
        assert state.auto_scan_active is True  # unchanged
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "ACTIVE" in reply_text

    def test_no_arg_inactive_shows_inactive(self, bot_env):
        state, _bot = bot_env
        state.auto_scan_active = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_auto_scan(update, ctx))
        assert state.auto_scan_active is False  # unchanged
        reply_text = update.message.reply_text.call_args[0][0]
        assert "INACTIVE" in reply_text

    def test_invalid_arg_shows_usage(self, bot_env):
        state, _bot = bot_env
        update = _make_update(ADMIN_ID)
        ctx = _make_context("toggle")
        _run(_bot.cmd_auto_scan(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Usage" in reply_text or "usage" in reply_text.lower()

    def test_non_admin_blocked(self, bot_env):
        state, _bot = bot_env
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_auto_scan(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "⛔" in reply_text
        # state must not change
        assert state.auto_scan_active is True


# ── /trail_sl tests ───────────────────────────────────────────────────────────

class TestTrailSlCommand:
    def test_on_sets_active(self, bot_env):
        state, _bot = bot_env
        state.trail_active = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_trail_sl(update, ctx))
        assert state.trail_active is True

    def test_off_sets_inactive(self, bot_env):
        state, _bot = bot_env
        state.trail_active = True
        update = _make_update(ADMIN_ID)
        ctx = _make_context("off")
        _run(_bot.cmd_trail_sl(update, ctx))
        assert state.trail_active is False

    def test_no_arg_shows_state_without_change(self, bot_env):
        state, _bot = bot_env
        state.trail_active = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_trail_sl(update, ctx))
        assert state.trail_active is False  # unchanged
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "INACTIVE" in reply_text

    def test_invalid_arg_shows_usage(self, bot_env):
        state, _bot = bot_env
        update = _make_update(ADMIN_ID)
        ctx = _make_context("flip")
        _run(_bot.cmd_trail_sl(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Usage" in reply_text or "usage" in reply_text.lower()

    def test_non_admin_blocked(self, bot_env):
        state, _bot = bot_env
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_trail_sl(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "⛔" in reply_text
        assert state.trail_active is False


# ── /news_caution tests ───────────────────────────────────────────────────────

class TestNewsCautionCommand:
    def test_on_activates_freeze(self, bot_env):
        state, _bot = bot_env
        state.news_freeze = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_news_caution(update, ctx))
        assert state.news_freeze is True

    def test_off_deactivates_freeze(self, bot_env):
        state, _bot = bot_env
        state.news_freeze = True
        update = _make_update(ADMIN_ID)
        ctx = _make_context("off")
        _run(_bot.cmd_news_caution(update, ctx))
        assert state.news_freeze is False

    def test_no_arg_shows_state_without_change(self, bot_env):
        state, _bot = bot_env
        state.news_freeze = False
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_news_caution(update, ctx))
        assert state.news_freeze is False  # unchanged
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "INACTIVE" in reply_text

    def test_no_arg_active_shows_active(self, bot_env):
        state, _bot = bot_env
        state.news_freeze = True
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_news_caution(update, ctx))
        assert state.news_freeze is True  # unchanged
        reply_text = update.message.reply_text.call_args[0][0]
        assert "ACTIVE" in reply_text

    def test_invalid_arg_shows_usage(self, bot_env):
        state, _bot = bot_env
        update = _make_update(ADMIN_ID)
        ctx = _make_context("maybe")
        _run(_bot.cmd_news_caution(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Usage" in reply_text or "usage" in reply_text.lower()

    def test_non_admin_blocked(self, bot_env):
        state, _bot = bot_env
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("on")
        _run(_bot.cmd_news_caution(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "⛔" in reply_text
        assert state.news_freeze is False


# ── /status tests ─────────────────────────────────────────────────────────────

class TestStatusCommand:
    def test_returns_status_dashboard(self, bot_env):
        state, _bot = bot_env
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_status(update, ctx))
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Auto-Scanner" in reply_text
        assert "Trailing SL" in reply_text
        assert "News Caution" in reply_text
        assert "WebSocket" in reply_text
        assert "Scan Pairs" in reply_text
        assert "Active Signals" in reply_text
        assert "Uptime" in reply_text

    def test_non_admin_blocked(self, bot_env):
        _, _bot = bot_env
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_status(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "⛔" in reply_text


# ── /health tests ─────────────────────────────────────────────────────────────

class TestHealthCommand:
    def test_returns_health_diagnostics(self, bot_env):
        state, _bot = bot_env
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_health(update, ctx))
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "WebSocket" in reply_text
        assert "Scheduler" in reply_text
        assert "Memory" in reply_text
        assert "Auto-Scanner" in reply_text
        assert "Trailing SL" in reply_text
        assert "News Freeze" in reply_text
        assert "Active Signals" in reply_text

    def test_non_admin_blocked(self, bot_env):
        _, _bot = bot_env
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context()
        _run(_bot.cmd_health(update, ctx))
        reply_text = update.message.reply_text.call_args[0][0]
        assert "⛔" in reply_text
