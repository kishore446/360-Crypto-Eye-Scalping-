"""
CH9 — VIP Features
Portfolio tracker, risk calculator, custom price alerts,
and signal performance replay for premium subscribers.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from config import (
        TELEGRAM_CHANNEL_ID_VIP,
        VIP_MAX_ALERTS_PER_USER,
        VIP_MAX_PORTFOLIO_ENTRIES,
    )
except Exception:  # pragma: no cover
    TELEGRAM_CHANNEL_ID_VIP = 0
    VIP_MAX_PORTFOLIO_ENTRIES = 50
    VIP_MAX_ALERTS_PER_USER = 20

# ── Portfolio Tracker ─────────────────────────────────────────────────────────


@dataclass
class PortfolioEntry:
    """A single portfolio position."""

    symbol: str
    quantity: float
    entry_price: float
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# In-memory storage keyed by user chat_id
_portfolios: dict[int, list[PortfolioEntry]] = {}
_portfolio_lock = threading.Lock()


def add_position(
    chat_id: int,
    symbol: str,
    quantity: float,
    entry_price: float,
) -> None:
    """Add or update a portfolio position for *chat_id*."""
    symbol = symbol.upper()
    with _portfolio_lock:
        entries = _portfolios.setdefault(chat_id, [])
        # Update existing symbol if present
        for entry in entries:
            if entry.symbol == symbol:
                entry.quantity = quantity
                entry.entry_price = entry_price
                entry.added_at = datetime.now(timezone.utc)
                return
        if len(entries) >= VIP_MAX_PORTFOLIO_ENTRIES:
            raise ValueError(
                f"Portfolio limit reached ({VIP_MAX_PORTFOLIO_ENTRIES} positions). "
                "Remove a position first."
            )
        entries.append(PortfolioEntry(symbol=symbol, quantity=quantity, entry_price=entry_price))


def remove_position(chat_id: int, symbol: str) -> bool:
    """
    Remove a position from *chat_id*'s portfolio.

    Returns True if removed, False if not found.
    """
    symbol = symbol.upper()
    with _portfolio_lock:
        entries = _portfolios.get(chat_id, [])
        before = len(entries)
        _portfolios[chat_id] = [e for e in entries if e.symbol != symbol]
        return len(_portfolios[chat_id]) < before


def get_portfolio_summary(chat_id: int, current_prices: dict[str, float]) -> str:
    """
    Return a formatted portfolio summary for *chat_id*.

    *current_prices* maps symbol (e.g. "BTCUSDT") → current price.
    """
    entries = _portfolios.get(chat_id, [])
    if not entries:
        return "📊 Your portfolio is empty. Use /portfolio add <SYMBOL> <QTY> <PRICE> to add positions."

    lines = ["📊 VIP PORTFOLIO", "─────────────────────────────"]
    total_value = 0.0
    total_cost = 0.0

    for entry in entries:
        symbol_key = entry.symbol if entry.symbol.endswith("USDT") else entry.symbol + "USDT"
        current = current_prices.get(symbol_key, current_prices.get(entry.symbol, entry.entry_price))
        value = entry.quantity * current
        cost = entry.quantity * entry.entry_price
        pnl_abs = value - cost
        pnl_pct = (pnl_abs / cost * 100) if cost > 0 else 0.0
        icon = "✅" if pnl_abs >= 0 else "🔻"
        direction = "+" if pnl_abs >= 0 else ""
        base = entry.symbol.replace("USDT", "")
        lines.append(
            f"{base}: {entry.quantity} @ ${entry.entry_price:,.2f} → "
            f"${current:,.2f} ({direction}{pnl_pct:.2f}%) {icon}"
        )
        total_value += value
        total_cost += cost

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
    direction = "+" if total_pnl >= 0 else ""
    lines.append("─────────────────────────────")
    lines.append(
        f"Total P&L: {direction}${total_pnl:,.2f} ({direction}{total_pnl_pct:.2f}%)"
    )
    return "\n".join(lines)


# ── Risk Calculator ───────────────────────────────────────────────────────────


def calculate_risk(
    balance: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = 1.0,
    take_profit: Optional[float] = None,
) -> dict:
    """
    Calculate position sizing based on risk parameters.

    Returns a dict with:
    - position_size: USD value to risk
    - quantity: number of units to buy
    - potential_loss: absolute dollar loss if SL hit
    - risk_reward: R:R ratio (if take_profit provided, else None)
    - risk_amount: USD risked
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if stop_loss <= 0:
        raise ValueError("stop_loss must be positive")
    if balance <= 0:
        raise ValueError("balance must be positive")
    if risk_pct <= 0:
        raise ValueError("risk_pct must be positive")

    risk_amount = balance * (risk_pct / 100.0)
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance == 0:
        raise ValueError("entry_price and stop_loss cannot be equal")

    quantity = risk_amount / sl_distance
    position_size = quantity * entry_price
    potential_loss = quantity * sl_distance  # = risk_amount

    result: dict = {
        "position_size": round(position_size, 2),
        "quantity": quantity,
        "potential_loss": round(potential_loss, 2),
        "risk_amount": round(risk_amount, 2),
        "risk_reward": None,
    }

    if take_profit is not None:
        tp_distance = abs(take_profit - entry_price)
        result["risk_reward"] = round(tp_distance / sl_distance, 2) if sl_distance > 0 else None

    return result


