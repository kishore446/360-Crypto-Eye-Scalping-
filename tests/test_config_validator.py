"""
Tests for bot/config_validator.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.config_validator import validate_config


def _make_valid_config(**overrides) -> MagicMock:
    """Return a MagicMock that looks like a valid config module."""
    defaults = {
        "MAX_SAME_SIDE_SIGNALS": 3,
        "MIN_CONFLUENCE_SCORE": 40,
        "LEVERAGE_MIN": 10,
        "LEVERAGE_MAX": 20,
        "TP1_RR": 1.5,
        "TP2_RR": 2.5,
        "TP3_RR": 4.0,
        "TELEGRAM_CHANNEL_ID_HARD": 100,
        "TELEGRAM_CHANNEL_ID_MEDIUM": 200,
        "TELEGRAM_CHANNEL_ID_EASY": 300,
        "TELEGRAM_CHANNEL_ID_SPOT": 400,
        "TELEGRAM_CHANNEL_ID_INSIGHTS": 500,
        "WEBHOOK_SECRET": "strong_secret",
        "AUTO_SCAN_INTERVAL_SECONDS": 60,
        "STALE_SIGNAL_HOURS": 4,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for key, value in defaults.items():
        setattr(cfg, key, value)
    return cfg


class TestValidateConfig:
    def test_passes_with_valid_config(self) -> None:
        cfg = _make_valid_config()
        with patch("bot.config_validator.importlib", create=True):
            with patch.dict("sys.modules", {"config": cfg}):
                # Should not raise
                validate_config()

    def test_raises_on_max_same_side_signals_too_low(self) -> None:
        cfg = _make_valid_config(MAX_SAME_SIDE_SIGNALS=0)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="MAX_SAME_SIDE_SIGNALS"):
                validate_config()

    def test_raises_on_max_same_side_signals_too_high(self) -> None:
        cfg = _make_valid_config(MAX_SAME_SIDE_SIGNALS=11)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="MAX_SAME_SIDE_SIGNALS"):
                validate_config()

    def test_raises_on_invalid_confluence_score(self) -> None:
        cfg = _make_valid_config(MIN_CONFLUENCE_SCORE=150)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="MIN_CONFLUENCE_SCORE"):
                validate_config()

    def test_raises_when_leverage_min_equals_max(self) -> None:
        cfg = _make_valid_config(LEVERAGE_MIN=10, LEVERAGE_MAX=10)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="LEVERAGE_MIN"):
                validate_config()

    def test_raises_when_leverage_min_greater_than_max(self) -> None:
        cfg = _make_valid_config(LEVERAGE_MIN=20, LEVERAGE_MAX=10)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="LEVERAGE_MIN"):
                validate_config()

    def test_raises_on_invalid_tp_order(self) -> None:
        cfg = _make_valid_config(TP1_RR=3.0, TP2_RR=2.0, TP3_RR=4.0)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="TP"):
                validate_config()

    def test_raises_on_duplicate_channel_ids(self) -> None:
        cfg = _make_valid_config(
            TELEGRAM_CHANNEL_ID_HARD=100,
            TELEGRAM_CHANNEL_ID_MEDIUM=100,  # duplicate!
        )
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="Duplicate"):
                validate_config()

    def test_zero_channel_ids_not_flagged_as_duplicate(self) -> None:
        cfg = _make_valid_config(
            TELEGRAM_CHANNEL_ID_HARD=0,
            TELEGRAM_CHANNEL_ID_MEDIUM=0,
            TELEGRAM_CHANNEL_ID_EASY=0,
            TELEGRAM_CHANNEL_ID_SPOT=0,
            TELEGRAM_CHANNEL_ID_INSIGHTS=0,
        )
        with patch.dict("sys.modules", {"config": cfg}):
            # Should not raise — zeros are the "not configured" sentinel
            validate_config()

    def test_raises_when_scan_interval_too_low(self) -> None:
        cfg = _make_valid_config(AUTO_SCAN_INTERVAL_SECONDS=5)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="AUTO_SCAN_INTERVAL_SECONDS"):
                validate_config()

    def test_raises_when_stale_hours_too_low(self) -> None:
        cfg = _make_valid_config(STALE_SIGNAL_HOURS=0)
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit, match="STALE_SIGNAL_HOURS"):
                validate_config()

    def test_empty_webhook_secret_only_warns(self, caplog) -> None:
        """Empty WEBHOOK_SECRET should log a warning, not raise."""
        cfg = _make_valid_config(WEBHOOK_SECRET="")
        with patch.dict("sys.modules", {"config": cfg}):
            with caplog.at_level("WARNING"):
                validate_config()  # Must not raise
        assert any("WEBHOOK_SECRET" in r.message for r in caplog.records)

    def test_multiple_errors_listed_in_exit_message(self) -> None:
        cfg = _make_valid_config(
            MAX_SAME_SIDE_SIGNALS=0,
            LEVERAGE_MIN=20,
            LEVERAGE_MAX=10,
        )
        with patch.dict("sys.modules", {"config": cfg}):
            with pytest.raises(SystemExit) as exc_info:
                validate_config()
        assert "MAX_SAME_SIDE_SIGNALS" in str(exc_info.value)
        assert "LEVERAGE_MIN" in str(exc_info.value)
