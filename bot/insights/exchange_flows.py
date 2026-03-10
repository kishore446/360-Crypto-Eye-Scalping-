"""
CH7 Enhanced — Exchange Flow Alerts & Stablecoin Monitor
Tracks net exchange inflow/outflow and stablecoin supply changes.
"""
from __future__ import annotations

try:
    from config import TELEGRAM_CHANNEL_ID_WHALE
except Exception:  # pragma: no cover
    TELEGRAM_CHANNEL_ID_WHALE = 0

# Threshold in USD for posting an exchange flow alert
_FLOW_THRESHOLD_USD = 50_000_000  # $50M


def format_exchange_flow(
    symbol: str,
    net_flow_usd: float,
    direction: str,
) -> str:
    """
    Return a Telegram-formatted exchange flow alert.

    *net_flow_usd* is the absolute USD value of net flow.
    *direction* is "inflow" (sell pressure) or "outflow" (accumulation signal).
    """
    direction_lower = direction.lower()
    if direction_lower == "inflow":
        icon = "🔴"
        interpretation = "Potential sell pressure — coins moving TO exchanges"
    elif direction_lower == "outflow":
        icon = "🟢"
        interpretation = "Accumulation signal — coins moving FROM exchanges"
    else:
        icon = "⚪"
        interpretation = "Net flow detected"

    base = symbol.replace("USDT", "").replace("/USDT", "")
    flow_m = net_flow_usd / 1_000_000

    return (
        f"{icon} EXCHANGE FLOW ALERT — {base}\n"
        f"──────────────────────────\n"
        f"Direction: {direction.upper()}\n"
        f"Net Flow: ${flow_m:.1f}M\n"
        f"──────────────────────────\n"
        f"📌 {interpretation}"
    )


def should_post_flow_alert(net_flow_usd: float) -> bool:
    """Return True if the net flow exceeds the posting threshold."""
    return abs(net_flow_usd) >= _FLOW_THRESHOLD_USD


def format_stablecoin_monitor(
    usdt_mcap_change: float,
    usdc_mcap_change: float,
) -> str:
    """
    Return a Telegram-formatted stablecoin supply monitor message.

    *usdt_mcap_change* and *usdc_mcap_change* are percentage changes
    in market cap / circulating supply over the period.
    """
    combined = usdt_mcap_change + usdc_mcap_change
    if combined > 0:
        signal = "🟢 Stablecoin supply expanding — new capital entering crypto"
    elif combined < -1:
        signal = "🔴 Stablecoin supply contracting — capital exiting or being deployed"
    else:
        signal = "⚪ Stablecoin supply stable — neutral liquidity conditions"

    usdt_dir = "+" if usdt_mcap_change >= 0 else ""
    usdc_dir = "+" if usdc_mcap_change >= 0 else ""

    return (
        f"💵 STABLECOIN MONITOR\n"
        f"──────────────────────────\n"
        f"USDT Supply: {usdt_dir}{usdt_mcap_change:.2f}%\n"
        f"USDC Supply: {usdc_dir}{usdc_mcap_change:.2f}%\n"
        f"──────────────────────────\n"
        f"📌 {signal}"
    )


def get_target_channel_id() -> int:
    """Return the CH7 whale tracker channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_WHALE
