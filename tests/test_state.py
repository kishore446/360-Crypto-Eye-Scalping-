"""Tests for bot/state.py — BotState thread safety."""
from __future__ import annotations

import threading

import pytest

from bot.state import BotState


def _reset_singleton() -> None:
    """Reset the BotState singleton so tests can re-create it with a fresh state."""
    BotState._instance = None


class TestBotStateSingleton:
    def test_singleton_returns_same_instance(self):
        a = BotState()
        b = BotState()
        assert a is b

    def test_default_values(self):
        state = BotState()
        assert state.news_freeze is False
        assert state.trail_active is False
        assert state.auto_scan_active is True

    def test_auto_scan_active_follows_boot_config_true(self, monkeypatch):
        """auto_scan_active is True on first creation when AUTO_SCAN_ENABLED_ON_BOOT=True."""
        import bot.state as _state_mod

        monkeypatch.setattr(_state_mod, "_AUTO_SCAN_ENABLED_ON_BOOT", True)
        _reset_singleton()
        state = BotState()
        assert state.auto_scan_active is True
        _reset_singleton()

    def test_auto_scan_active_follows_boot_config_false(self, monkeypatch):
        """auto_scan_active is False on first creation when AUTO_SCAN_ENABLED_ON_BOOT=False."""
        import bot.state as _state_mod

        monkeypatch.setattr(_state_mod, "_AUTO_SCAN_ENABLED_ON_BOOT", False)
        _reset_singleton()
        state = BotState()
        assert state.auto_scan_active is False
        _reset_singleton()

    def test_set_news_freeze(self):
        state = BotState()
        original = state.news_freeze
        state.news_freeze = not original
        assert state.news_freeze is not original
        # restore
        state.news_freeze = original

    def test_set_trail_active(self):
        state = BotState()
        state.trail_active = True
        assert state.trail_active is True
        state.trail_active = False

    def test_set_auto_scan_active(self):
        state = BotState()
        state.auto_scan_active = True
        assert state.auto_scan_active is True
        state.auto_scan_active = False

    def test_toggle_auto_scan_active(self):
        """Toggling auto_scan_active at runtime overrides the boot default."""
        state = BotState()
        original = state.auto_scan_active
        state.auto_scan_active = not original
        assert state.auto_scan_active is not original
        # restore
        state.auto_scan_active = original


class TestBotStateThreadSafety:
    def test_concurrent_writes_do_not_raise(self):
        """Many threads toggling state concurrently should not raise or corrupt."""
        state = BotState()
        errors: list[Exception] = []

        def toggle_news(n: int) -> None:
            try:
                for _ in range(n):
                    state.news_freeze = True
                    state.news_freeze = False
            except Exception as exc:
                errors.append(exc)

        def toggle_trail(n: int) -> None:
            try:
                for _ in range(n):
                    state.trail_active = True
                    state.trail_active = False
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=toggle_news, args=(100,)) for _ in range(5)]
        threads += [threading.Thread(target=toggle_trail, args=(100,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors in threads: {errors}"

    def test_concurrent_reads_always_bool(self):
        """All read values must be bool (no partial writes visible)."""
        state = BotState()
        results: list = []

        def read_state() -> None:
            for _ in range(50):
                results.append(state.news_freeze)
                results.append(state.auto_scan_active)

        threads = [threading.Thread(target=read_state) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(isinstance(v, bool) for v in results)
