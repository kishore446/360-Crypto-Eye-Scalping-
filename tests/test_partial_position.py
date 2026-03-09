"""
Tests for bot/partial_position.py — Partial Close Simulation (Part B)
"""
from __future__ import annotations

import json

import pytest

from bot.partial_position import PartialPosition


class TestPartialPositionBasics:
    def test_initial_remaining_pct(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        assert pp.remaining_pct() == pytest.approx(1.0)

    def test_no_exits_composite_pnl_is_zero(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        assert pp.composite_pnl() == 0.0

    def test_has_exits_false_initially(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        assert pp.has_exits() is False

    def test_exit_count_zero_initially(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        assert pp.exit_count() == 0


class TestPartialPositionTP1Exit:
    def test_tp1_exit_records_50_pct(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        assert pp.exit_count() == 1
        assert pp.remaining_pct() == pytest.approx(0.50)

    def test_tp1_exit_pnl(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        # 50% closed at +2%, remaining 50% not yet closed
        assert pp.composite_pnl() == pytest.approx(2.0, rel=1e-3)

    def test_tp1_exit_marks_tp1_done(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        assert pp._tp1_done is True


class TestCompositeMultiExit:
    def test_tp1_then_tp2_composite_pnl(self):
        """
        50% at TP1 (+2%), 25% at TP2 (+4%), remaining 25% at BE (0%).
        Composite should weight correctly.
        """
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)   # 50% at +2%
        pp.add_exit("TP2", exit_price=104.0, entry_price=100.0)   # 25% at +4%
        pp.add_exit("BE", exit_price=100.0, entry_price=100.0)    # 25% at 0%
        # composite = (0.50*2 + 0.25*4 + 0.25*0) / (0.50+0.25+0.25) = 2.0
        assert pp.composite_pnl() == pytest.approx(2.0, rel=1e-3)

    def test_tp1_tp2_tp3_composite_pnl(self):
        """50% at +2%, 25% at +4%, 25% at +8%."""
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        pp.add_exit("TP2", exit_price=104.0, entry_price=100.0)
        pp.add_exit("TP3", exit_price=108.0, entry_price=100.0)
        # composite = (0.50*2 + 0.25*4 + 0.25*8) / 1.0 = 4.0
        assert pp.composite_pnl() == pytest.approx(4.0, rel=1e-3)

    def test_sl_after_tp1_composite_pnl(self):
        """50% at TP1 (+2%), remaining 50% stopped at -1%."""
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)   # 50% at +2%
        pp.add_exit("SL", exit_price=99.0, entry_price=100.0)     # 50% at -1%
        # composite = (0.50*2 + 0.50*(-1)) / 1.0 = 0.5
        assert pp.composite_pnl() == pytest.approx(0.5, rel=1e-3)

    def test_remaining_pct_after_multiple_exits(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        assert pp.remaining_pct() == pytest.approx(0.50)
        pp.add_exit("TP2", exit_price=104.0, entry_price=100.0)
        assert pp.remaining_pct() == pytest.approx(0.25)


class TestPartialPositionSerialization:
    def test_to_json_structure(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        raw = json.loads(pp.to_json())
        assert len(raw) == 1
        assert raw[0]["level"] == "TP1"
        assert raw[0]["pct"] == pytest.approx(50.0)
        assert raw[0]["pnl"] == pytest.approx(2.0, rel=1e-3)

    def test_to_json_empty(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        raw = json.loads(pp.to_json())
        assert raw == []


class TestFormatExitBreakdown:
    def test_breakdown_single_exit(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        breakdown = pp.format_exit_breakdown(side="LONG")
        assert "TP1" in breakdown
        assert "50%" in breakdown
        assert "+2.00%" in breakdown

    def test_breakdown_multi_exit(self):
        pp = PartialPosition(signal_id="sig-001", entry_price=100.0)
        pp.add_exit("TP1", exit_price=102.0, entry_price=100.0)
        pp.add_exit("TP2", exit_price=104.0, entry_price=100.0)
        breakdown = pp.format_exit_breakdown(side="LONG")
        assert "Exit 1:" in breakdown
        assert "Exit 2:" in breakdown
