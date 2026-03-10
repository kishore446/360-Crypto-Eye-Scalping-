"""
CH6 — Altcoin Gems Scanner
Detects dormant altcoin awakening, calculates altseason index,
and tracks sector rotation using Binance spot data.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

try:
    from config import (
        ALTGEM_MAX_24H_VOLUME_USDT,
        ALTGEM_MIN_VOLUME_SPIKE,
        SPOT_SCAM_PUMP_THRESHOLD_PCT,
        TELEGRAM_CHANNEL_ID_ALTGEMS,
    )
except Exception:  # pragma: no cover
    ALTGEM_MIN_VOLUME_SPIKE = 3.0
    ALTGEM_MAX_24H_VOLUME_USDT = 5_000_000
    SPOT_SCAM_PUMP_THRESHOLD_PCT = 500.0
    TELEGRAM_CHANNEL_ID_ALTGEMS = 0

# ── Sector definitions ────────────────────────────────────────────────────────

SECTORS: dict[str, list[str]] = {
    "DeFi": ["UNI", "AAVE", "MKR", "COMP", "SNX"],
    "L2": ["ARB", "OP", "MATIC", "MANTA", "STRK"],
    "Meme": ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK"],
    "AI": ["FET", "RENDER", "AGIX", "OCEAN", "TAO"],
    "Gaming": ["AXS", "SAND", "MANA", "IMX", "GALA"],
}

# Reverse lookup: token → sector
_TOKEN_SECTOR: dict[str, str] = {
    token: sector for sector, tokens in SECTORS.items() for token in tokens
}


# ── Enums & dataclasses ───────────────────────────────────────────────────────


class GemType(str, Enum):
    DORMANT_AWAKENING = "DORMANT_AWAKENING"
    BREAKOUT = "BREAKOUT"
    ACCUMULATION = "ACCUMULATION"


@dataclass
class AltgemResult:
    """A detected altcoin gem signal."""

    symbol: str
    gem_type: GemType
    volume_ratio: float
    price: float
    price_change_24h: float
    volume_24h_usdt: float
    sector: Optional[str] = None

    def format_message(self) -> str:
        """Return a Telegram-formatted gem alert message."""
        base = self.symbol.replace("USDT", "")
        sector_line = f"📈 Sector: {self.sector}" if self.sector else "📈 Sector: Unknown"
        direction = "+" if self.price_change_24h >= 0 else ""
        vol_m = self.volume_24h_usdt / 1_000_000
        return (
            f"💎 ALTCOIN GEM ALERT — #{base}/USDT\n"
            f"Type: {self.gem_type.value}\n"
            f"──────────────────────────\n"
            f"📊 Volume: {self.volume_ratio:.1f}x avg (24h: ${vol_m:.1f}M)\n"
            f"💰 Price: ${self.price:.4f} ({direction}{self.price_change_24h:.1f}% 24h)\n"
            f"{sector_line}\n"
            f"⚠️ Risk: HIGH — Low-cap altcoin. DYOR."
        )


# ── Detection logic ───────────────────────────────────────────────────────────


def get_sector(symbol: str) -> Optional[str]:
    """Return the sector name for *symbol* (base token without USDT suffix)."""
    base = symbol.upper().replace("USDT", "").replace("/", "")
    return _TOKEN_SECTOR.get(base)


def is_scam_pump(price_change_24h: float) -> bool:
    """Return True if the 24h price change exceeds the scam pump threshold."""
    return price_change_24h > SPOT_SCAM_PUMP_THRESHOLD_PCT


def detect_dormant_awakening(
    symbol: str,
    volume_24h_usdt: float,
    current_volume: float,
    avg_volume_20: float,
    price: float,
    price_change_24h: float,
    min_volume_spike: float = ALTGEM_MIN_VOLUME_SPIKE,
    max_24h_volume_usdt: int = ALTGEM_MAX_24H_VOLUME_USDT,
) -> Optional[AltgemResult]:
    """
    Detect a dormant awakening pattern.

    Criteria:
    - Volume spike >= min_volume_spike × 20-period average
    - 24h volume < max_24h_volume_usdt (low-cap proxy)
    - NOT a scam pump (24h change <= SPOT_SCAM_PUMP_THRESHOLD_PCT)
    """
    if avg_volume_20 <= 0:
        return None
    volume_ratio = current_volume / avg_volume_20
    if volume_ratio < min_volume_spike:
        return None
    if volume_24h_usdt >= max_24h_volume_usdt:
        return None
    if is_scam_pump(price_change_24h):
        return None
    return AltgemResult(
        symbol=symbol,
        gem_type=GemType.DORMANT_AWAKENING,
        volume_ratio=volume_ratio,
        price=price,
        price_change_24h=price_change_24h,
        volume_24h_usdt=volume_24h_usdt,
        sector=get_sector(symbol),
    )


def calculate_altseason_index(btc_7d_change: float, alt_avg_7d_change: float) -> dict:
    """
    Calculate the altseason index from BTC vs altcoin 7-day returns.

    Returns a dict with:
    - score: float 0–100 (higher = more altseason-y)
    - is_altseason: bool (True if alts outperform BTC by > 5%)
    - label: human-readable label
    """
    diff = alt_avg_7d_change - btc_7d_change
    # Normalise diff to 0-100 scale (diff of +20 → score 100, -20 → 0)
    score = max(0.0, min(100.0, (diff + 20.0) / 40.0 * 100.0))
    is_altseason = diff > 5.0
    label = "Altseason Heating Up 🔥" if is_altseason else "BTC Dominance Phase 🏦"
    return {"score": score, "is_altseason": is_altseason, "label": label, "diff": diff}


def calculate_sector_returns(
    sector_prices: dict[str, dict[str, float]],
) -> dict[str, float]:
    """
    Calculate the weighted 7-day return per sector.

    *sector_prices* maps sector_name → {symbol: 7d_return_pct}.
    Returns sector_name → average_return.
    """
    results: dict[str, float] = {}
    for sector, token_returns in sector_prices.items():
        if not token_returns:
            results[sector] = 0.0
            continue
        results[sector] = sum(token_returns.values()) / len(token_returns)
    return results


def format_sector_rotation(sector_returns: dict[str, float]) -> str:
    """Return a formatted sector rotation message sorted by return (descending)."""
    ranked = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
    lines = ["🔄 SECTOR ROTATION", "──────────────────────────"]
    for i, (sector, ret) in enumerate(ranked, start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        direction = "+" if ret >= 0 else ""
        lines.append(f"{medal} {sector}: {direction}{ret:.1f}% (7d)")
    return "\n".join(lines)


def format_altseason_post(btc_7d_change: float, alt_avg_7d_change: float) -> str:
    """Return a formatted altseason index post."""
    result = calculate_altseason_index(btc_7d_change, alt_avg_7d_change)
    score = result["score"]
    label = result["label"]
    diff = result["diff"]
    bar_filled = int(score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    btc_dir = "+" if btc_7d_change >= 0 else ""
    alt_dir = "+" if alt_avg_7d_change >= 0 else ""
    return (
        f"🌙 ALTSEASON INDEX\n"
        f"──────────────────────────\n"
        f"Score: {score:.0f}/100  [{bar}]\n"
        f"Status: {label}\n"
        f"──────────────────────────\n"
        f"BTC 7d: {btc_dir}{btc_7d_change:.1f}%\n"
        f"Alt avg 7d: {alt_dir}{alt_avg_7d_change:.1f}%\n"
        f"Spread: {'+' if diff >= 0 else ''}{diff:.1f}%"
    )


def get_target_channel_id() -> int:
    """Return the CH6 channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_ALTGEMS
