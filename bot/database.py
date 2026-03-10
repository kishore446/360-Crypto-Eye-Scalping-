"""
Database layer — SQLite with WAL mode for concurrent-safe persistence.
Replaces flat JSON files (signals.json, dashboard.json) with proper tables.

Connection pooling uses thread-local storage so each OS thread gets its own
persistent ``sqlite3.Connection``, avoiding the overhead of opening and closing
a new connection on every operation while remaining thread-safe.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

try:
    from config import DB_PATH as _DB_PATH
except ImportError:
    _DB_PATH: str = "data/360eye.db"

# Thread-local storage for per-thread connection pooling
_local = threading.local()

# Guard so init_db() only runs the heavy DDL once per process lifetime.
# _last_initialized_path tracks which DB path was last initialized so that
# switching databases (e.g. in tests via monkeypatch) triggers re-initialization.
_db_initialized: bool = False
_last_initialized_path: str = ""
_init_lock = threading.Lock()


def get_db_path() -> str:
    return _DB_PATH


def set_db_path(path: str) -> None:
    """Update the database path and invalidate the process-level init flag."""
    global _DB_PATH, _db_initialized, _last_initialized_path
    _DB_PATH = path
    # Reset so init_db() will re-create tables in the new database
    _db_initialized = False
    _last_initialized_path = ""
    # Discard any cached connections pointing at the old path
    close_all_connections()


def _get_conn_pooled() -> sqlite3.Connection:
    """Return the thread-local persistent connection, creating it if necessary.

    If the module-level ``_DB_PATH`` has changed since the connection was
    opened (e.g. during tests or after ``set_db_path()``), the stale
    connection is closed and a new one is created pointing at the current path.

    The connection is configured once with WAL mode, NORMAL synchronous writes,
    a 64 MB page cache, and ``sqlite3.Row`` as the row factory so callers can
    access columns by name.
    """
    conn_path = getattr(_local, "conn_path", None)
    if conn_path != _DB_PATH:
        # Path changed — discard the stale connection and open a fresh one
        old_conn = getattr(_local, "conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:  # noqa: BLE001
                pass
        _local.conn = None
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA cache_size=-64000")  # 64 MB cache
        _local.conn.row_factory = sqlite3.Row
        _local.conn_path = _DB_PATH
    return _local.conn


def close_all_connections() -> None:
    """Close and discard the current thread's pooled connection.

    Call this at process shutdown or after ``set_db_path()`` to ensure clean
    resource release.  Other threads' connections are not affected; each
    thread is responsible for its own connection lifecycle.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        _local.conn = None


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that wraps the pooled connection in a savepoint transaction.

    On exit the transaction is committed; on exception it is rolled back.  The
    underlying connection is *not* closed — it is returned to the pool.
    """
    conn = _get_conn_pooled()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Create tables if they don't exist.  Safe to call multiple times — after
    the first successful run the function returns immediately without touching
    the database."""
    global _db_initialized, _last_initialized_path
    with _init_lock:
        if _db_initialized and _last_initialized_path == _DB_PATH:
            return
        _do_init_db()
        _db_initialized = True
        _last_initialized_path = _DB_PATH


