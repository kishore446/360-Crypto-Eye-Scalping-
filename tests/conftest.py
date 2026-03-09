"""Shared pytest fixtures for 360 Crypto Eye Scalping tests."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Set dummy environment variables before any bot module imports.
# This prevents real network calls to Binance/Telegram during import.
# ---------------------------------------------------------------------------
_DUMMY_ENV = {
    "TELEGRAM_BOT_TOKEN": "test:fake-token",
    "TELEGRAM_CH1_ID": "-1001234567890",
    "TELEGRAM_CH2_ID": "-1001234567891",
    "TELEGRAM_CH3_ID": "-1001234567892",
    "TELEGRAM_CH4_ID": "-1001234567893",
    "TELEGRAM_CH5_ID": "-1001234567894",
    "TELEGRAM_ADMIN_CHAT_ID": "-1001234567895",
    "BINANCE_API_KEY": "fake-api-key",
    "BINANCE_API_SECRET": "fake-api-secret",
}

for _key, _val in _DUMMY_ENV.items():
    os.environ.setdefault(_key, _val)

import bot.risk_manager as _rm  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_signals_file(tmp_path, monkeypatch):
    """
    Give each test its own temporary signals.json path so that persistence
    calls in RiskManager do not contaminate other tests.
    """
    monkeypatch.setattr(_rm, "SIGNALS_FILE", str(tmp_path / "test_signals.json"))


@pytest.fixture(autouse=True)
def _mock_network_clients(monkeypatch):
    """
    Patch network-dependent clients (Binance, Telegram) to prevent real
    HTTP connections during tests.
    """
    # Mock httpx to prevent any real HTTP calls
    mock_httpx_client = MagicMock()
    mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
    mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
    mock_httpx_client.get = AsyncMock(return_value=MagicMock(
        status_code=200,
        json=MagicMock(return_value={}),
        raise_for_status=MagicMock(),
    ))

    with (
        patch("httpx.AsyncClient", return_value=mock_httpx_client),
        patch("httpx.Client", return_value=mock_httpx_client),
    ):
        yield
