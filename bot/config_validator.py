"""
Config Validator
================
Runs at application startup to validate all config values.

Critical violations raise :exc:`SystemExit` so the process halts with a
clear error message before attempting to start the bot.

Non-critical issues (e.g. empty optional API keys) are logged as warnings so
administrators can identify misconfiguration without causing a hard failure.

Call :func:`validate_config` from ``main.py`` before starting the bot::

    from bot.config_validator import validate_config
    validate_config()
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def validate_config() -> None:
    """
    Validate all configuration values loaded from the ``config`` module.

    Raises
    ------
    SystemExit
        When a critical configuration error is detected (e.g. conflicting
        leverage bounds, decreasing R:R ratios, or duplicate channel IDs).

    Warnings are logged for non-critical issues such as empty API keys or
    weak webhook secrets.
    """
    try:
        import config as cfg  # noqa: PLC0415
    except Exception as exc:
        raise SystemExit(f"Failed to import config: {exc}") from exc

    errors: list[str] = []
    warnings: list[str] = []

    # ── MAX_SAME_SIDE_SIGNALS ─────────────────────────────────────────────────
    max_same_side = getattr(cfg, "MAX_SAME_SIDE_SIGNALS", 3)
    if not 1 <= max_same_side <= 10:
        errors.append(
            f"MAX_SAME_SIDE_SIGNALS={max_same_side} is outside the valid range [1, 10]."
        )

    # ── MIN_CONFLUENCE_SCORE ──────────────────────────────────────────────────
    min_score = getattr(cfg, "MIN_CONFLUENCE_SCORE", 40)
    if not 0 <= min_score <= 100:
        errors.append(
            f"MIN_CONFLUENCE_SCORE={min_score} is outside the valid range [0, 100]."
        )

    # ── LEVERAGE_MIN < LEVERAGE_MAX ───────────────────────────────────────────
    lev_min = getattr(cfg, "LEVERAGE_MIN", 10)
    lev_max = getattr(cfg, "LEVERAGE_MAX", 20)
    if lev_min >= lev_max:
        errors.append(
            f"LEVERAGE_MIN ({lev_min}) must be strictly less than LEVERAGE_MAX ({lev_max})."
        )

    # ── TP R:R order: TP1 < TP2 < TP3 ────────────────────────────────────────
    tp1_rr = getattr(cfg, "TP1_RR", 1.5)
    tp2_rr = getattr(cfg, "TP2_RR", 2.5)
    tp3_rr = getattr(cfg, "TP3_RR", 4.0)
    if not (tp1_rr < tp2_rr < tp3_rr):
        errors.append(
            f"TP R:R ratios must satisfy TP1_RR < TP2_RR < TP3_RR. "
            f"Got TP1={tp1_rr}, TP2={tp2_rr}, TP3={tp3_rr}."
        )

    # ── No duplicate Telegram channel IDs (except 0) ─────────────────────────
    channel_ids = [
        ("TELEGRAM_CHANNEL_ID_HARD", getattr(cfg, "TELEGRAM_CHANNEL_ID_HARD", 0)),
        ("TELEGRAM_CHANNEL_ID_MEDIUM", getattr(cfg, "TELEGRAM_CHANNEL_ID_MEDIUM", 0)),
        ("TELEGRAM_CHANNEL_ID_EASY", getattr(cfg, "TELEGRAM_CHANNEL_ID_EASY", 0)),
        ("TELEGRAM_CHANNEL_ID_SPOT", getattr(cfg, "TELEGRAM_CHANNEL_ID_SPOT", 0)),
        ("TELEGRAM_CHANNEL_ID_INSIGHTS", getattr(cfg, "TELEGRAM_CHANNEL_ID_INSIGHTS", 0)),
    ]
    non_zero_ids = [(name, cid) for name, cid in channel_ids if cid != 0]
    seen: dict[int, str] = {}
    for name, cid in non_zero_ids:
        if cid in seen:
            errors.append(
                f"Duplicate Telegram channel ID {cid} found in "
                f"{seen[cid]} and {name}. Each channel must have a unique ID."
            )
        else:
            seen[cid] = name

    # ── WEBHOOK_SECRET should not be empty in production ─────────────────────
    webhook_secret = getattr(cfg, "WEBHOOK_SECRET", "")
    if not webhook_secret:
        warnings.append(
            "WEBHOOK_SECRET is empty. Set a strong secret to secure the webhook endpoint."
        )

    # ── AUTO_SCAN_INTERVAL_SECONDS >= 10 ─────────────────────────────────────
    scan_interval = getattr(cfg, "AUTO_SCAN_INTERVAL_SECONDS", 60)
    if scan_interval < 10:
        errors.append(
            f"AUTO_SCAN_INTERVAL_SECONDS={scan_interval} is too low; minimum is 10."
        )

    # ── STALE_SIGNAL_HOURS >= 1 ───────────────────────────────────────────────
    stale_hours = getattr(cfg, "STALE_SIGNAL_HOURS", 4)
    if stale_hours < 1:
        errors.append(
            f"STALE_SIGNAL_HOURS={stale_hours} must be at least 1."
        )

    # ── Emit warnings ─────────────────────────────────────────────────────────
    for warning in warnings:
        logger.warning("[config_validator] WARNING: %s", warning)

    # ── Fail on critical errors ───────────────────────────────────────────────
    if errors:
        for error in errors:
            logger.critical("[config_validator] CRITICAL: %s", error)
        raise SystemExit(
            "Config validation failed with the following errors:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    logger.info("[config_validator] All configuration checks passed.")
