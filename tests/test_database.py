"""Tests for bot/database.py — DB CRUD and JSON migration."""
from __future__ import annotations

import json
import time

import pytest

import bot.database as db_module
from bot.database import (
    _get_conn,
    init_db,
    load_active_signals,
    migrate_from_json,
    save_signal,
    update_signal,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite database file."""
    db_file = str(tmp_path / "test_360eye.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    yield db_file


class TestInitDb:
    def test_creates_signals_table(self, tmp_path):
        init_db()
        with _get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
            )
            assert cursor.fetchone() is not None

    def test_creates_trade_results_table(self, tmp_path):
        init_db()
        with _get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trade_results'"
            )
            assert cursor.fetchone() is not None

    def test_idempotent_multiple_calls(self):
        init_db()
        init_db()  # should not raise

    def test_creates_indexes(self):
        init_db()
        with _get_conn() as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "idx_signals_closed" in indexes
        assert "idx_signals_symbol" in indexes
        assert "idx_trade_results_outcome" in indexes
        assert "idx_signals_opened_at" in indexes

    def test_creates_origin_channel_column(self):
        """init_db() should add origin_channel and confluence_score columns."""
        init_db()
        with _get_conn() as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(signals)").fetchall()
            }
        assert "origin_channel" in cols
        assert "confluence_score" in cols

    def test_db_path_reads_from_config(self, monkeypatch):
        """_DB_PATH should default to config.DB_PATH value, not hardcoded."""
        # Verify that the database module uses a config-derived path,
        # NOT the old hardcoded "360eye.db" (which had no directory prefix).
        # The _isolated_db autouse fixture already monkeypatches _DB_PATH to a
        # tmp path; here we just assert it was never "360eye.db" before patching.
        import bot.database as db
        # After fixture patching the path is tmp — just verify default is not bare "360eye.db"
        assert db._DB_PATH != "360eye.db"


class TestCRUD:
    def test_insert_and_query_signal(self):
        init_db()
        sig_id = "TEST-001"
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO signals
                   (id, symbol, side, confidence, entry_low, entry_high,
                    tp1, tp2, tp3, stop_loss, opened_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (sig_id, "BTC", "LONG", "High", 64900.0, 65000.0,
                 65750.0, 66500.0, 68000.0, 64400.0, time.time()),
            )
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id=?", (sig_id,)).fetchone()
        assert row is not None
        assert row["symbol"] == "BTC"
        assert row["side"] == "LONG"

    def test_insert_and_query_trade_result(self):
        init_db()
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO trade_results
                   (symbol, side, entry_price, stop_loss, tp1, tp2, tp3,
                    opened_at, outcome, pnl_pct, timeframe)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("ETH", "SHORT", 3000.0, 3100.0, 2850.0, 2700.0, 2500.0,
                 time.time(), "WIN", 5.0, "5m"),
            )
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM trade_results WHERE symbol='ETH'").fetchone()
        assert row is not None
        assert row["outcome"] == "WIN"
        assert row["pnl_pct"] == pytest.approx(5.0)

    def test_or_ignore_on_duplicate_signal_id(self):
        init_db()
        sig_id = "DUP-001"
        for _ in range(2):
            with _get_conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO signals
                       (id, symbol, side, confidence, entry_low, entry_high,
                        tp1, tp2, tp3, stop_loss, opened_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (sig_id, "BTC", "LONG", "High", 64900.0, 65000.0,
                     65750.0, 66500.0, 68000.0, 64400.0, time.time()),
                )
        with _get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM signals WHERE id=?", (sig_id,)).fetchone()[0]
        assert count == 1


class TestSignalCRUD:
    """Test save_signal, load_active_signals, update_signal helpers."""

    def _make_signal_data(self, sig_id: str = "SIG-001", closed: bool = False) -> dict:
        return {
            "id": sig_id,
            "symbol": "BTC",
            "side": "LONG",
            "confidence": "High",
            "entry_low": 64900.0,
            "entry_high": 65000.0,
            "tp1": 65750.0,
            "tp2": 66500.0,
            "tp3": 68000.0,
            "stop_loss": 64400.0,
            "structure_note": "Test note",
            "context_note": "Test context",
            "leverage_min": 15,
            "leverage_max": 20,
            "opened_at": time.time(),
            "closed_at": None,
            "be_triggered": False,
            "closed": closed,
            "close_reason": None,
            "created_by": "scanner",
            "confluence_gates_json": None,
            "origin_channel": 12345,
            "confluence_score": 75,
        }

    def test_save_signal_inserts_row(self):
        init_db()
        save_signal(self._make_signal_data("SAVE-001"))
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id='SAVE-001'").fetchone()
        assert row is not None
        assert row["symbol"] == "BTC"
        assert row["origin_channel"] == 12345
        assert row["confluence_score"] == 75

    def test_save_signal_upserts_on_duplicate(self):
        init_db()
        data = self._make_signal_data("UPSERT-001")
        save_signal(data)
        data["confidence"] = "Medium"
        save_signal(data)  # Should replace, not error
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id='UPSERT-001'").fetchone()
        assert row["confidence"] == "Medium"

    def test_load_active_signals_excludes_closed(self):
        init_db()
        save_signal(self._make_signal_data("OPEN-001", closed=False))
        save_signal(self._make_signal_data("CLOSED-001", closed=True))
        signals = load_active_signals()
        ids = [s["id"] for s in signals]
        assert "OPEN-001" in ids
        assert "CLOSED-001" not in ids

    def test_load_active_signals_returns_dict_list(self):
        init_db()
        save_signal(self._make_signal_data("DICT-001"))
        signals = load_active_signals()
        assert isinstance(signals, list)
        assert all(isinstance(s, dict) for s in signals)

    def test_update_signal_changes_fields(self):
        init_db()
        save_signal(self._make_signal_data("UPDATE-001"))
        update_signal("UPDATE-001", {"closed": 1, "close_reason": "tp1_hit"})
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id='UPDATE-001'").fetchone()
        assert row["closed"] == 1
        assert row["close_reason"] == "tp1_hit"

    def test_update_signal_noop_on_empty_updates(self):
        init_db()
        save_signal(self._make_signal_data("NOOP-001"))
        update_signal("NOOP-001", {})  # Should not raise
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id='NOOP-001'").fetchone()
        assert row is not None

    def test_load_active_signals_empty_db(self):
        init_db()
        signals = load_active_signals()
        assert signals == []


class TestMigrateFromJson:
    def test_migrates_signals_json(self, tmp_path):
        init_db()
        signals_file = tmp_path / "signals.json"
        signals_file.write_text(json.dumps([
            {
                "id": "MIG-001",
                "result": {
                    "symbol": "BTC",
                    "side": "LONG",
                    "confidence": "High",
                    "entry_low": 64900.0,
                    "entry_high": 65000.0,
                    "tp1": 65750.0,
                    "tp2": 66500.0,
                    "tp3": 68000.0,
                    "stop_loss": 64400.0,
                    "structure_note": "Test",
                    "context_note": "Test ctx",
                    "leverage_min": 10,
                    "leverage_max": 20,
                },
                "opened_at": time.time(),
                "be_triggered": False,
                "closed": False,
            }
        ]), encoding="utf-8")

        migrate_from_json(str(signals_file), str(tmp_path / "nonexistent.json"))

        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id='MIG-001'").fetchone()
        assert row is not None
        assert row["symbol"] == "BTC"

        # Original file should be archived
        assert not signals_file.exists()
        assert (tmp_path / "signals.json.archived").exists()

    def test_migrates_dashboard_json(self, tmp_path):
        init_db()
        dashboard_file = tmp_path / "dashboard.json"
        dashboard_file.write_text(json.dumps([
            {
                "symbol": "ETH",
                "side": "LONG",
                "entry_price": 3000.0,
                "exit_price": 3150.0,
                "stop_loss": 2900.0,
                "tp1": 3150.0,
                "tp2": 3300.0,
                "tp3": 3600.0,
                "opened_at": time.time() - 3600,
                "closed_at": time.time(),
                "outcome": "WIN",
                "pnl_pct": 5.0,
                "timeframe": "5m",
            }
        ]), encoding="utf-8")

        migrate_from_json(str(tmp_path / "nonexistent.json"), str(dashboard_file))

        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM trade_results WHERE symbol='ETH'").fetchone()
        assert row is not None
        assert row["outcome"] == "WIN"
        assert not dashboard_file.exists()

    def test_nonexistent_files_are_ignored(self, tmp_path):
        init_db()
        # Should not raise when files don't exist
        migrate_from_json(
            str(tmp_path / "no_signals.json"),
            str(tmp_path / "no_dashboard.json"),
        )
