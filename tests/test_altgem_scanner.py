"""Tests for bot/channels/altgem_scanner.py"""
from __future__ import annotations

import pytest

from bot.channels.altgem_scanner import (
    AltgemResult,
    GemType,
    calculate_altseason_index,
    calculate_sector_returns,
    detect_dormant_awakening,
    format_altseason_post,
    format_sector_rotation,
    get_sector,
    get_target_channel_id,
    is_scam_pump,
)

# ── Sector mapping ────────────────────────────────────────────────────────────


class TestGetSector:
    def test_defi_token(self):
        assert get_sector("UNIUSDT") == "DeFi"

    def test_l2_token(self):
        assert get_sector("ARBUSDT") == "L2"

    def test_meme_token(self):
        assert get_sector("DOGEUSDT") == "Meme"

    def test_ai_token(self):
        assert get_sector("FETUSDT") == "AI"

    def test_gaming_token(self):
        assert get_sector("AXSUSDT") == "Gaming"

    def test_unknown_token(self):
        assert get_sector("UNKNOWNUSDT") is None

    def test_slash_variant(self):
        assert get_sector("UNI/USDT") == "DeFi"

    def test_case_insensitive(self):
        assert get_sector("uniusdt") == "DeFi"


# ── Scam pump filter ──────────────────────────────────────────────────────────


class TestScamPumpFilter:
    def test_normal_pump_not_scam(self):
        assert is_scam_pump(50.0) is False

    def test_below_threshold(self):
        assert is_scam_pump(499.9) is False

    def test_at_threshold_not_scam(self):
        # Threshold is > 500 (strict), so exactly 500% is NOT a scam
        assert is_scam_pump(500.0) is False

    def test_above_threshold_is_scam(self):
        assert is_scam_pump(1000.0) is True


# ── Dormant awakening detection ───────────────────────────────────────────────


class TestDetectDormantAwakening:
    def test_detects_awakening(self):
        result = detect_dormant_awakening(
            symbol="UNIUSDT",
            volume_24h_usdt=1_000_000,
            current_volume=500.0,
            avg_volume_20=100.0,  # 5x spike
            price=5.0,
            price_change_24h=15.0,
        )
        assert result is not None
        assert result.gem_type == GemType.DORMANT_AWAKENING
        assert result.volume_ratio == pytest.approx(5.0)
        assert result.sector == "DeFi"

    def test_insufficient_volume_spike_returns_none(self):
        result = detect_dormant_awakening(
            symbol="UNIUSDT",
            volume_24h_usdt=1_000_000,
            current_volume=200.0,
            avg_volume_20=100.0,  # only 2x — below 3x threshold
            price=5.0,
            price_change_24h=15.0,
        )
        assert result is None

    def test_high_cap_coin_excluded(self):
        result = detect_dormant_awakening(
            symbol="BTCUSDT",
            volume_24h_usdt=10_000_000_000,  # way above $5M threshold
            current_volume=500.0,
            avg_volume_20=100.0,
            price=95000.0,
            price_change_24h=5.0,
        )
        assert result is None

    def test_scam_pump_excluded(self):
        result = detect_dormant_awakening(
            symbol="SCAMCOIN",
            volume_24h_usdt=100_000,
            current_volume=600.0,
            avg_volume_20=100.0,  # 6x spike
            price=0.001,
            price_change_24h=600.0,  # > 500% → scam
        )
        assert result is None

    def test_zero_avg_volume_returns_none(self):
        result = detect_dormant_awakening(
            symbol="UNIUSDT",
            volume_24h_usdt=100_000,
            current_volume=600.0,
            avg_volume_20=0.0,
            price=5.0,
            price_change_24h=10.0,
        )
        assert result is None

    def test_custom_threshold(self):
        result = detect_dormant_awakening(
            symbol="UNIUSDT",
            volume_24h_usdt=1_000_000,
            current_volume=250.0,
            avg_volume_20=100.0,  # 2.5x
            price=5.0,
            price_change_24h=10.0,
            min_volume_spike=2.0,  # custom threshold
        )
        assert result is not None


# ── Altseason index ───────────────────────────────────────────────────────────


