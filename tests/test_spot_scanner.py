"""
Tests for the Spot Market Scanner (bot/spot_scanner.py).
"""
from __future__ import annotations

import time

from bot.spot_scanner import (
    ScamAlert,
    SpotGemResult,
    SpotScanner,
    fetch_binance_spot_pairs,
    validate_symbol,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_daily_candles(n: int, base_price: float = 1.0) -> list[list[float]]:
    """Return n synthetic daily OHLCV candles with flat price."""
    now_ms = int(time.time() * 1000)
    candles = []
    for i in range(n):
        t = now_ms - (n - i) * 86_400_000
        c = [t, base_price, base_price * 1.01, base_price * 0.99, base_price, 10_000.0]
        candles.append(c)
    return candles


def _make_daily_candles_with_volume_spike(n: int, spike_ratio: float = 4.0) -> list[list[float]]:
    """Return daily candles where the last candle has a spike_ratio volume spike."""
    candles = _make_daily_candles(n)
    # Set normal volume to 1000, last candle to spike_ratio * 1000
    for c in candles[:-1]:
        c[5] = 1_000.0
    candles[-1][5] = 1_000.0 * spike_ratio
    return candles


def _make_breakout_candles(n: int, base_price: float = 1.0, breakout_pct: float = 0.05) -> list[list[float]]:
    """Return daily candles where the last candle breaks above historical high with volume.
    Volume is 2.5x (above 1.5x breakout threshold but below 3x dormant-awakening threshold).
    """
    candles = _make_daily_candles(n, base_price)
    # Set all historical closes to base_price
    for c in candles[:-1]:
        c[4] = base_price
        c[5] = 1_000.0
    # Last candle breaks above (volume 2.5x — above 1.5x breakout threshold, below 3x awakening)
    candles[-1][4] = base_price * (1 + breakout_pct)
    candles[-1][2] = base_price * (1 + breakout_pct)  # high
    candles[-1][5] = 2_500.0  # 2.5x volume — triggers breakout but not dormant awakening
    return candles


def _make_accumulation_candles(n: int = 100, low_price: float = 0.50) -> list[list[float]]:
    """Return daily candles showing accumulation near 90-day low with rising volume."""
    candles = _make_daily_candles(n, base_price=0.60)
    # Set range: some go to low_price, most around 0.60
    for c in candles[:90]:
        c[4] = 0.60
        c[5] = 1_000.0
    # Last 14: rising volume, price near low
    for i, c in enumerate(candles[-14:]):
        c[4] = low_price * 1.05  # near low
        c[5] = 1_000.0 + i * 100.0  # rising volume
    # One historical low
    candles[5][3] = low_price  # set a low
    candles[5][4] = low_price
    return candles


def _make_scam_pump_candles(pump_pct: float = 600.0, crash_pct: float = 60.0) -> list[list[float]]:
    """Return 1h candles showing a pump-and-dump pattern."""
    n = 48
    candles = _make_daily_candles(n, base_price=1.0)
    base = 1.0
    pumped = base * (1 + pump_pct / 100)
    crashed = pumped * (1 - crash_pct / 100)
    # Pump in middle, crash at end
    for c in candles[:20]:
        c[4] = base
    for c in candles[20:40]:
        c[4] = pumped
        c[2] = pumped  # high
    for c in candles[40:]:
        c[4] = crashed
    return candles


def _make_wash_trading_candles(n: int = 24) -> list[list[float]]:
    """Return 1h candles with suspiciously uniform volume (wash trading)."""
    candles = _make_daily_candles(n, base_price=1.0)
    for c in candles:
        c[5] = 10_000.0  # perfectly uniform volume
    return candles


# ── SpotGemResult tests ───────────────────────────────────────────────────────

class TestSpotGemResultFormatMessage:
    def test_new_listing_message_contains_symbol(self):
        gem = SpotGemResult(
            symbol="NEWCOIN",
            gem_type="NEW_LISTING",
            entry_low=0.98,
            entry_high=1.02,
            tp1=1.15,
            tp2=1.30,
            tp3=1.50,
            stop_loss=0.90,
            score=55,
            reason="New listing detected.",
        )
        msg = gem.format_message()
        assert "#NEWCOIN/USDT" in msg
        assert "NEW_LISTING" in msg
        assert "TP1" in msg
        assert "SL" in msg

    def test_dormant_awakening_has_emoji(self):
        gem = SpotGemResult(
            symbol="SLEEPY",
            gem_type="DORMANT_AWAKENING",
            entry_low=0.98,
            entry_high=1.02,
            tp1=1.15,
            tp2=1.30,
            tp3=1.50,
            stop_loss=0.90,
            score=72,
            reason="Volume spike detected.",
        )
        msg = gem.format_message()
        assert "💤" in msg or "🚀" in msg

    def test_risk_flags_shown_in_message(self):
        gem = SpotGemResult(
            symbol="RISKY",
            gem_type="NEW_LISTING",
            entry_low=0.98,
            entry_high=1.02,
            tp1=1.15,
            tp2=1.30,
            tp3=1.50,
            stop_loss=0.90,
            score=40,
            reason="Test.",
            risk_flags=["low_liquidity", "new_listing_volatility"],
        )
        msg = gem.format_message()
        assert "low_liquidity" in msg
        assert "new_listing_volatility" in msg

    def test_score_shown_in_message(self):
        gem = SpotGemResult(
            symbol="BTC",
            gem_type="MOMENTUM_BREAKOUT",
            entry_low=50000,
            entry_high=50500,
            tp1=57500,
            tp2=65000,
            tp3=75000,
            stop_loss=45000,
            score=78,
            reason="Breakout confirmed.",
        )
        msg = gem.format_message()
        assert "78/100" in msg


# ── ScamAlert tests ───────────────────────────────────────────────────────────

class TestScamAlertFormatMessage:
    def test_critical_has_siren_emoji(self):
        alert = ScamAlert(
            symbol="SCAMCOIN",
            risk_level="CRITICAL",
            pattern="PUMP_AND_DUMP",
            evidence="600% pump then 60% crash.",
        )
        msg = alert.format_message()
        assert "🚨" in msg
        assert "CRITICAL" in msg
        assert "#SCAMCOIN/USDT" in msg

    def test_high_has_warning_emoji(self):
        alert = ScamAlert(
            symbol="WASHCOIN",
            risk_level="HIGH",
            pattern="WASH_TRADING",
            evidence="0.5% volume variance.",
        )
        msg = alert.format_message()
        assert "⚠️" in msg
        assert "HIGH" in msg

    def test_pattern_in_message(self):
        alert = ScamAlert(
            symbol="TEST",
            risk_level="CRITICAL",
            pattern="HONEYPOT",
            evidence="No sells detected.",
        )
        msg = alert.format_message()
        assert "HONEYPOT" in msg
        assert "Do NOT trade" in msg


# ── Symbol validation tests ───────────────────────────────────────────────────

class TestValidateSymbol:
    def test_valid_symbols(self):
        assert validate_symbol("BTC") is True
        assert validate_symbol("PEPE") is True
        assert validate_symbol("1000PEPE") is True
        assert validate_symbol("A1B2C3") is True

    def test_invalid_symbols(self):
        assert validate_symbol("") is False
        assert validate_symbol("BTC/USDT") is False
        assert validate_symbol("'; DROP TABLE--") is False
        assert validate_symbol("A" * 21) is False  # too long
        assert validate_symbol("btc") is False  # lowercase


# ── SpotScanner gem detection tests ──────────────────────────────────────────

class TestSpotScannerGemDetection:
    def _make_scanner(self) -> SpotScanner:
        return SpotScanner(
            spot_market_data=None,
            min_volume_usdt=0,  # no volume filter for tests
            volume_spike_ratio=3.0,
            breakout_lookback_days=30,
            accumulation_range_pct=0.10,
            new_listing_lookback_days=90,
        )

    def test_new_listing_detected(self):
        scanner = self._make_scanner()
        # Only 10 days of data — fewer than lookback_days (90)
        candles = _make_daily_candles(10)
        result = scanner.run_gem_detection("NEWCOIN", candles, [], [])
        assert result is not None
        assert result.gem_type == "NEW_LISTING"
        assert result.symbol == "NEWCOIN"

    def test_dormant_awakening_detected(self):
        scanner = self._make_scanner()
        candles = _make_daily_candles_with_volume_spike(100, spike_ratio=4.0)
        result = scanner.run_gem_detection("SLEEPY", candles, [], [])
        assert result is not None
        assert result.gem_type == "DORMANT_AWAKENING"

    def test_momentum_breakout_detected(self):
        scanner = self._make_scanner()
        candles = _make_breakout_candles(100, base_price=1.0, breakout_pct=0.05)
        result = scanner.run_gem_detection("BREAK", candles, [], [])
        assert result is not None
        assert result.gem_type == "MOMENTUM_BREAKOUT"

    def test_no_gem_on_insufficient_data(self):
        scanner = self._make_scanner()
        result = scanner.run_gem_detection("TINY", [], [], [])
        assert result is None

    def test_no_gem_on_zero_price(self):
        scanner = self._make_scanner()
        candles = _make_daily_candles(100, base_price=0.0)
        result = scanner.run_gem_detection("ZERO", candles, [], [])
        assert result is None

    def test_gem_has_correct_tp_levels(self):
        scanner = self._make_scanner()
        candles = _make_daily_candles(10)  # new listing
        result = scanner.run_gem_detection("TEST", candles, [], [])
        assert result is not None
        assert result.tp1 > result.entry_high
        assert result.tp2 > result.tp1
        assert result.tp3 > result.tp2
        assert result.stop_loss < result.entry_low

    def test_volume_filter_blocks_low_volume(self):
        scanner = SpotScanner(
            spot_market_data=None,
            min_volume_usdt=1_000_000,  # $1M minimum
        )
        # Volume = 10000 * price = 10000 (below 1M filter)
        candles = _make_daily_candles(10, base_price=1.0)
        result = scanner.run_gem_detection("LOWVOL", candles, [], [])
        assert result is None


# ── SpotScanner scam detection tests ─────────────────────────────────────────

class TestSpotScannerScamDetection:
    def _make_scanner(self) -> SpotScanner:
        return SpotScanner(
            spot_market_data=None,
            pump_threshold_pct=500.0,
            crash_threshold_pct=50.0,
        )

    def test_pump_and_dump_detected(self):
        scanner = self._make_scanner()
        candles = _make_scam_pump_candles(pump_pct=600.0, crash_pct=60.0)
        result = scanner.detect_scam_patterns("SCAM", candles, [], {})
        assert result is not None
        assert result.pattern == "PUMP_AND_DUMP"
        assert result.risk_level == "CRITICAL"

    def test_wash_trading_detected(self):
        scanner = self._make_scanner()
        candles = _make_wash_trading_candles(24)
        result = scanner.detect_scam_patterns("WASH", candles, [], {})
        assert result is not None
        assert result.pattern == "WASH_TRADING"
        assert result.risk_level == "HIGH"

    def test_no_scam_on_normal_candles(self):
        scanner = self._make_scanner()
        import random
        rng = random.Random(42)  # fixed seed for determinism
        candles = []
        base = 1.0
        for i in range(24):
            t = int(time.time() * 1000) - (24 - i) * 3_600_000
            vol = base * (1000 + rng.uniform(-200, 200))  # variable volume
            c = [t, base, base * 1.01, base * 0.99, base * (1 + rng.uniform(-0.01, 0.01)), vol]
            candles.append(c)
        result = scanner.detect_scam_patterns("NORMAL", candles, [], {})
        assert result is None

    def test_no_scam_on_insufficient_1h_candles(self):
        scanner = self._make_scanner()
        # Only 5 1h candles — below threshold of 24
        candles = _make_scam_pump_candles()[:5]
        result = scanner.detect_scam_patterns("FEW", candles, [], {})
        assert result is None


# ── SpotScanner.scam_check_symbol() tests ────────────────────────────────────

class TestSpotScannerScamCheckSymbol:
    def test_invalid_symbol_rejected(self):
        scanner = SpotScanner(spot_market_data=None)
        # Lowercase — invalid
        result = scanner.scam_check_symbol("btc")
        assert result is None

    def test_too_long_symbol_rejected(self):
        scanner = SpotScanner(spot_market_data=None)
        result = scanner.scam_check_symbol("A" * 25)
        assert result is None

    def test_symbol_with_special_chars_rejected(self):
        scanner = SpotScanner(spot_market_data=None)
        result = scanner.scam_check_symbol("BTC/USDT")
        assert result is None

    def test_valid_symbol_accepted(self):
        scanner = SpotScanner(spot_market_data=None)
        # No data → returns None (no scam detected)
        result = scanner.scam_check_symbol("BTC")
        assert result is None


# ── SpotScanner.scan_once() routing tests ─────────────────────────────────────

class TestSpotScannerScanOnce:
    def test_scan_once_returns_tuple(self):
        scanner = SpotScanner(spot_market_data=None)
        scanner._pairs = []  # empty to avoid API calls
        gems, scams = scanner.scan_once()
        assert isinstance(gems, list)
        assert isinstance(scams, list)

    def test_scan_once_returns_empty_when_disabled(self):
        scanner = SpotScanner(spot_market_data=None)
        scanner.set_enabled(False)
        gems, scams = scanner.scan_once()
        assert gems == []
        assert scams == []

    def test_get_status_fields(self):
        scanner = SpotScanner(spot_market_data=None)
        status = scanner.get_status()
        assert "enabled" in status
        assert "pairs_loaded" in status
        assert "last_scan" in status
        assert "gems_found_total" in status
        assert "scams_found_total" in status

    def test_spot_gems_route_to_ch4(self):
        """Gem signal's format_message should contain SPOT GEM ALERT."""
        gem = SpotGemResult(
            symbol="TEST",
            gem_type="ACCUMULATION",
            entry_low=0.98,
            entry_high=1.02,
            tp1=1.15,
            tp2=1.30,
            tp3=1.50,
            stop_loss=0.90,
            score=65,
            reason="Accumulation pattern detected.",
        )
        msg = gem.format_message()
        assert "SPOT GEM ALERT" in msg

    def test_scam_alerts_route_to_insights(self):
        """Scam alert's format_message should contain SCAM WARNING."""
        alert = ScamAlert(
            symbol="SCAM",
            risk_level="CRITICAL",
            pattern="PUMP_AND_DUMP",
            evidence="Evidence here.",
        )
        msg = alert.format_message()
        assert "SCAM WARNING" in msg


# ── fetch_binance_spot_pairs tests ────────────────────────────────────────────

class TestFetchBinanceSpotPairs:
    def test_returns_empty_list_on_exception(self, monkeypatch):
        """fetch_binance_spot_pairs() should return [] when exchange fails."""
        from unittest.mock import MagicMock

        mock_exchange = MagicMock()
        mock_exchange.load_markets.side_effect = Exception("network error")

        import bot.exchange as _exchange
        monkeypatch.setattr(_exchange, "_spot_resilient_exchange", mock_exchange)

        result = fetch_binance_spot_pairs()
        assert result == []

    def test_returns_usdt_spot_pairs(self, monkeypatch):
        """fetch_binance_spot_pairs() should return only active USDT spot pairs."""
        from unittest.mock import MagicMock

        mock_exchange = MagicMock()
        mock_exchange.load_markets.return_value = {}
        mock_exchange.markets = {
            "BTC/USDT": {"quote": "USDT", "active": True, "spot": True, "swap": False, "future": False, "base": "BTC"},
            "ETH/USDT": {"quote": "USDT", "active": True, "spot": True, "swap": False, "future": False, "base": "ETH"},
            "BTC/BNB": {"quote": "BNB", "active": True, "spot": True, "swap": False, "future": False, "base": "BTC"},
            "BTCUSDT-PERP": {"quote": "USDT", "active": True, "spot": False, "swap": True, "future": False, "base": "BTC"},
        }

        import bot.exchange as _exchange
        monkeypatch.setattr(_exchange, "_spot_resilient_exchange", mock_exchange)

        result = fetch_binance_spot_pairs()
        symbols = [p["symbol"] for p in result]
        assert "BTC" in symbols
        assert "ETH" in symbols
        # Non-USDT pair should not appear
        assert len([p for p in result if p["quote"] != "USDT"]) == 0
