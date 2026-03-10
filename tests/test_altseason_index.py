"""Tests for bot/insights/altseason_index.py"""
from __future__ import annotations

import pytest

from bot.insights.altseason_index import (
    calculate_altseason_score,
    format_altseason_index,
    get_target_channel_id,
)


class TestCalculateAltseasonScore:
    def test_neutral_returns_50(self):
        score = calculate_altseason_score(5.0, 5.0)
        assert score == pytest.approx(50.0)

    def test_alts_outperform_heavily(self):
        score = calculate_altseason_score(0.0, 20.0)
        assert score == pytest.approx(100.0)

    def test_btc_outperforms_heavily(self):
        score = calculate_altseason_score(20.0, 0.0)
        assert score == pytest.approx(0.0)

    def test_score_clamped_to_100(self):
        score = calculate_altseason_score(-50.0, 50.0)
        assert score == 100.0

    def test_score_clamped_to_0(self):
        score = calculate_altseason_score(50.0, -50.0)
        assert score == 0.0

    def test_alts_outperform_by_5pct(self):
        # diff = 8, score = (8+20)/40*100 = 70
        score = calculate_altseason_score(2.0, 10.0)
        assert score == pytest.approx(70.0)


class TestFormatAltseasonIndex:
    def test_contains_required_fields(self):
        msg = format_altseason_index(5.0, 10.0)
        assert "ALTSEASON INDEX" in msg
        assert "Score:" in msg
        assert "BTC 7d:" in msg
        assert "Alt avg 7d:" in msg
        assert "Spread:" in msg

    def test_altseason_heating_up_label(self):
        msg = format_altseason_index(0.0, 10.0)
        assert "Heating Up" in msg or "Altseason" in msg

    def test_btc_dominance_label(self):
        msg = format_altseason_index(15.0, 0.0)
        assert "BTC" in msg and ("Dominance" in msg or "dominance" in msg.lower())

    def test_bar_visualization_present(self):
        msg = format_altseason_index(5.0, 5.0)
        assert "[" in msg and "]" in msg

    def test_positive_btc_change_shown(self):
        msg = format_altseason_index(5.0, 5.0)
        assert "+5.0%" in msg

    def test_negative_btc_change_shown(self):
        msg = format_altseason_index(-3.0, 2.0)
        assert "-3.0%" in msg

    def test_altseason_note_when_alts_outperform(self):
        msg = format_altseason_index(0.0, 10.0)
        # diff > 5 → altseason note
        assert "5%" in msg or "outperform" in msg.lower() or "Heating" in msg


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
