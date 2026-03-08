"""
Config sync tests — verify config defaults match Blueprint v3.0.0-domination values.
"""
from __future__ import annotations


class TestConfigSyncBlueprintValues:
    """Verify that all config defaults match the Blueprint specifications."""

    def test_max_same_side_signals_is_3(self):
        """Blueprint says max 3 concurrent same-side signals."""
        import config
        assert config.MAX_SAME_SIDE_SIGNALS == 3, (
            f"Expected MAX_SAME_SIDE_SIGNALS=3 (Blueprint v3), got {config.MAX_SAME_SIDE_SIGNALS}"
        )

    def test_min_confluence_score_is_40(self):
        """Blueprint requires min confluence score of 40 to filter low-quality signals."""
        import config
        assert config.MIN_CONFLUENCE_SCORE == 40, (
            f"Expected MIN_CONFLUENCE_SCORE=40 (Blueprint v3), got {config.MIN_CONFLUENCE_SCORE}"
        )

    def test_session_filter_enabled_by_default(self):
        """README documents SESSION_FILTER_ENABLED default as false (24/7 scanning)."""
        import config
        assert config.SESSION_FILTER_ENABLED is False, (
            f"Expected SESSION_FILTER_ENABLED=False (README default, 24/7 scanning), got {config.SESSION_FILTER_ENABLED}"
        )

    def test_auto_scan_pairs_empty_by_default(self):
        """New default: AUTO_SCAN_PAIRS is empty so the bot scans ALL Binance Futures pairs."""
        import config
        assert len(config.AUTO_SCAN_PAIRS) == 0, (
            f"Expected AUTO_SCAN_PAIRS to be empty (scan all), got {config.AUTO_SCAN_PAIRS}"
        )

    def test_auto_scan_pairs_is_list(self):
        """AUTO_SCAN_PAIRS should always be a list (even when empty)."""
        import config
        assert isinstance(config.AUTO_SCAN_PAIRS, list), (
            f"Expected AUTO_SCAN_PAIRS to be a list, got {type(config.AUTO_SCAN_PAIRS)}"
        )


class TestPerChannelSessionConfig:
    """Verify per-channel session filter configuration is present."""

    def test_ch1_session_filter_enabled(self):
        """CH1 Hard Scalp should have session gating enabled."""
        import config
        assert hasattr(config, "SESSION_FILTER_CH1_ENABLED"), (
            "Missing SESSION_FILTER_CH1_ENABLED in config"
        )
        assert config.SESSION_FILTER_CH1_ENABLED is True

    def test_ch2_session_filter_enabled(self):
        """CH2 Medium Scalp should have session gating enabled."""
        import config
        assert hasattr(config, "SESSION_FILTER_CH2_ENABLED"), (
            "Missing SESSION_FILTER_CH2_ENABLED in config"
        )
        assert config.SESSION_FILTER_CH2_ENABLED is True

    def test_ch3_session_filter_disabled(self):
        """CH3 Easy Breakout should be 24/7 (no session gating)."""
        import config
        assert hasattr(config, "SESSION_FILTER_CH3_ENABLED"), (
            "Missing SESSION_FILTER_CH3_ENABLED in config"
        )
        assert config.SESSION_FILTER_CH3_ENABLED is False

    def test_ch4_session_filter_disabled(self):
        """CH4 Spot should be 24/7 (no session gating)."""
        import config
        assert hasattr(config, "SESSION_FILTER_CH4_ENABLED"), (
            "Missing SESSION_FILTER_CH4_ENABLED in config"
        )
        assert config.SESSION_FILTER_CH4_ENABLED is False


class TestDashboardTradeResultFields:
    """Verify TradeResult has new fields required by Blueprint v3."""

    def test_trade_result_has_channel_tier(self):
        from bot.dashboard import TradeResult
        assert "channel_tier" in TradeResult.__dataclass_fields__, (
            "TradeResult missing 'channel_tier' field"
        )

    def test_trade_result_has_session(self):
        from bot.dashboard import TradeResult
        assert "session" in TradeResult.__dataclass_fields__, (
            "TradeResult missing 'session' field"
        )

    def test_default_channel_tier_is_aggregate(self):
        import time

        from bot.dashboard import TradeResult
        r = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=102.0,
            stop_loss=98.0, tp1=102.0, tp2=104.0, tp3=106.0,
            opened_at=time.time(), closed_at=None,
            outcome="WIN", pnl_pct=2.0, timeframe="5m",
        )
        assert r.channel_tier == "AGGREGATE"

    def test_default_session_is_unknown(self):
        import time

        from bot.dashboard import TradeResult
        r = TradeResult(
            symbol="BTC", side="LONG", entry_price=100.0, exit_price=102.0,
            stop_loss=98.0, tp1=102.0, tp2=104.0, tp3=106.0,
            opened_at=time.time(), closed_at=None,
            outcome="WIN", pnl_pct=2.0, timeframe="5m",
        )
        assert r.session == "UNKNOWN"


class TestDashboardPerChannelMethods:
    """Verify Dashboard has per-channel and per-session stats methods."""

    def test_per_channel_stats_method_exists(self, tmp_path):
        from bot.dashboard import Dashboard
        db = Dashboard(log_file=str(tmp_path / "db.json"))
        assert hasattr(db, "per_channel_stats"), "Dashboard missing per_channel_stats()"
        result = db.per_channel_stats()
        assert isinstance(result, dict)

    def test_per_session_stats_method_exists(self, tmp_path):
        from bot.dashboard import Dashboard
        db = Dashboard(log_file=str(tmp_path / "db.json"))
        assert hasattr(db, "per_session_stats"), "Dashboard missing per_session_stats()"
        result = db.per_session_stats()
        assert isinstance(result, dict)

    def test_format_per_channel_report_method_exists(self, tmp_path):
        from bot.dashboard import Dashboard
        db = Dashboard(log_file=str(tmp_path / "db.json"))
        assert hasattr(db, "format_per_channel_report"), (
            "Dashboard missing format_per_channel_report()"
        )
        report = db.format_per_channel_report()
        assert isinstance(report, str)


class TestRiskManagerDynamicRisk:
    """Verify RiskManager has dynamic_risk_fraction method."""

    def test_dynamic_risk_fraction_method_exists(self):
        from bot.risk_manager import RiskManager
        rm = RiskManager()
        assert hasattr(rm, "dynamic_risk_fraction"), (
            "RiskManager missing dynamic_risk_fraction() method"
        )

    def test_returns_float(self):
        from bot.risk_manager import RiskManager

        class MockCooldown:
            def is_cooldown_active(self):
                return False

        rm = RiskManager()
        result = rm.dynamic_risk_fraction("HIGH", MockCooldown())
        assert isinstance(result, float)
