"""
Tests for SQLite connection pooling and thread safety in bot/database.py
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

import bot.database as db_module
from bot.database import (
    _get_conn,
    _get_conn_pooled,
    close_all_connections,
    init_db,
    load_active_signals,
    save_signal,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own fresh SQLite database."""
    db_file = str(tmp_path / "test_pool.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    yield db_file
    close_all_connections()


class TestConnectionPooling:
    def test_returns_same_connection_within_thread(self):
        init_db()
        conn1 = _get_conn_pooled()
        conn2 = _get_conn_pooled()
        assert conn1 is conn2

    def test_connection_has_wal_mode(self):
        init_db()
        conn = _get_conn_pooled()
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_connection_has_row_factory(self):
        init_db()
        conn = _get_conn_pooled()
        assert conn.row_factory is sqlite3.Row

    def test_different_threads_get_different_connections(self):
        init_db()
        connections = []

        def capture():
            c = _get_conn_pooled()
            connections.append(c)

        t1 = threading.Thread(target=capture)
        t2 = threading.Thread(target=capture)
        t1.start()
        t1.join()
        t2.start()
        t2.join()

        assert len(connections) == 2
        # Each thread should get its own connection object
        assert connections[0] is not connections[1]

    def test_connection_reused_across_calls(self):
        """Connection must be reused (not closed and reopened) on every DB call."""
        init_db()
        conn_before = _get_conn_pooled()
        # Make a DB call
        save_signal({
            "id": "POOL-001",
            "symbol": "BTC",
            "side": "LONG",
            "confidence": "HIGH",
            "entry_low": 99.0,
            "entry_high": 101.0,
            "tp1": 110.0,
            "tp2": 120.0,
            "tp3": 130.0,
            "stop_loss": 90.0,
            "structure_note": "test",
            "context_note": "",
            "leverage_min": 10,
            "leverage_max": 20,
            "opened_at": time.time(),
            "closed_at": None,
            "be_triggered": False,
            "closed": False,
            "close_reason": None,
            "created_by": "test",
            "confluence_gates_json": None,
            "origin_channel": 0,
            "confluence_score": 0,
        })
        conn_after = _get_conn_pooled()
        assert conn_before is conn_after

    def test_path_change_creates_new_connection(self, tmp_path, monkeypatch):
        """After changing _DB_PATH the old connection must be discarded."""
        init_db()
        conn_old = _get_conn_pooled()

        new_path = str(tmp_path / "new_db.db")
        monkeypatch.setattr(db_module, "_DB_PATH", new_path)
        # Force re-init for new path
        init_db()
        conn_new = _get_conn_pooled()

        assert conn_new is not conn_old

    def test_close_all_connections_discards_connection(self):
        init_db()
        conn1 = _get_conn_pooled()
        close_all_connections()
        conn2 = _get_conn_pooled()
        # New connection should be a fresh object
        assert conn2 is not conn1


class TestInitDbIdempotent:
    def test_init_db_once_per_path(self, monkeypatch):
        """init_db() should only run DDL once per DB path."""
        init_db()
        flag_after_first = db_module._db_initialized
        assert flag_after_first is True

        # Second call — should be a no-op
        init_db()
        assert db_module._db_initialized is True

    def test_init_db_reruns_on_path_change(self, tmp_path, monkeypatch):
        """After the path changes, init_db() must re-create tables."""
        init_db()
        assert db_module._db_initialized is True

        new_path = str(tmp_path / "new2.db")
        monkeypatch.setattr(db_module, "_DB_PATH", new_path)
        # _db_initialized is still True but path differs
        init_db()
        # Tables must exist in new DB
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
            ).fetchone()
        assert row is not None


class TestThreadSafety:
    def test_concurrent_writes_do_not_corrupt(self, tmp_path, monkeypatch):
        """Multiple threads writing simultaneously must not corrupt the database."""
        db_file = str(tmp_path / "concurrent.db")
        monkeypatch.setattr(db_module, "_DB_PATH", db_file)
        init_db()

        errors = []

        def write(i: int):
            try:
                save_signal({
                    "id": f"THREAD-{i:04d}",
                    "symbol": f"COIN{i}",
                    "side": "LONG",
                    "confidence": "HIGH",
                    "entry_low": 99.0,
                    "entry_high": 101.0,
                    "tp1": 110.0,
                    "tp2": 120.0,
                    "tp3": 130.0,
                    "stop_loss": 90.0,
                    "structure_note": "",
                    "context_note": "",
                    "leverage_min": 10,
                    "leverage_max": 20,
                    "opened_at": time.time(),
                    "closed_at": None,
                    "be_triggered": False,
                    "closed": False,
                    "close_reason": None,
                    "created_by": "test",
                    "confluence_gates_json": None,
                    "origin_channel": 0,
                    "confluence_score": 0,
                })
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent write errors: {errors}"
        rows = load_active_signals()
        assert len(rows) == 20