class TestCalculateAltseasonIndex:
    def test_altseason_heating_when_alts_outperform(self):
        result = calculate_altseason_index(btc_7d_change=2.0, alt_avg_7d_change=10.0)
        assert result["is_altseason"] is True
        assert result["diff"] == pytest.approx(8.0)
        assert result["score"] > 50

    def test_btc_dominance_when_btc_outperforms(self):
        result = calculate_altseason_index(btc_7d_change=15.0, alt_avg_7d_change=5.0)
        assert result["is_altseason"] is False
        assert result["diff"] == pytest.approx(-10.0)
        assert result["score"] < 50

    def test_score_range_0_to_100(self):
        # Extreme cases
        r1 = calculate_altseason_index(-50.0, 50.0)
        assert r1["score"] == pytest.approx(100.0)
        r2 = calculate_altseason_index(50.0, -50.0)
        assert r2["score"] == pytest.approx(0.0)

    def test_neutral_case(self):
        result = calculate_altseason_index(5.0, 5.0)
        assert result["is_altseason"] is False
        assert result["score"] == pytest.approx(50.0)


# ── Sector rotation ───────────────────────────────────────────────────────────


class TestSectorRotation:
    def test_calculate_sector_returns(self):
        sector_prices = {
            "DeFi": {"UNI": 10.0, "AAVE": 5.0},
            "Meme": {"DOGE": 20.0, "SHIB": -5.0},
        }
        result = calculate_sector_returns(sector_prices)
        assert result["DeFi"] == pytest.approx(7.5)
        assert result["Meme"] == pytest.approx(7.5)

    def test_empty_sector_returns_zero(self):
        result = calculate_sector_returns({"DeFi": {}})
        assert result["DeFi"] == pytest.approx(0.0)

    def test_format_sector_rotation_sorted(self):
        returns = {"DeFi": 10.0, "Meme": -5.0, "AI": 15.0}
        msg = format_sector_rotation(returns)
        assert "AI" in msg
        assert "DeFi" in msg
        assert "Meme" in msg
        # AI should appear before DeFi (higher return)
        assert msg.index("AI") < msg.index("Meme")


# ── AltgemResult message format ───────────────────────────────────────────────


class TestAltgemResultFormat:
    def test_format_message(self):
        result = AltgemResult(
            symbol="UNIUSDT",
            gem_type=GemType.DORMANT_AWAKENING,
            volume_ratio=5.2,
            price=5.234,
            price_change_24h=12.5,
            volume_24h_usdt=2_300_000,
            sector="DeFi",
        )
        msg = result.format_message()
        assert "UNI/USDT" in msg
        assert "DORMANT_AWAKENING" in msg
        assert "5.2x" in msg
        assert "DeFi" in msg
        assert "+12.5%" in msg
        assert "DYOR" in msg

    def test_format_message_negative_change(self):
        result = AltgemResult(
            symbol="ARBUSDT",
            gem_type=GemType.BREAKOUT,
            volume_ratio=3.1,
            price=1.5,
            price_change_24h=-2.0,
            volume_24h_usdt=500_000,
        )
        msg = result.format_message()
        assert "-2.0%" in msg

    def test_format_message_no_sector(self):
        result = AltgemResult(
            symbol="XYZUSDT",
            gem_type=GemType.ACCUMULATION,
            volume_ratio=3.5,
            price=0.01,
            price_change_24h=5.0,
            volume_24h_usdt=1_000_000,
            sector=None,
        )
        msg = result.format_message()
        assert "Unknown" in msg


# ── Altseason post format ─────────────────────────────────────────────────────


class TestFormatAltseasonPost:
    def test_altseason_post_contains_score(self):
        msg = format_altseason_post(btc_7d_change=2.0, alt_avg_7d_change=10.0)
        assert "ALTSEASON INDEX" in msg
        assert "Score:" in msg
        assert "BTC 7d:" in msg
        assert "Alt avg 7d:" in msg

    def test_altseason_label_shown(self):
        msg = format_altseason_post(btc_7d_change=-5.0, alt_avg_7d_change=20.0)
        assert "Heating Up" in msg or "Altseason" in msg


# ── Channel ID guard ──────────────────────────────────────────────────────────


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
