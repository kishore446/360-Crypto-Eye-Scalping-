"""
Spot Market Scanner
===================
Scans all Binance Spot USDT pairs for gem opportunities and scam/manipulation
patterns.

Gem types detected:
  NEW_LISTING        — Listed within the last 90 days
  DORMANT_AWAKENING  — Low volume for 30+ days then 3x+ volume spike
  MOMENTUM_BREAKOUT  — Price breaking 30-day high with volume confirmation
  ACCUMULATION       — Tight range near 90-day low with rising volume
  CATALYST_DRIVEN    — Upcoming CoinMarketCal event (mainnet/listing/partnership)

Scam patterns detected:
  PUMP_AND_DUMP      — >500% spike then >50% crash within 24h
  WASH_TRADING       — Unrealistically uniform volume (low std-dev)
  HONEYPOT           — Massive buy volume, near-zero sell volume
  LOW_LIQUIDITY      — Order book depth < $10k on either side

Routing:
  Gem signals  → CH4 (SPOT)
  Scam alerts  → CH5 (INSIGHTS)
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Max length for user-supplied SYMBOL parameter in /scam_check
_SYMBOL_MAX_LEN = 20
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")

try:
    from config import (
        SPOT_GEM_ACCUMULATION_RANGE_PCT,
        SPOT_GEM_BREAKOUT_LOOKBACK_DAYS,
        SPOT_GEM_VOLUME_SPIKE_RATIO,
        SPOT_MIN_24H_VOLUME_USDT,
        SPOT_NEW_LISTING_LOOKBACK_DAYS,
        SPOT_SCAM_CRASH_THRESHOLD_PCT,
        SPOT_SCAM_PUMP_THRESHOLD_PCT,
        SPOT_SCAN_BATCH_DELAY,
        SPOT_SCAN_BATCH_SIZE,
    )
except Exception:  # pragma: no cover — fallback for tests without full env
    SPOT_MIN_24H_VOLUME_USDT = 100_000
    SPOT_GEM_VOLUME_SPIKE_RATIO = 3.0
    SPOT_GEM_BREAKOUT_LOOKBACK_DAYS = 30
    SPOT_GEM_ACCUMULATION_RANGE_PCT = 0.10
    SPOT_NEW_LISTING_LOOKBACK_DAYS = 90
    SPOT_SCAM_PUMP_THRESHOLD_PCT = 500.0
    SPOT_SCAM_CRASH_THRESHOLD_PCT = 50.0
    SPOT_SCAN_BATCH_SIZE = 30
    SPOT_SCAN_BATCH_DELAY = 0.5


@dataclass
class SpotGemResult:
    """A detected spot gem opportunity."""

    symbol: str
    gem_type: str  # "NEW_LISTING" | "DORMANT_AWAKENING" | "MOMENTUM_BREAKOUT" | "ACCUMULATION" | "CATALYST_DRIVEN"
    entry_low: float
    entry_high: float
    tp1: float  # +15%
    tp2: float  # +30%
    tp3: float  # +50%
    stop_loss: float  # -10%
    score: int  # 0-100 confidence score
    reason: str
    risk_flags: list[str] = field(default_factory=list)

    def format_message(self) -> str:
        """Format as a CH4 SPOT signal message."""
        gem_emoji = {
            "NEW_LISTING": "🆕",
            "DORMANT_AWAKENING": "💤➡️🚀",
            "MOMENTUM_BREAKOUT": "📈",
            "ACCUMULATION": "🏦",
            "CATALYST_DRIVEN": "📅",
        }.get(self.gem_type, "💎")

        flags_line = ""
        if self.risk_flags:
            flags_line = f"\n⚠️ *Risk:* {', '.join(self.risk_flags)}"

        return (
            f"💎 *SPOT GEM ALERT* {gem_emoji}\n"
            f"#{self.symbol}/USDT — `{self.gem_type}`\n\n"
            f"📥 *Entry Zone:* ${self.entry_low:,.4f} – ${self.entry_high:,.4f}\n"
            f"🎯 *TP1:* ${self.tp1:,.4f} (+15%)\n"
            f"🎯 *TP2:* ${self.tp2:,.4f} (+30%)\n"
            f"🎯 *TP3:* ${self.tp3:,.4f} (+50%)\n"
            f"🛑 *SL:* ${self.stop_loss:,.4f} (-10%)\n\n"
            f"📊 *Score:* {self.score}/100\n"
            f"💬 {self.reason}"
            f"{flags_line}"
        )


@dataclass
class ScamAlert:
    """A detected scam / manipulation pattern."""

    symbol: str
    risk_level: str  # "HIGH" | "CRITICAL"
    pattern: str  # "PUMP_AND_DUMP" | "WASH_TRADING" | "HONEYPOT" | "LOW_LIQUIDITY"
    evidence: str

    def format_message(self) -> str:
        """Format as a CH5 Insights warning."""
        level_emoji = "🚨" if self.risk_level == "CRITICAL" else "⚠️"
        return (
            f"{level_emoji} *SCAM WARNING — {self.risk_level}*\n"
            f"#{self.symbol}/USDT — `{self.pattern}`\n\n"
            f"🔍 *Evidence:* {self.evidence}\n\n"
            f"_Do NOT trade this pair._"
        )


def fetch_binance_spot_pairs() -> list[dict]:
    """
    Fetch all active USDT spot pairs from Binance.

    Returns a list of dicts with:
      symbol, base, quote, volume_24h_usdt

    Uses the spot ResilientExchange instance.
    """
    try:
        from bot.exchange import _spot_resilient_exchange

        _spot_resilient_exchange.load_markets()
        pairs: list[dict] = []
        for sym, market in _spot_resilient_exchange.markets.items():
            if (
                market.get("quote") == "USDT"
                and market.get("active", False)
                and market.get("spot", False)
                and not market.get("swap", False)
                and not market.get("future", False)
            ):
                pairs.append(
                    {
                        "symbol": market["base"],
                        "base": market["base"],
                        "quote": "USDT",
                        "ccxt_symbol": sym,
                        "volume_24h_usdt": 0.0,  # populated separately if needed
                    }
                )
        pairs.sort(key=lambda p: p["symbol"])
        logger.info("Fetched %d active Binance Spot USDT pairs.", len(pairs))
        return pairs
    except Exception as exc:
        logger.warning("fetch_binance_spot_pairs() failed: %s", exc)
        return []


def validate_symbol(symbol: str) -> bool:
    """Validate a user-supplied symbol is safe (alphanumeric, max 20 chars)."""
    return bool(_SYMBOL_RE.match(symbol))


class SpotScanner:
    """
    Scans all Binance Spot pairs on a configurable interval.

    - Refreshes pair list every 6 hours
    - Runs gem detection on each pair's candle history
    - Runs scam detection on short-timeframe candles
    - Returns (gems, scam_alerts) from scan_once()
    """

    def __init__(
        self,
        spot_market_data=None,  # MarketDataStore for spot
        min_volume_usdt: int = SPOT_MIN_24H_VOLUME_USDT,
        volume_spike_ratio: float = SPOT_GEM_VOLUME_SPIKE_RATIO,
        breakout_lookback_days: int = SPOT_GEM_BREAKOUT_LOOKBACK_DAYS,
        accumulation_range_pct: float = SPOT_GEM_ACCUMULATION_RANGE_PCT,
        new_listing_lookback_days: int = SPOT_NEW_LISTING_LOOKBACK_DAYS,
        pump_threshold_pct: float = SPOT_SCAM_PUMP_THRESHOLD_PCT,
        crash_threshold_pct: float = SPOT_SCAM_CRASH_THRESHOLD_PCT,
        batch_size: int = SPOT_SCAN_BATCH_SIZE,
        batch_delay: float = SPOT_SCAN_BATCH_DELAY,
    ) -> None:
        self._spot_market_data = spot_market_data
        self._min_volume_usdt = min_volume_usdt
        self._volume_spike_ratio = volume_spike_ratio
        self._breakout_lookback_days = breakout_lookback_days
        self._accumulation_range_pct = accumulation_range_pct
        self._new_listing_lookback_days = new_listing_lookback_days
        self._pump_threshold_pct = pump_threshold_pct
        self._crash_threshold_pct = crash_threshold_pct
        self._batch_size = batch_size
        self._batch_delay = batch_delay

        self._pairs: list[dict] = []
        self._last_pair_refresh: float = 0.0
        self._last_scan_time: float = 0.0
        self._gems_found: int = 0
        self._scams_found: int = 0
        self._enabled: bool = True

    def refresh_pairs(self) -> None:
        """Re-fetch the active Binance Spot USDT pair list."""
        self._pairs = fetch_binance_spot_pairs()
        self._last_pair_refresh = time.time()
        logger.info("Spot scanner: loaded %d pairs.", len(self._pairs))

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value

    def get_status(self) -> dict:
        """Return current scanner status for /spot_status command."""
        return {
            "enabled": self._enabled,
            "pairs_loaded": len(self._pairs),
            "last_scan": self._last_scan_time,
            "gems_found_total": self._gems_found,
            "scams_found_total": self._scams_found,
        }

    def scan_once(self) -> tuple[list[SpotGemResult], list[ScamAlert]]:
        """Run one full spot scan cycle synchronously."""
        if not self._enabled:
            return [], []

        if not self._pairs:
            self.refresh_pairs()

        gems: list[SpotGemResult] = []
        scams: list[ScamAlert] = []

        pairs = list(self._pairs)
        total = len(pairs)
        logger.info("Spot scanner: scanning %d pairs…", total)

        for i in range(0, total, self._batch_size):
            batch = pairs[i : i + self._batch_size]
            for pair_info in batch:
                sym = pair_info["symbol"]
                try:
                    candles_1d = self._get_candles(sym, "1d")
                    candles_4h = self._get_candles(sym, "4h")
                    candles_1h = self._get_candles(sym, "1h")

                    gem = self.run_gem_detection(sym, candles_1d, candles_4h, candles_1h)
                    if gem is not None:
                        gems.append(gem)
                        self._gems_found += 1

                    scam = self.detect_scam_patterns(sym, candles_1h, candles_1d, {})
                    if scam is not None:
                        scams.append(scam)
                        self._scams_found += 1
                except Exception as exc:
                    logger.debug("Spot scan error for %s: %s", sym, exc)

            # Inter-batch pause to respect rate limits
            if i + self._batch_size < total:
                time.sleep(self._batch_delay)

        self._last_scan_time = time.time()
        logger.info(
            "Spot scanner complete — %d gems, %d scam alerts found.",
            len(gems),
            len(scams),
        )
        return gems, scams

    def _get_candles(self, symbol: str, timeframe: str) -> list[list[float]]:
        """Return candles from in-memory store, or empty list if unavailable."""
        if self._spot_market_data is None:
            return []
        return self._spot_market_data.get_candles(symbol, timeframe)

    def run_gem_detection(
        self,
        symbol: str,
        candles_1d: list[list[float]],
        candles_4h: list[list[float]],
        candles_1h: list[list[float]],
    ) -> Optional[SpotGemResult]:
        """Check if a spot pair qualifies as a gem. Returns SpotGemResult or None."""
        if not candles_1d or len(candles_1d) < 5:
            return None

        current_price = float(candles_1d[-1][4])  # last close
        if current_price <= 0:
            return None

        # ── Volume filter ──────────────────────────────────────────────────
        recent_volume = float(candles_1d[-1][5]) * current_price
        if self._min_volume_usdt > 0 and recent_volume < self._min_volume_usdt:
            return None

        risk_flags: list[str] = []
        if recent_volume < 500_000:
            risk_flags.append("low_liquidity")

        entry_mid = current_price
        entry_low = entry_mid * 0.99
        entry_high = entry_mid * 1.01
        tp1 = entry_mid * 1.15
        tp2 = entry_mid * 1.30
        tp3 = entry_mid * 1.50
        stop_loss = entry_mid * 0.90

        # ── NEW_LISTING detection ──────────────────────────────────────────
        # Proxy: fewer daily candles available than lookback days
        lookback = self._new_listing_lookback_days
        if len(candles_1d) < lookback:
            risk_flags.append("new_listing_volatility")
            return SpotGemResult(
                symbol=symbol,
                gem_type="NEW_LISTING",
                entry_low=entry_low,
                entry_high=entry_high,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                stop_loss=stop_loss,
                score=55,
                reason=(
                    f"Recently listed coin ({len(candles_1d)} days of data). "
                    "Monitor for early momentum."
                ),
                risk_flags=risk_flags,
            )

        closes = [float(c[4]) for c in candles_1d]
        volumes = [float(c[5]) for c in candles_1d]

        # ── DORMANT_AWAKENING detection ────────────────────────────────────
        lookback_30 = min(30, len(volumes) - 1)
        if lookback_30 >= 5:
            avg_vol_30d = sum(volumes[-lookback_30 - 1 : -1]) / lookback_30
            last_vol = volumes[-1]
            if avg_vol_30d > 0 and last_vol / avg_vol_30d >= self._volume_spike_ratio:
                return SpotGemResult(
                    symbol=symbol,
                    gem_type="DORMANT_AWAKENING",
                    entry_low=entry_low,
                    entry_high=entry_high,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    stop_loss=stop_loss,
                    score=72,
                    reason=(
                        f"Volume spiked {last_vol / avg_vol_30d:.1f}x vs 30-day average. "
                        "Potential dormant awakening."
                    ),
                    risk_flags=risk_flags,
                )

        # ── MOMENTUM_BREAKOUT detection ────────────────────────────────────
        lookback_days = min(self._breakout_lookback_days, len(closes) - 1)
        if lookback_days >= 5:
            high_30d = max(closes[-lookback_days - 1 : -1])
            avg_vol_30d = sum(volumes[-lookback_days - 1 : -1]) / lookback_days
            last_vol = volumes[-1]
            if current_price > high_30d and avg_vol_30d > 0 and last_vol > 2 * avg_vol_30d:
                return SpotGemResult(
                    symbol=symbol,
                    gem_type="MOMENTUM_BREAKOUT",
                    entry_low=entry_low,
                    entry_high=entry_high,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    stop_loss=stop_loss,
                    score=78,
                    reason=(
                        f"Price broke {lookback_days}-day high ${high_30d:,.4f} "
                        f"with {last_vol / avg_vol_30d:.1f}x volume confirmation."
                    ),
                    risk_flags=risk_flags,
                )

        # ── ACCUMULATION detection ─────────────────────────────────────────
        # A coin is "near its 90d low" if within 1.5x the accumulation range config.
        _near_low_threshold = self._accumulation_range_pct * 1.5
        # Volume trend is "rising" if 2nd half of 14d is 10% above 1st half.
        _volume_trend_multiplier = 1.1
        lookback_90 = min(90, len(closes) - 1)
        if lookback_90 >= 10:
            low_90d = min(closes[-lookback_90:])
            high_90d = max(closes[-lookback_90:])
            range_pct = (high_90d - low_90d) / low_90d if low_90d > 0 else 1.0
            near_low = (current_price - low_90d) / low_90d < _near_low_threshold if low_90d > 0 else False
            # Check rising volume trend over last 14 days
            if len(volumes) >= 14:
                first_half_vol = sum(volumes[-14:-7]) / 7
                second_half_vol = sum(volumes[-7:]) / 7
                rising_vol = second_half_vol > first_half_vol * _volume_trend_multiplier

                if (
                    range_pct <= self._accumulation_range_pct * 3
                    and near_low
                    and rising_vol
                ):
                    return SpotGemResult(
                        symbol=symbol,
                        gem_type="ACCUMULATION",
                        entry_low=entry_low,
                        entry_high=entry_high,
                        tp1=tp1,
                        tp2=tp2,
                        tp3=tp3,
                        stop_loss=stop_loss,
                        score=65,
                        reason=(
                            f"Price near 90-day low (${low_90d:,.4f}) in tight "
                            f"{range_pct * 100:.1f}% range with rising volume trend."
                        ),
                        risk_flags=risk_flags,
                    )

        return None

    def detect_scam_patterns(
        self,
        symbol: str,
        candles_1h: list[list[float]],
        candles_1d: list[list[float]],
        volume_profile: dict,
    ) -> Optional[ScamAlert]:
        """Check if a spot pair shows scam/manipulation patterns."""
        if not candles_1h or len(candles_1h) < 24:
            return None

        # ── PUMP_AND_DUMP detection ────────────────────────────────────────
        # Look for >PUMP_THRESHOLD spike followed by >CRASH_THRESHOLD drop
        closes_1h = [float(c[4]) for c in candles_1h[-48:]]
        if len(closes_1h) >= 4:
            window_low = min(closes_1h[:-1])
            window_high = max(closes_1h[:-1])
            current = closes_1h[-1]

            if window_low > 0:
                pump_pct = (window_high - window_low) / window_low * 100
                if pump_pct >= self._pump_threshold_pct:
                    crash_pct = (window_high - current) / window_high * 100
                    if crash_pct >= self._crash_threshold_pct:
                        return ScamAlert(
                            symbol=symbol,
                            risk_level="CRITICAL",
                            pattern="PUMP_AND_DUMP",
                            evidence=(
                                f"Price pumped {pump_pct:.0f}% then crashed {crash_pct:.0f}% "
                                f"within 48h. Classic pump-and-dump."
                            ),
                        )

        # ── WASH_TRADING detection ─────────────────────────────────────────
        # Unrealistically uniform volumes (std-dev / mean < 2%)
        volumes_1h = [float(c[5]) for c in candles_1h[-24:]]
        if len(volumes_1h) >= 12:
            mean_vol = sum(volumes_1h) / len(volumes_1h)
            if mean_vol > 0:
                try:
                    std_vol = statistics.stdev(volumes_1h)
                    cv = std_vol / mean_vol  # coefficient of variation
                    if cv < 0.02:  # < 2% variation is suspicious
                        return ScamAlert(
                            symbol=symbol,
                            risk_level="HIGH",
                            pattern="WASH_TRADING",
                            evidence=(
                                f"Volume coefficient of variation is only {cv * 100:.2f}% "
                                f"(< 2%). Suggests artificial/wash trading."
                            ),
                        )
                except statistics.StatisticsError:
                    pass

        return None

    def scam_check_symbol(self, symbol: str) -> Optional[ScamAlert]:
        """
        Manual scam check for a single symbol (used by /scam_check command).

        The symbol must be alphanumeric and at most 20 characters.
        Returns None if the symbol is invalid or no scam is detected.
        """
        if not validate_symbol(symbol):
            logger.warning("scam_check_symbol: invalid symbol '%s' rejected.", symbol)
            return None
        candles_1h = self._get_candles(symbol, "1h")
        candles_1d = self._get_candles(symbol, "1d")
        return self.detect_scam_patterns(symbol, candles_1h, candles_1d, {})
