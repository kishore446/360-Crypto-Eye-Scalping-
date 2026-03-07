"""
Tests for DB maintenance features in bot/database.py
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from bot.database import archive_old_signals, init_db, set_db_path

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a fresh temporary SQLite database for each test."""
    db_path = str(tmp_path / "test_360eye.db")
    set_db_path(db_path)
    init_db()
    yield db_path
    set_db_path("360eye.db")  # Reset to default after test


def _insert_signal(db_path: str, signal_id: str, closed: int, closed_at: float | None) -> None:
    """Helper to insert a signal row directly."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR IGNORE INTO signals
           (id, symbol, side, confidence, entry_low, entry_high,
            tp1, tp2, tp3, stop_loss, opened_at, closed, closed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            signal_id, "BTC", "LONG", "HIGH",
            99.0, 101.0, 105.0, 110.0, 120.0, 95.0,
            time.time() - 100 * 86400,
            closed, closed_at,
        ),
    )
    conn.commit()
    conn.close()


# ── init_db table creation ────────────────────────────────────────────────────


class TestInitDb:
    def test_creates_signals_table(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "signals" in table_names

    def test_creates_signals_archived_table(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "signals_archived" in table_names

    def test_creates_trade_results_table(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "trade_results" in table_names

    def test_signals_archived_has_same_columns_as_signals(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        signals_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()
        }
        archived_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(signals_archived)").fetchall()
        }
        conn.close()
        assert signals_cols == archived_cols


# ── archive_old_signals ───────────────────────────────────────────────────────


class TestArchiveOldSignals:
    def test_archives_old_closed_signals(self, tmp_db):
        old_closed_at = time.time() - 100 * 86400  # 100 days ago
        _insert_signal(tmp_db, "OLD-1", closed=1, closed_at=old_closed_at)
        _insert_signal(tmp_db, "OLD-2", closed=1, closed_at=old_closed_at)

        archived = archive_old_signals(days=90)

        assert archived >= 2
        conn = sqlite3.connect(tmp_db)
        remaining = conn.execute("SELECT COUNT(*) FROM signals WHERE id LIKE 'OLD-%'").fetchone()[0]
        in_archive = conn.execute("SELECT COUNT(*) FROM signals_archived WHERE id LIKE 'OLD-%'").fetchone()[0]
        conn.close()
        assert remaining == 0
        assert in_archive >= 2

    def test_does_not_archive_recent_signals(self, tmp_db):
        recent_closed_at = time.time() - 5 * 86400  # only 5 days ago
        _insert_signal(tmp_db, "RECENT-1", closed=1, closed_at=recent_closed_at)

        archive_old_signals(days=90)

        conn = sqlite3.connect(tmp_db)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE id = 'RECENT-1'"
        ).fetchone()[0]
        conn.close()
        assert remaining == 1

    def test_does_not_archive_open_signals(self, tmp_db):
        old_time = time.time() - 100 * 86400
        _insert_signal(tmp_db, "OPEN-1", closed=0, closed_at=old_time)

        archive_old_signals(days=90)

        conn = sqlite3.connect(tmp_db)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE id = 'OPEN-1'"
        ).fetchone()[0]
        conn.close()
        assert remaining == 1

    def test_returns_correct_count(self, tmp_db):
        old_closed_at = time.time() - 100 * 86400
        _insert_signal(tmp_db, "CNT-1", closed=1, closed_at=old_closed_at)
        _insert_signal(tmp_db, "CNT-2", closed=1, closed_at=old_closed_at)
        _insert_signal(tmp_db, "CNT-3", closed=1, closed_at=old_closed_at)

        archived = archive_old_signals(days=90)

        assert archived >= 3

    def test_empty_db_returns_zero(self, tmp_db):
        archived = archive_old_signals(days=90)
        assert archived == 0

    def test_idempotent_second_run(self, tmp_db):
        old_closed_at = time.time() - 100 * 86400
        _insert_signal(tmp_db, "IDEM-1", closed=1, closed_at=old_closed_at)

        archived1 = archive_old_signals(days=90)
        archive_old_signals(days=90)

        # Second run should not produce new archives for already-archived signals
        assert archived1 >= 1
        # Signals already gone from main table, so second run archives 0 new ones
        conn = sqlite3.connect(tmp_db)
        in_archive = conn.execute(
            "SELECT COUNT(*) FROM signals_archived WHERE id = 'IDEM-1'"
        ).fetchone()[0]
        conn.close()
        assert in_archive == 1
