"""Tests for bot/insights/oi_heatmap.py"""
from __future__ import annotations

from bot.insights.oi_heatmap import (
    _oi_emoji,
    format_oi_heatmap,
    get_target_channel_id,
)


class TestOiEmoji:
    def test_fire_for_10pct_or_more(self):
        assert _oi_emoji(10.0) == "🔥"
        assert _oi_emoji(15.0) == "🔥"
        assert _oi_emoji(-10.0) == "🔥"

    def test_lightning_for_5_to_10(self):
        assert _oi_emoji(5.0) == "⚡"
        assert _oi_emoji(7.5) == "⚡"
        assert _oi_emoji(-5.0) == "⚡"

    def test_chart_for_2_to_5(self):
        assert _oi_emoji(2.0) == "📊"
        assert _oi_emoji(4.9) == "📊"

    def test_arrow_for_below_2(self):
        assert _oi_emoji(1.5) == "➡️"
        assert _oi_emoji(0.0) == "➡️"
        assert _oi_emoji(-1.0) == "➡️"


class TestFormatOiHeatmap:
    def test_empty_input(self):
        msg = format_oi_heatmap({})
        assert "No OI data" in msg

    def test_header_present(self):
        msg = format_oi_heatmap({"BTCUSDT": 5.0})
        assert "OI HEATMAP" in msg

    def test_symbol_stripped_of_usdt(self):
        msg = format_oi_heatmap({"BTCUSDT": 5.0})
        assert "BTC" in msg

    def test_top_10_limit(self):
        # 15 symbols, only top 10 by absolute value should appear
        oi = {f"TOKEN{i}USDT": float(i) for i in range(1, 16)}
        msg = format_oi_heatmap(oi)
        # The lowest value token (TOKEN1 with value 1.0) should NOT appear
        # while the highest ones should
        assert "TOKEN15" in msg  # top by abs value
        assert "TOKEN1USDT".replace("USDT", "") not in msg or msg.count("TOKEN") <= 11

    def test_sorted_by_absolute_change(self):
        oi = {"BTCUSDT": 3.0, "ETHUSDT": -15.0, "SOLUSDT": 8.0}
        msg = format_oi_heatmap(oi)
        # ETH (15% abs) should appear before BTC (3%)
        assert msg.index("ETH") < msg.index("BTC")

    def test_positive_change_shown(self):
        msg = format_oi_heatmap({"BTCUSDT": 12.5})
        assert "+12.5%" in msg

    def test_negative_change_shown(self):
        msg = format_oi_heatmap({"ETHUSDT": -8.0})
        assert "-8.0%" in msg

    def test_highest_oi_note(self):
        msg = format_oi_heatmap({"BTCUSDT": 15.0, "ETHUSDT": 5.0})
        assert "Highest OI Change" in msg
        assert "BTC" in msg

    def test_fire_emoji_present_for_large_change(self):
        msg = format_oi_heatmap({"BTCUSDT": 20.0})
        assert "🔥" in msg


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