def format_risk_calculator(
    balance: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = 1.0,
    take_profit: Optional[float] = None,
    symbol: str = "BTC",
) -> str:
    """Return a Telegram-formatted risk calculator result."""
    calc = calculate_risk(balance, entry_price, stop_loss, risk_pct, take_profit)
    lines = [
        "🧮 RISK CALCULATOR",
        f"Balance: ${balance:,.2f} | Risk: {risk_pct}%",
        f"Entry: ${entry_price:,.2f} | SL: ${stop_loss:,.2f}",
        "──────────────────────",
        f"Position Size: ${calc['position_size']:,.2f}",
        f"Quantity: {calc['quantity']:.6g} {symbol}",
        f"Risk Amount: ${calc['risk_amount']:,.2f}",
    ]
    if calc["risk_reward"] is not None and take_profit is not None:
        lines.append(f"TP: ${take_profit:,.2f} | R:R = 1:{calc['risk_reward']}")
    return "\n".join(lines)


# ── Custom Price Alerts ───────────────────────────────────────────────────────


@dataclass
class PriceAlert:
    """A user-defined price alert."""

    symbol: str
    direction: str  # "above" or "below"
    target_price: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TriggeredAlert:
    """A price alert that has been triggered."""

    chat_id: int
    alert: PriceAlert
    current_price: float


# In-memory storage keyed by user chat_id
_alerts: dict[int, list[PriceAlert]] = {}
_alerts_lock = threading.Lock()


def add_alert(
    chat_id: int,
    symbol: str,
    direction: str,
    target_price: float,
) -> None:
    """Add a price alert for *chat_id*."""
    direction = direction.lower()
    if direction not in ("above", "below"):
        raise ValueError("direction must be 'above' or 'below'")
    symbol = symbol.upper()
    with _alerts_lock:
        alerts = _alerts.setdefault(chat_id, [])
        if len(alerts) >= VIP_MAX_ALERTS_PER_USER:
            raise ValueError(
                f"Alert limit reached ({VIP_MAX_ALERTS_PER_USER} alerts). "
                "Remove an alert first with /alert remove <SYMBOL>."
            )
        alerts.append(PriceAlert(symbol=symbol, direction=direction, target_price=target_price))


def remove_alert(chat_id: int, symbol: str) -> bool:
    """
    Remove all alerts for *symbol* from *chat_id*.

    Returns True if any were removed.
    """
    symbol = symbol.upper()
    with _alerts_lock:
        alerts = _alerts.get(chat_id, [])
        before = len(alerts)
        _alerts[chat_id] = [a for a in alerts if a.symbol != symbol]
        return len(_alerts[chat_id]) < before


def check_alerts(current_prices: dict[str, float]) -> list[TriggeredAlert]:
    """
    Check all alerts against *current_prices* and return triggered ones.

    Triggered alerts are removed from storage.
    *current_prices* maps symbol (e.g. "BTCUSDT" or "BTC") → price.
    """
    triggered: list[TriggeredAlert] = []
    with _alerts_lock:
        for chat_id, alerts in list(_alerts.items()):
            still_pending: list[PriceAlert] = []
            for alert in alerts:
                symbol_key = (
                    alert.symbol if alert.symbol.endswith("USDT") else alert.symbol + "USDT"
                )
                price = current_prices.get(symbol_key, current_prices.get(alert.symbol))
                if price is None:
                    still_pending.append(alert)
                    continue
                hit = (alert.direction == "above" and price >= alert.target_price) or (
                    alert.direction == "below" and price <= alert.target_price
                )
                if hit:
                    triggered.append(
                        TriggeredAlert(chat_id=chat_id, alert=alert, current_price=price)
                    )
                else:
                    still_pending.append(alert)
            _alerts[chat_id] = still_pending
    return triggered


# ── Signal Performance Replay ─────────────────────────────────────────────────


def format_signal_replay(dashboard: object, days: int = 7) -> str:
    """
    Return a formatted performance replay for the last *days* days.

    *dashboard* must have a `trades` attribute (list of TradeResult-like objects
    with `symbol`, `pnl_pct`, `closed_at`, `side` attributes).
    """
    try:
        trades = list(getattr(dashboard, "trades", []))
    except Exception:
        return "📈 No signal history available."

    if not trades:
        return "📈 No signals in the replay window."

    cutoff = datetime.now(timezone.utc)
    recent = []
    for trade in trades:
        closed_at = getattr(trade, "closed_at", None)
        if closed_at is None:
            continue
        if isinstance(closed_at, str):
            try:
                closed_at = datetime.fromisoformat(closed_at)
            except ValueError:
                continue
        # Handle both naive and aware datetimes for compatibility
        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone.utc)
        if (cutoff - closed_at).days <= days:
            recent.append(trade)

    if not recent:
        return f"📈 No closed signals in the last {days} days."

    wins = sum(1 for t in recent if getattr(t, "pnl_pct", 0) > 0)
    losses = len(recent) - wins
    total_pnl = sum(getattr(t, "pnl_pct", 0) for t in recent)
    win_rate = (wins / len(recent) * 100) if recent else 0

    lines = [
        f"📈 SIGNAL REPLAY — Last {days} Days",
        "─────────────────────────────",
    ]
    for trade in recent[-10:]:  # Show last 10 signals
        symbol = getattr(trade, "symbol", "???")
        pnl = getattr(trade, "pnl_pct", 0)
        side = getattr(trade, "side", "")
        icon = "✅" if pnl > 0 else "❌"
        direction = "+" if pnl >= 0 else ""
        lines.append(f"{icon} {symbol} [{side}]: {direction}{pnl:.1f}%")

    lines += [
        "─────────────────────────────",
        f"Win Rate: {win_rate:.0f}% ({wins}W / {losses}L)",
        f"Total PnL: {'+' if total_pnl >= 0 else ''}{total_pnl:.1f}%",
    ]
    return "\n".join(lines)


def get_target_channel_id() -> int:
    """Return the CH9 channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_VIP
