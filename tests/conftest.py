"""Shared pytest fixtures for 360 Crypto Eye Scalping tests."""
from __future__ import annotations

import pytest
import bot.risk_manager as _rm


@pytest.fixture(autouse=True)
def _isolate_signals_file(tmp_path, monkeypatch):
    """
    Give each test its own temporary signals.json path so that persistence
    calls in RiskManager do not contaminate other tests.
    """
    monkeypatch.setattr(_rm, "SIGNALS_FILE", str(tmp_path / "test_signals.json"))