def _do_init_db() -> None:
    """Internal: actually execute the DDL statements.  Must be called under ``_init_lock``."""
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

            CREATE TABLE IF NOT EXISTS signals_archived (
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
        """)

        # Add new columns if they don't already exist (safe migration)
        for col_def in (
            "ALTER TABLE signals ADD COLUMN origin_channel INTEGER DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN confluence_score INTEGER DEFAULT 0",
            "ALTER TABLE signals_archived ADD COLUMN origin_channel INTEGER DEFAULT 0",
            "ALTER TABLE signals_archived ADD COLUMN confluence_score INTEGER DEFAULT 0",
        ):
            try:
                conn.execute(col_def)
            except Exception:
                pass  # Column already exists — ignore

        # Performance indexes
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_signals_closed
                ON signals(closed, closed_at);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol
                ON signals(symbol);
            CREATE INDEX IF NOT EXISTS idx_signals_side
                ON signals(side, closed);
            CREATE INDEX IF NOT EXISTS idx_trade_results_outcome
                ON trade_results(outcome, closed_at);
            CREATE INDEX IF NOT EXISTS idx_trade_results_symbol
                ON trade_results(symbol);
            CREATE INDEX IF NOT EXISTS idx_signals_opened_at
                ON signals(opened_at);
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


def archive_old_signals(days: int = 90) -> int:
    """
    Move closed signals older than *days* days to the ``signals_archived`` table,
    delete the originals, and run VACUUM to reclaim space.

    Parameters
    ----------
    days:
        Age threshold in days. Closed signals with ``closed_at`` older than
        this are moved to the archive. Default is 90.

    Returns
    -------
    int
        Number of signals archived in this call (newly inserted rows only).
    """
    cutoff = time.time() - days * 86400
    archived_count = 0
    with _get_conn() as conn:
        # Count eligible rows before insertion to get accurate newly-archived count
        count_row = conn.execute(
            """SELECT COUNT(*) FROM signals
               WHERE closed = 1 AND closed_at IS NOT NULL AND closed_at < ?""",
            (cutoff,),
        ).fetchone()
        archived_count = count_row[0] if count_row else 0
        # Copy qualifying rows to archive (ignore duplicates from prior runs)
        conn.execute(
            """
            INSERT OR IGNORE INTO signals_archived
            SELECT * FROM signals
            WHERE closed = 1 AND closed_at IS NOT NULL AND closed_at < ?
            """,
            (cutoff,),
        )
        # Delete originals
        conn.execute(
            "DELETE FROM signals WHERE closed = 1 AND closed_at IS NOT NULL AND closed_at < ?",
            (cutoff,),
        )
    # VACUUM outside a transaction
    vacuum_conn = None
    try:
        vacuum_conn = __import__("sqlite3").connect(_DB_PATH)
        vacuum_conn.execute("VACUUM")
        vacuum_conn.close()
    except Exception as exc:
        logger.warning("VACUUM failed after archiving: %s", exc)
        if vacuum_conn is not None:
            try:
                vacuum_conn.close()
            except Exception:
                pass
    logger.info("Archived %d signals older than %d days.", archived_count, days)
    return archived_count


# ── Signal CRUD helpers ────────────────────────────────────────────────────


def save_signal(signal_data: dict) -> None:
    """Upsert a signal into the signals table."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals
                (id, symbol, side, confidence, entry_low, entry_high,
                 tp1, tp2, tp3, stop_loss, structure_note, context_note,
                 leverage_min, leverage_max, opened_at, closed_at,
                 be_triggered, closed, close_reason, created_by,
                 confluence_gates_json, origin_channel, confluence_score)
            VALUES
                (:id, :symbol, :side, :confidence, :entry_low, :entry_high,
                 :tp1, :tp2, :tp3, :stop_loss, :structure_note, :context_note,
                 :leverage_min, :leverage_max, :opened_at, :closed_at,
                 :be_triggered, :closed, :close_reason, :created_by,
                 :confluence_gates_json, :origin_channel, :confluence_score)
            """,
            {
                "id": signal_data.get("id", ""),
                "symbol": signal_data.get("symbol", ""),
                "side": signal_data.get("side", ""),
                "confidence": signal_data.get("confidence", ""),
                "entry_low": signal_data.get("entry_low", 0.0),
                "entry_high": signal_data.get("entry_high", 0.0),
                "tp1": signal_data.get("tp1", 0.0),
                "tp2": signal_data.get("tp2", 0.0),
                "tp3": signal_data.get("tp3", 0.0),
                "stop_loss": signal_data.get("stop_loss", 0.0),
                "structure_note": signal_data.get("structure_note"),
                "context_note": signal_data.get("context_note"),
                "leverage_min": signal_data.get("leverage_min"),
                "leverage_max": signal_data.get("leverage_max"),
                "opened_at": signal_data.get("opened_at", time.time()),
                "closed_at": signal_data.get("closed_at"),
                "be_triggered": int(signal_data.get("be_triggered", False)),
                "closed": int(signal_data.get("closed", False)),
                "close_reason": signal_data.get("close_reason"),
                "created_by": signal_data.get("created_by", "scanner"),
                "confluence_gates_json": signal_data.get("confluence_gates_json"),
                "origin_channel": signal_data.get("origin_channel", 0),
                "confluence_score": signal_data.get("confluence_score", 0),
            },
        )


def load_active_signals() -> list[dict]:
    """Load all non-closed signals from the signals table."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE closed = 0 ORDER BY opened_at ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def update_signal(signal_id: str, updates: dict) -> None:
    """Update one or more fields on an existing signal row.

    Parameters
    ----------
    signal_id:
        The ``id`` of the signal to update.
    updates:
        Mapping of column name → new value. Only whitelisted column names are accepted.
    """
    if not updates:
        return
    # Whitelist of updatable columns to prevent SQL injection
    _UPDATABLE_COLUMNS = frozenset({
        "closed", "closed_at", "close_reason", "be_triggered",
        "origin_channel", "confluence_score", "confluence_gates_json",
        "created_by", "tp1_hit", "tp2_hit", "tp3_hit",
    })
    safe_updates = {k: v for k, v in updates.items() if k in _UPDATABLE_COLUMNS}
    if not safe_updates:
        logger.warning("update_signal: no valid columns in updates %s", list(updates.keys()))
        return
    set_clause = ", ".join(f"{col} = ?" for col in safe_updates)
    values = list(safe_updates.values()) + [signal_id]
    with _get_conn() as conn:
        conn.execute(f"UPDATE signals SET {set_clause} WHERE id = ?", values)  # noqa: S608
