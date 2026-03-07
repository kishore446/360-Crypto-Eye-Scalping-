"""
Tests for bot/gate_stats.py
"""
from __future__ import annotations

import json
import time

import pytest

import bot.database as db_module
from bot.database import init_db, _get_conn
from bot.gate_stats import (
    format_gate_stats_line,
    get_gate_combo_stats,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite database."""
    db_file = str(tmp_path / "test_gate.db")
    monkeypatch.setattr(db_module, "_DB_PATH", db_file)
    init_db()
    yield db_file


def _insert_signal(
    conn,
    sig_id: str,
    symbol: str = "BTC",
    side: str = "LONG",
    gates: list[str] | None = None,
    opened_at: float | None = None,
    closed: int = 1,
    close_reason: str | None = None,
    tp2: float = 61_000.0,
) -> None:
    if gates is None:
        gates = ["macro_bias", "zone", "liquidity_sweep", "mss"]
    if opened_at is None:
        opened_at = time.time() - 3600
    gates_json = json.dumps(sorted(gates))
    conn.execute(
        """
        INSERT INTO signals
            (id, symbol, side, confidence, entry_low, entry_high,
             tp1, tp2, tp3, stop_loss, opened_at, closed, close_reason, confluence_gates_json)
        VALUES (?, ?, ?, 'High', 60000, 60100, 60500, ?, 62000, 59500, ?, ?, ?, ?)
        """,
        (sig_id, symbol, side, tp2, opened_at, closed, close_reason, gates_json),
    )


class TestGetGateComboStats:
    def test_empty_gates_returns_zeroed_dict(self) -> None:
        result = get_gate_combo_stats([])
        assert result == {"total": 0, "tp2_hits": 0, "win_rate_pct": 0.0}

    def test_no_matching_signals_returns_zeroed_dict(self) -> None:
        result = get_gate_combo_stats(["macro_bias", "zone"])
        assert result["total"] == 0

    def test_counts_tp2_hits_from_close_reason(self) -> None:
        gates = ["macro_bias", "zone", "liquidity_sweep", "mss"]
        with _get_conn() as conn:
            _insert_signal(conn, "S1", gates=gates, close_reason="tp2")
            _insert_signal(conn, "S2", gates=gates, close_reason="tp3")
            _insert_signal(conn, "S3", gates=gates, close_reason="sl")

        result = get_gate_combo_stats(gates)
        assert result["total"] == 3
        assert result["tp2_hits"] == 2
        assert result["win_rate_pct"] == pytest.approx(66.67, rel=0.01)

    def test_gate_order_does_not_matter(self) -> None:
        gates = ["zone", "mss", "macro_bias", "liquidity_sweep"]
        gates_reversed = list(reversed(gates))
        with _get_conn() as conn:
            _insert_signal(conn, "T1", gates=gates, close_reason="tp3")
            _insert_signal(conn, "T2", gates=gates, close_reason="tp3")
            _insert_signal(conn, "T3", gates=gates, close_reason="tp3")

        r1 = get_gate_combo_stats(gates)
        r2 = get_gate_combo_stats(gates_reversed)
        assert r1["total"] == r2["total"]
        assert r1["tp2_hits"] == r2["tp2_hits"]

    def test_respects_lookback_days(self) -> None:
        gates = ["macro_bias", "zone", "mss"]
        old_time = time.time() - 100 * 86_400  # 100 days ago
        with _get_conn() as conn:
            _insert_signal(conn, "OLD1", gates=gates, opened_at=old_time, close_reason="tp3")
            _insert_signal(conn, "OLD2", gates=gates, opened_at=old_time, close_reason="tp3")
            _insert_signal(conn, "OLD3", gates=gates, opened_at=old_time, close_reason="tp3")

        result = get_gate_combo_stats(gates, lookback_days=30)
        # All trades are older than 30 days, so should not appear
        assert result["total"] == 0

    def test_only_counts_closed_signals(self) -> None:
        gates = ["macro_bias", "fvg"]
        with _get_conn() as conn:
            _insert_signal(conn, "X1", gates=gates, closed=0, close_reason=None)
            _insert_signal(conn, "X2", gates=gates, closed=1, close_reason="tp2")
            _insert_signal(conn, "X3", gates=gates, closed=1, close_reason="tp3")

        result = get_gate_combo_stats(gates)
        assert result["total"] == 2  # X1 (open) excluded
        assert result["tp2_hits"] == 2

    def test_no_close_reason_not_counted_as_tp2(self) -> None:
        gates = ["macro_bias", "zone"]
        with _get_conn() as conn:
            _insert_signal(conn, "N1", gates=gates, closed=1, close_reason=None)
            _insert_signal(conn, "N2", gates=gates, closed=1, close_reason="stale")
            _insert_signal(conn, "N3", gates=gates, closed=1, close_reason="sl")

        result = get_gate_combo_stats(gates)
        assert result["total"] == 3
        assert result["tp2_hits"] == 0
        assert result["win_rate_pct"] == 0.0


class TestFormatGateStatsLine:
    def test_returns_empty_string_when_fewer_than_5_samples(self) -> None:
        gates = ["a", "b", "c"]
        with _get_conn() as conn:
            for i in range(4):
                _insert_signal(conn, f"G{i}", gates=gates, close_reason="tp2")

        result = format_gate_stats_line(gates)
        assert result == ""

    def test_returns_formatted_line_when_enough_data(self) -> None:
        gates = ["macro_bias", "zone", "mss", "fvg"]
        with _get_conn() as conn:
            for i in range(7):
                _insert_signal(conn, f"H{i}", gates=gates, close_reason="tp3")

        result = format_gate_stats_line(gates)
        assert "TP2+" in result
        assert "signals" in result

    def test_returns_empty_string_for_empty_gates(self) -> None:
        assert format_gate_stats_line([]) == ""

    def test_win_rate_percentage_in_output(self) -> None:
        gates = ["macro_bias", "zone", "mss"]
        with _get_conn() as conn:
            for i in range(5):
                _insert_signal(conn, f"P{i}", gates=gates, close_reason="tp3")

        result = format_gate_stats_line(gates)
        assert "100%" in result
