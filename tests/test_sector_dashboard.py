"""Tests for bot/insights/sector_dashboard.py"""
from __future__ import annotations

from bot.insights.sector_dashboard import (
    format_sector_dashboard,
    get_target_channel_id,
)


class TestFormatSectorDashboard:
    def test_empty_input(self):
        msg = format_sector_dashboard({})
        assert "No sector data" in msg

    def test_basic_output_contains_sectors(self):
        returns = {"DeFi": 10.5, "L2": -3.2, "Meme": 25.0, "AI": 5.0}
        msg = format_sector_dashboard(returns)
        assert "DeFi" in msg
        assert "L2" in msg
        assert "Meme" in msg
        assert "AI" in msg

    def test_sectors_ranked_by_return(self):
        returns = {"DeFi": 5.0, "Meme": 20.0, "AI": 10.0}
        msg = format_sector_dashboard(returns)
        # Meme (20%) should appear before DeFi (5%)
        assert msg.index("Meme") < msg.index("DeFi")

    def test_positive_returns_show_plus(self):
        returns = {"DeFi": 10.0}
        msg = format_sector_dashboard(returns)
        assert "+10.0%" in msg

    def test_negative_returns_show_minus(self):
        returns = {"L2": -5.5}
        msg = format_sector_dashboard(returns)
        assert "-5.5%" in msg

    def test_header_present(self):
        returns = {"DeFi": 5.0}
        msg = format_sector_dashboard(returns)
        assert "SECTOR ROTATION" in msg

    def test_best_and_worst_shown(self):
        returns = {"DeFi": 10.0, "L2": -5.0, "Meme": 25.0}
        msg = format_sector_dashboard(returns)
        assert "Best" in msg
        assert "Worst" in msg
        assert "Meme" in msg  # best
        assert "L2" in msg    # worst

    def test_medals_shown(self):
        returns = {"DeFi": 10.0, "L2": 5.0, "Meme": 1.0}
        msg = format_sector_dashboard(returns)
        assert "🥇" in msg
        assert "🥈" in msg
        assert "🥉" in msg

    def test_bar_characters_present(self):
        returns = {"DeFi": 10.0}
        msg = format_sector_dashboard(returns)
        assert "█" in msg or "░" in msg

    def test_single_sector(self):
        returns = {"DeFi": 5.0}
        msg = format_sector_dashboard(returns)
        assert "DeFi" in msg
        assert "Best" in msg

    def test_all_zeros(self):
        returns = {"DeFi": 0.0, "L2": 0.0}
        msg = format_sector_dashboard(returns)
        assert "SECTOR ROTATION" in msg


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
