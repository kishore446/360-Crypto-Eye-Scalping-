"""Tests for bot/database.py — archive_old_signals() and signals_archived table."""
from __future__ import annotations

import time

import pytest

import bot.database as db_module
from bot.database import (
    _get_conn,
    archive_old_signals,
    init_db,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite database file."""
    db_file = str(tmp_path / "test_maintenance.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    yield db_file


def _insert_signal(conn, sig_id: str, closed: int, closed_at: float | None) -> None:
    conn.execute(
        """INSERT INTO signals
           (id, symbol, side, confidence, entry_low, entry_high,
            tp1, tp2, tp3, stop_loss, opened_at, closed, closed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sig_id, "BTC", "LONG", "High",
            64900.0, 65000.0, 65750.0, 66500.0, 68000.0, 64400.0,
            time.time() - 200 * 86400,  # opened 200 days ago
            closed, closed_at,
        ),
    )


class TestSignalsArchivedTable:
    def test_table_created_on_init(self):
        init_db()
        with _get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signals_archived'"
            )
            assert cursor.fetchone() is not None

    def test_archived_table_same_schema(self):
        init_db()
        with _get_conn() as conn:
            # Both tables should have an 'id' column
            cols_active = {
                row[1] for row in conn.execute("PRAGMA table_info(signals)")
            }
            cols_archived = {
                row[1] for row in conn.execute("PRAGMA table_info(signals_archived)")
            }
        assert cols_active == cols_archived


class TestArchiveOldSignals:
    def test_archives_old_closed_signals(self):
        init_db()
        old_closed_at = time.time() - 100 * 86400  # 100 days ago
        with _get_conn() as conn:
            _insert_signal(conn, "OLD-001", closed=1, closed_at=old_closed_at)

        count = archive_old_signals(days=90)
        assert count == 1

        # Signal should be gone from 'signals'
        with _get_conn() as conn:
            row = conn.execute("SELECT id FROM signals WHERE id='OLD-001'").fetchone()
            assert row is None
            # Signal should be in 'signals_archived'
            archived = conn.execute(
                "SELECT id FROM signals_archived WHERE id='OLD-001'"
            ).fetchone()
            assert archived is not None

    def test_does_not_archive_recent_signals(self):
        init_db()
        recent_closed_at = time.time() - 5 * 86400  # 5 days ago
        with _get_conn() as conn:
            _insert_signal(conn, "RECENT-001", closed=1, closed_at=recent_closed_at)

        count = archive_old_signals(days=90)
        assert count == 0

        with _get_conn() as conn:
            row = conn.execute("SELECT id FROM signals WHERE id='RECENT-001'").fetchone()
            assert row is not None

    def test_does_not_archive_open_signals(self):
        init_db()
        with _get_conn() as conn:
            _insert_signal(conn, "OPEN-001", closed=0, closed_at=None)

        count = archive_old_signals(days=90)
        assert count == 0

        with _get_conn() as conn:
            row = conn.execute("SELECT id FROM signals WHERE id='OPEN-001'").fetchone()
            assert row is not None

    def test_returns_correct_count(self):
        init_db()
        old_closed_at = time.time() - 100 * 86400
        with _get_conn() as conn:
            for i in range(5):
                _insert_signal(conn, f"OLD-{i:03d}", closed=1, closed_at=old_closed_at)
            # Add one recent — should NOT be archived
            _insert_signal(conn, "RECENT-001", closed=1, closed_at=time.time() - 5 * 86400)

        count = archive_old_signals(days=90)
        assert count == 5

    def test_idempotent_second_call(self):
        init_db()
        old_closed_at = time.time() - 100 * 86400
        with _get_conn() as conn:
            _insert_signal(conn, "OLD-001", closed=1, closed_at=old_closed_at)

        first = archive_old_signals(days=90)
        second = archive_old_signals(days=90)

        assert first == 1
        assert second == 0  # already archived; nothing left to archive

    def test_custom_days_threshold(self):
        init_db()
        # 30-day-old signal
        closed_at_30d = time.time() - 30 * 86400
        with _get_conn() as conn:
            _insert_signal(conn, "MID-001", closed=1, closed_at=closed_at_30d)

        # With 90-day threshold: not archived
        count_90 = archive_old_signals(days=90)
        assert count_90 == 0

        # With 20-day threshold: archived
        count_20 = archive_old_signals(days=20)
        assert count_20 == 1
