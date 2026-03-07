"""
Tests for bot/subscriber_prefs.py
"""
from __future__ import annotations

import pytest

import bot.database as db_module
from bot.database import init_db, set_db_path, _get_conn
from bot.subscriber_prefs import (
    VALID_MODES,
    describe_mode,
    format_daily_digest,
    get_preference,
    get_users_for_mode,
    set_preference,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite database with subscriber_preferences table."""
    db_file = str(tmp_path / "test_subs.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    init_db()
    yield db_file


class TestSetPreference:
    def test_insert_new_preference(self) -> None:
        set_preference(12345, "all")
        assert get_preference(12345) == "all"

    def test_update_existing_preference(self) -> None:
        set_preference(12345, "all")
        set_preference(12345, "digest")
        assert get_preference(12345) == "digest"

    def test_all_valid_modes_accepted(self) -> None:
        for mode in VALID_MODES:
            set_preference(99, mode)
            assert get_preference(99) == mode

    def test_invalid_mode_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            set_preference(1, "invalid_mode")

    def test_multiple_users_independent(self) -> None:
        set_preference(1, "all")
        set_preference(2, "high_only")
        set_preference(3, "digest")
        assert get_preference(1) == "all"
        assert get_preference(2) == "high_only"
        assert get_preference(3) == "digest"


class TestGetPreference:
    def test_defaults_to_all_for_unknown_user(self) -> None:
        result = get_preference(99999)
        assert result == "all"

    def test_returns_saved_mode(self) -> None:
        set_preference(555, "digest")
        assert get_preference(555) == "digest"


class TestGetUsersForMode:
    def test_returns_empty_when_no_users(self) -> None:
        assert get_users_for_mode("digest") == []

    def test_returns_only_matching_users(self) -> None:
        set_preference(1, "all")
        set_preference(2, "digest")
        set_preference(3, "digest")
        result = get_users_for_mode("digest")
        assert sorted(result) == [2, 3]

    def test_returns_all_mode_users(self) -> None:
        set_preference(10, "all")
        set_preference(11, "all")
        set_preference(12, "high_only")
        result = get_users_for_mode("all")
        assert sorted(result) == [10, 11]


class TestFormatDailyDigest:
    def test_empty_signals_returns_no_signals_message(self) -> None:
        msg = format_daily_digest([])
        assert "No signals" in msg

    def test_includes_signal_info(self) -> None:
        signals = [
            {
                "symbol": "BTC",
                "side": "LONG",
                "confidence": "High",
                "tp1": 65_000.0,
                "stop_loss": 64_000.0,
                "outcome": "WIN",
                "pnl_pct": 1.5,
            }
        ]
        msg = format_daily_digest(signals)
        assert "BTC" in msg
        assert "LONG" in msg
        assert "High" in msg

    def test_open_trade_shows_open_icon(self) -> None:
        signals = [
            {
                "symbol": "ETH",
                "side": "SHORT",
                "confidence": "Medium",
                "tp1": 3_000.0,
                "stop_loss": 3_100.0,
                "outcome": "OPEN",
                "pnl_pct": 0.0,
            }
        ]
        msg = format_daily_digest(signals)
        assert "🟡" in msg

    def test_win_shows_checkmark(self) -> None:
        signals = [
            {
                "symbol": "SOL",
                "side": "LONG",
                "confidence": "High",
                "tp1": 200.0,
                "stop_loss": 190.0,
                "outcome": "WIN",
                "pnl_pct": 3.0,
            }
        ]
        msg = format_daily_digest(signals)
        assert "✅" in msg

    def test_loss_shows_cross(self) -> None:
        signals = [
            {
                "symbol": "BNB",
                "side": "SHORT",
                "confidence": "Low",
                "tp1": 280.0,
                "stop_loss": 300.0,
                "outcome": "LOSS",
                "pnl_pct": -1.0,
            }
        ]
        msg = format_daily_digest(signals)
        assert "❌" in msg

    def test_total_count_in_message(self) -> None:
        signals = [
            {"symbol": "X", "side": "LONG", "confidence": "High",
             "tp1": 1.0, "stop_loss": 0.9, "outcome": "WIN", "pnl_pct": 1.0},
            {"symbol": "Y", "side": "SHORT", "confidence": "Medium",
             "tp1": 2.0, "stop_loss": 2.2, "outcome": "LOSS", "pnl_pct": -0.5},
        ]
        msg = format_daily_digest(signals)
        assert "Total signals today: 2" in msg


class TestDescribeMode:
    def test_known_modes_have_labels(self) -> None:
        assert "All" in describe_mode("all") or "🔔" in describe_mode("all")
        assert "HIGH" in describe_mode("high_only") or "⭐" in describe_mode("high_only")
        assert "Digest" in describe_mode("digest") or "📋" in describe_mode("digest")

    def test_unknown_mode_returns_itself(self) -> None:
        assert describe_mode("unknown_xyz") == "unknown_xyz"
