"""
Webhook Receiver — TradingView → 360 Eye Bot
=============================================
Exposes a Flask HTTP endpoint that accepts JSON payloads from TradingView
alerts and forwards them through the signal engine.

Data flow:
  TradingView Alert → POST /webhook → signal_engine → Telegram Bot API

Security:
  All requests must include the ``X-Webhook-Secret`` header matching the
  ``WEBHOOK_SECRET`` environment variable.  Requests without a valid secret
  are rejected with HTTP 403.

Run standalone:
  python -m bot.webhook

Or via gunicorn in production:
  gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:5000
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
import uuid
from collections import defaultdict
from typing import Any

from flask import Flask, Response, jsonify, request

from bot.bot import dashboard, process_webhook, risk_manager, signal_router
from bot.dashboard_web import register_dashboard_routes
from config import (
    ALLOWED_WEBHOOK_IPS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    WEBHOOK_RATE_LIMIT_MAX,
    WEBHOOK_RATE_LIMIT_WINDOW,
    WEBHOOK_SECRET,
)

try:
    from config import (
        TELEGRAM_CHANNEL_ID_HARD,
        TELEGRAM_CHANNEL_ID_MEDIUM,
        TELEGRAM_CHANNEL_ID_EASY,
    )
except ImportError:
    TELEGRAM_CHANNEL_ID_HARD = 0
    TELEGRAM_CHANNEL_ID_MEDIUM = 0
    TELEGRAM_CHANNEL_ID_EASY = 0

logger = logging.getLogger(__name__)

# ── Start time for uptime tracking ───────────────────────────────────────────
_start_time = time.time()

# ── Rate limiting: track request timestamps per IP ───────────────────────────
_request_log: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()

# ── Pydantic payload validation (optional but available) ─────────────────────
try:
    from pydantic import BaseModel, field_validator

    class WebhookPayload(BaseModel):
        symbol: str
        side: str

        @field_validator("side")
        @classmethod
        def side_must_be_valid(cls, v: str) -> str:
            upper = v.upper()
            if upper not in ("LONG", "SHORT"):
                raise ValueError("side must be LONG or SHORT")
            return upper

        @field_validator("symbol")
        @classmethod
        def symbol_not_empty(cls, v: str) -> str:
            if not v.strip():
                raise ValueError("symbol must not be empty")
            return v.strip().upper()

    _pydantic_available = True
except ImportError:
    _pydantic_available = False


def _verify_secret(incoming: str) -> bool:
    """Constant-time comparison of the shared webhook secret to prevent timing attacks."""
    if not WEBHOOK_SECRET:
        # If no secret is configured, skip verification (dev mode only).
        logger.warning("WEBHOOK_SECRET is not set — all requests are accepted.")
        return True
    return hmac.compare_digest(incoming, WEBHOOK_SECRET)


def _check_ip_allowlist(remote_addr: str) -> bool:
    """Return True when the IP is allowed (or when no allowlist is configured)."""
    if not ALLOWED_WEBHOOK_IPS:
        return True
    return remote_addr in ALLOWED_WEBHOOK_IPS


def _check_rate_limit(remote_addr: str) -> bool:
    """Return True when the IP has not exceeded the rate limit."""
    with _rate_limit_lock:
        now = time.time()
        window_start = now - WEBHOOK_RATE_LIMIT_WINDOW
        existing = _request_log.get(remote_addr, [])
        _request_log[remote_addr] = [t for t in existing if t > window_start]
        if len(_request_log[remote_addr]) >= WEBHOOK_RATE_LIMIT_MAX:
            return False
        _request_log[remote_addr].append(now)
        return True


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(__name__)

    if not WEBHOOK_SECRET:
        logger.critical(
            "WEBHOOK_SECRET is not configured — webhook endpoint is unprotected!"
        )

    @app.route("/health", methods=["GET"])
    def health() -> Response:
        uptime_seconds = int(time.time() - _start_time)
        active_count = len(risk_manager.active_signals)
        return jsonify({
            "status": "ok",
            "service": "360-crypto-eye-scalping",
            "uptime_seconds": uptime_seconds,
            "active_signal_count": active_count,
            "channels": {
                "ch1_hard": bool(TELEGRAM_CHANNEL_ID_HARD),
                "ch2_medium": bool(TELEGRAM_CHANNEL_ID_MEDIUM),
                "ch3_easy": bool(TELEGRAM_CHANNEL_ID_EASY),
            },
            "circuit_breaker": "closed",
            "last_scan_ts": None,
        })

    @app.route("/webhook", methods=["POST"])
    def webhook() -> Response:
        request_id = str(uuid.uuid4())

        # ── IP allowlist check ────────────────────────────────────────────────
        remote_addr = request.remote_addr or ""
        if not _check_ip_allowlist(remote_addr):
            logger.warning(
                "Rejected webhook — IP not in allowlist: %s [request_id=%s]",
                remote_addr, request_id,
            )
            resp = jsonify({"error": "forbidden"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 403

        # ── Rate limit check ──────────────────────────────────────────────────
        if not _check_rate_limit(remote_addr):
            logger.warning(
                "Rate limit exceeded for %s [request_id=%s]", remote_addr, request_id
            )
            resp = jsonify({"error": "rate limit exceeded"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 429

        # ── Secret check ──────────────────────────────────────────────────────
        secret = request.headers.get("X-Webhook-Secret", "")
        if not _verify_secret(secret):
            logger.warning(
                "Rejected webhook — invalid secret from %s [request_id=%s]",
                remote_addr, request_id,
            )
            resp = jsonify({"error": "forbidden"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 403

        raw_payload = request.get_json(silent=True)
        if raw_payload is None:
            resp = jsonify({"error": "invalid JSON"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 400

        # ── Pydantic validation ───────────────────────────────────────────────
        if _pydantic_available:
            try:
                validated = WebhookPayload(**raw_payload)
                payload: dict[str, Any] = validated.model_dump()
            except Exception as exc:
                logger.warning("Payload validation failed [request_id=%s]: %s", request_id, exc)
                resp = jsonify({"error": "invalid payload", "detail": str(exc)})
                resp.headers["X-Request-ID"] = request_id
                return resp, 422
        else:
            payload = raw_payload

        try:
            message = process_webhook(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error processing webhook [request_id=%s]: %s", request_id, exc)
            resp = jsonify({"error": "internal error"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 500

        if message is None:
            resp = jsonify({"status": "skipped", "reason": "confluence not met or news freeze"})
            resp.headers["X-Request-ID"] = request_id
            return resp, 200

        # Unpack (message, tier) tuple from process_webhook, or handle legacy str
        if isinstance(message, tuple):
            text, tier = message
        else:
            # Legacy path: process_webhook returned a plain string (e.g., from mocks/older code)
            logger.debug("process_webhook returned a plain string — using legacy TELEGRAM_CHANNEL_ID fallback")
            text, tier = message, None

        # Route to the appropriate channel via SignalRouter
        if tier is not None and signal_router.is_channel_enabled(tier):
            channel_id = signal_router.get_channel_id(tier)
        else:
            channel_id = TELEGRAM_CHANNEL_ID

        # Async broadcast via Telegram Bot API
        _send_telegram_message(text, channel_id)
        resp = jsonify({"status": "signal_broadcast"})
        resp.headers["X-Request-ID"] = request_id
        return resp, 200

    # Register the performance dashboard routes
    register_dashboard_routes(
        app,
        get_dashboard_fn=lambda: dashboard,
        get_risk_manager_fn=lambda: risk_manager,
    )

    return app


def _send_telegram_message(text: str, channel_id: int = TELEGRAM_CHANNEL_ID) -> None:
    """
    Send *text* to the specified Telegram channel using the Bot API.

    The actual HTTP call is performed on a background daemon thread so that
    the Flask worker is not blocked while waiting for the Telegram API.
    """
    def _send() -> None:
        import json as _json
        import urllib.error
        import urllib.request

        if not TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN not set — skipping Telegram broadcast.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = _json.dumps({
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()

        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.debug("Telegram API response: %s", resp.read())
        except urllib.error.URLError as exc:
            logger.error("Failed to send Telegram message: %s", exc)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
