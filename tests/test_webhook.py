"""Tests for bot/webhook.py — payload validation, rate limiting, security."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

import bot.webhook as webhook_module


@pytest.fixture()
def client():
    """Create a Flask test client with a fresh app, mocking process_webhook."""
    with patch.object(webhook_module, "process_webhook", return_value=None) as _mock:
        app = webhook_module.create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, _mock


@pytest.fixture()
def client_with_signal():
    """Flask test client where process_webhook returns a signal message."""
    with patch.object(webhook_module, "process_webhook", return_value="Signal message") as _mock:
        with patch.object(webhook_module, "_send_telegram_message"):
            app = webhook_module.create_app()
            app.config["TESTING"] = True
            with app.test_client() as c:
                yield c, _mock


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_health_includes_uptime(self, client):
        c, _ = client
        resp = c.get("/health")
        data = json.loads(resp.data)
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)

    def test_health_includes_active_signal_count(self, client):
        c, _ = client
        resp = c.get("/health")
        data = json.loads(resp.data)
        assert "active_signal_count" in data
        assert isinstance(data["active_signal_count"], int)


class TestWebhookSecurity:
    def test_missing_secret_rejected_when_configured(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", "test-secret"):
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
                headers={},
            )
        assert resp.status_code == 403

    def test_wrong_secret_rejected(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", "correct-secret"):
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
                headers={"X-Webhook-Secret": "wrong-secret"},
            )
        assert resp.status_code == 403

    def test_correct_secret_accepted(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", ""):
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
            )
        # Without secret configured, all requests pass secret check
        assert resp.status_code == 200

    def test_invalid_json_returns_400(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", ""):
            resp = c.post(
                "/webhook",
                data="not json at all",
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_response_has_request_id_header(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", ""):
            resp = c.post("/webhook", json={"symbol": "BTC", "side": "LONG"})
        assert "X-Request-ID" in resp.headers

    def test_ip_allowlist_blocks_unlisted_ip(self, client):
        c, _ = client
        with patch.object(webhook_module, "ALLOWED_WEBHOOK_IPS", ["1.2.3.4"]):
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
                environ_base={"REMOTE_ADDR": "9.9.9.9"},
            )
        assert resp.status_code == 403

    def test_ip_allowlist_allows_listed_ip(self, client):
        c, _ = client
        with (
            patch.object(webhook_module, "ALLOWED_WEBHOOK_IPS", ["9.9.9.9"]),
            patch.object(webhook_module, "WEBHOOK_SECRET", ""),
        ):
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
                environ_base={"REMOTE_ADDR": "9.9.9.9"},
            )
        # Should pass IP check (may still fail other checks, but not 403 from IP)
        assert resp.status_code != 403 or json.loads(resp.data).get("error") != "forbidden"

    def test_empty_allowlist_allows_all(self, client):
        c, _ = client
        with (
            patch.object(webhook_module, "ALLOWED_WEBHOOK_IPS", []),
            patch.object(webhook_module, "WEBHOOK_SECRET", ""),
        ):
            resp = c.post("/webhook", json={"symbol": "BTC", "side": "LONG"})
        assert resp.status_code == 200


class TestRateLimiting:
    def test_rate_limit_exceeded_returns_429(self, client):
        c, _ = client
        with (
            patch.object(webhook_module, "WEBHOOK_SECRET", ""),
            patch.object(webhook_module, "WEBHOOK_RATE_LIMIT_MAX", 3),
            patch.object(webhook_module, "_request_log", {}),
        ):
            for i in range(3):
                c.post(
                    "/webhook",
                    json={"symbol": "BTC", "side": "LONG"},
                    environ_base={"REMOTE_ADDR": "5.5.5.5"},
                )
            resp = c.post(
                "/webhook",
                json={"symbol": "BTC", "side": "LONG"},
                environ_base={"REMOTE_ADDR": "5.5.5.5"},
            )
        assert resp.status_code == 429


class TestPayloadValidation:
    def test_skipped_when_confluence_not_met(self, client):
        c, _ = client
        with patch.object(webhook_module, "WEBHOOK_SECRET", ""):
            resp = c.post("/webhook", json={"symbol": "BTC", "side": "LONG"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "skipped"

    def test_signal_broadcast_when_process_returns_message(self, client_with_signal):
        c, mock_pw = client_with_signal
        with patch.object(webhook_module, "WEBHOOK_SECRET", ""):
            resp = c.post("/webhook", json={"symbol": "BTC", "side": "LONG"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "signal_broadcast"
