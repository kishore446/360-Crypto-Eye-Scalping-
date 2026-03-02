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

from flask import Flask, Response, jsonify, request

from bot.bot import process_webhook
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_SECRET

logger = logging.getLogger(__name__)


def _verify_secret(incoming: str) -> bool:
    """Constant-time comparison of the shared webhook secret to prevent timing attacks."""
    if not WEBHOOK_SECRET:
        # If no secret is configured, skip verification (dev mode only).
        logger.warning("WEBHOOK_SECRET is not set — all requests are accepted.")
        return True
    return hmac.compare_digest(incoming, WEBHOOK_SECRET)


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health() -> Response:
        return jsonify({"status": "ok", "service": "360-crypto-eye-scalping"})

    @app.route("/webhook", methods=["POST"])
    def webhook() -> Response:
        secret = request.headers.get("X-Webhook-Secret", "")
        if not _verify_secret(secret):
            logger.warning("Rejected webhook — invalid secret from %s", request.remote_addr)
            return jsonify({"error": "forbidden"}), 403

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid JSON"}), 400

        try:
            message = process_webhook(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error processing webhook: %s", exc)
            return jsonify({"error": "internal error"}), 500

        if message is None:
            return jsonify({"status": "skipped", "reason": "confluence not met or news freeze"}), 200

        # Async broadcast via Telegram Bot API
        _send_telegram_message(message)
        return jsonify({"status": "signal_broadcast"}), 200

    return app


def _send_telegram_message(text: str) -> None:
    """
    Send *text* to the public channel using the Telegram Bot API (synchronous).

    In production prefer the async handler in bot.py.  This synchronous
    helper exists specifically for the webhook context where an async event
    loop is not available.
    """
    import urllib.request
    import urllib.error
    import json as _json

    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping Telegram broadcast.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = _json.dumps({
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()

    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.debug("Telegram API response: %s", resp.read())
    except urllib.error.URLError as exc:
        logger.error("Failed to send Telegram message: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(host=WEBHOOK_HOST, port=WEBHOOK_PORT)
