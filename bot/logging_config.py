"""Structured JSON logging configuration for 360 Crypto Eye Scalping."""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any


def generate_signal_id() -> str:
    """Generate a unique signal identifier using cryptographic randomness."""
    suffix = secrets.token_hex(6).upper()
    return f"SIG-{suffix}"


class JsonFormatter(logging.Formatter):
    """Format log records as JSON for machine-parseable output."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        # Carry through any extra fields
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                log_data[key] = val
        return json.dumps(log_data)


def configure_logging(level: int = logging.INFO, json_output: bool = False) -> None:
    """Configure root logger with optional JSON structured output."""
    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers[0] = handler
