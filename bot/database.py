"""
Database layer — SQLite with WAL mode for concurrent-safe persistence.
Replaces flat JSON files (signals.json, dashboard.json) with proper tables.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

_DB_PATH: str = "360eye.db"


def get_db_path() -> str:
    return _DB_PATH


def set_db_path(path: str) -> None:
    global _DB_PATH
    _DB_PATH = path


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence TEXT NOT NULL,
                entry_low REAL NOT NULL,
                entry_high REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                tp3 REAL NOT NULL,
                stop_loss REAL NOT NULL,
                structure_note TEXT,
                context_note TEXT,
                leverage_min INTEGER,
                leverage_max INTEGER,
                opened_at REAL NOT NULL,
                closed_at REAL,
                be_triggered INTEGER DEFAULT 0,
                closed INTEGER DEFAULT 0,
                close_reason TEXT,
                created_by TEXT DEFAULT 'manual',
                confluence_gates_json TEXT
            );

            CREATE TABLE IF NOT EXISTS trade_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                tp3 REAL NOT NULL,
                opened_at REAL NOT NULL,
                closed_at REAL,
                outcome TEXT NOT NULL,
                pnl_pct REAL NOT NULL,
                timeframe TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriber_preferences (
                user_id    INTEGER PRIMARY KEY,
                mode       TEXT    NOT NULL DEFAULT 'all',
                updated_at REAL    NOT NULL
            );
        """)
    logger.info("Database initialised at %s", _DB_PATH)


def migrate_from_json(signals_file: str = "signals.json", dashboard_file: str = "dashboard.json") -> None:
    """
    One-time migration: if old JSON files exist, import them into the DB,
    then rename them to *.archived so they are not re-imported.
    """
    signals_path = Path(signals_file)
    dashboard_path = Path(dashboard_file)

    if signals_path.exists():
        try:
            raw = json.loads(signals_path.read_text(encoding="utf-8"))
            with _get_conn() as conn:
                for d in raw:
                    r = d.get("result", d)
                    conn.execute(
                        """INSERT OR IGNORE INTO signals
                           (id, symbol, side, confidence, entry_low, entry_high,
                            tp1, tp2, tp3, stop_loss, structure_note, context_note,
                            leverage_min, leverage_max, opened_at, closed_at,
                            be_triggered, closed, close_reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            d.get("id", f"MIGRATED-{time.time_ns()}"),
                            r.get("symbol", ""),
                            r.get("side", ""),
                            r.get("confidence", ""),
                            r.get("entry_low", 0.0),
                            r.get("entry_high", 0.0),
                            r.get("tp1", 0.0),
                            r.get("tp2", 0.0),
                            r.get("tp3", 0.0),
                            r.get("stop_loss", 0.0),
                            r.get("structure_note", ""),
                            r.get("context_note", ""),
                            r.get("leverage_min", 10),
                            r.get("leverage_max", 20),
                            d.get("opened_at", time.time()),
                            d.get("closed_at"),
                            int(d.get("be_triggered", False)),
                            int(d.get("closed", False)),
                            d.get("close_reason"),
                        ),
                    )
            signals_path.rename(signals_path.with_suffix(".json.archived"))
            logger.info("Migrated %d signals from %s", len(raw), signals_file)
        except Exception as exc:
            logger.warning("Signal migration failed: %s", exc)

    if dashboard_path.exists():
        try:
            raw = json.loads(dashboard_path.read_text(encoding="utf-8"))
            with _get_conn() as conn:
                for r in raw:
                    conn.execute(
                        """INSERT INTO trade_results
                           (symbol, side, entry_price, exit_price, stop_loss,
                            tp1, tp2, tp3, opened_at, closed_at, outcome, pnl_pct, timeframe)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            r.get("symbol", ""),
                            r.get("side", ""),
                            r.get("entry_price", 0.0),
                            r.get("exit_price"),
                            r.get("stop_loss", 0.0),
                            r.get("tp1", 0.0),
                            r.get("tp2", 0.0),
                            r.get("tp3", 0.0),
                            r.get("opened_at", time.time()),
                            r.get("closed_at"),
                            r.get("outcome", ""),
                            r.get("pnl_pct", 0.0),
                            r.get("timeframe", "5m"),
                        ),
                    )
            dashboard_path.rename(dashboard_path.with_suffix(".json.archived"))
            logger.info("Migrated %d trade results from %s", len(raw), dashboard_file)
        except Exception as exc:
            logger.warning("Dashboard migration failed: %s", exc)
