"""
Backtest CLI — 360 Crypto Eye Scalping
=======================================
Command-line interface for running backtests against Binance Futures history.

Usage examples
--------------
Single symbol, last 90 days:
    python -m bot.backtest_cli --symbol BTCUSDT --start 2024-01-01 --end 2024-04-01

Multiple symbols:
    python -m bot.backtest_cli --multi BTCUSDT ETHUSDT SOLUSDT --start 2024-01-01

Export results to CSV:
    python -m bot.backtest_cli --symbol BTCUSDT --start 2024-01-01 --export results/
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from bot.backtester import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_TP1_RR,
    DEFAULT_TP2_RR,
    DEFAULT_TP3_RR,
    Backtester,
    HistoricalDataFetcher,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> datetime:
    """Parse ``YYYY-MM-DD`` into a UTC-aware datetime."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}' — expected YYYY-MM-DD") from exc


def _to_ms(dt: datetime) -> int:
    """Convert a datetime to Unix milliseconds."""
    return int(dt.timestamp() * 1000)


def _normalise_symbol(raw: str) -> str:
    """Normalise a user-supplied symbol to CCXT Binance Futures format."""
    raw = raw.upper().strip()
    if ":" in raw:
        return raw
    if "/" in raw:
        base, quote = raw.split("/", 1)
    elif raw.endswith("USDT"):
        base = raw[:-4]
        quote = "USDT"
    else:
        base = raw
        quote = "USDT"
    return f"{base}/{quote}:{quote}"


def run_backtest_for_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    capital: float,
    risk: float,
    tp1_rr: float,
    tp2_rr: float,
    tp3_rr: float,
    no_fvg: bool,
    no_ob: bool,
    export_dir: str | None,
    quiet: bool,
    fetcher: HistoricalDataFetcher | None = None,
) -> int:
    """
    Run a single-symbol backtest and optionally export results.

    Parameters
    ----------
    symbol:
        CCXT symbol, e.g. ``"BTC/USDT:USDT"``.
    start / end:
        UTC-aware datetimes bounding the backtest window.
    capital:
        Initial capital in USDT.
    risk:
        Risk per trade as a decimal fraction (e.g. 0.01 for 1 %).
    tp1_rr / tp2_rr / tp3_rr:
        Risk-reward ratios for the three take-profit levels.
    no_fvg:
        If ``True``, disable the optional FVG gate.
    no_ob:
        If ``True``, disable the optional Order Block gate.
    export_dir:
        Directory to write CSV trade log.  ``None`` disables export.
    quiet:
        When ``True`` suppress the full printed report.
    fetcher:
        Optional :class:`HistoricalDataFetcher` override (useful for tests).

    Returns
    -------
    int
        Exit code: ``0`` on success, ``1`` on error.
    """
    if fetcher is None:
        fetcher = HistoricalDataFetcher()

    since_ms = _to_ms(start)
    until_ms = _to_ms(end)

    if not quiet:
        print(f"⏳  Fetching historical data for {symbol} …")

    try:
        candles_5m = fetcher.fetch(symbol, "5m", since_ms, until_ms)
        candles_4h = fetcher.fetch(symbol, "4h", since_ms, until_ms)
        candles_1d = fetcher.fetch(symbol, "1d", since_ms, until_ms)
    except Exception as exc:  # noqa: BLE001
        print(f"❌  Failed to fetch data for {symbol}: {exc}", file=sys.stderr)
        return 1

    if len(candles_5m) < 50 or len(candles_4h) < 2 or len(candles_1d) < 20:
        print(
            f"⚠️   Insufficient data for {symbol}: "
            f"5m={len(candles_5m)}, 4H={len(candles_4h)}, 1D={len(candles_1d)}",
            file=sys.stderr,
        )
        return 1

    if not quiet:
        print(
            f"✅  Fetched {len(candles_5m)} × 5m, "
            f"{len(candles_4h)} × 4H, {len(candles_1d)} × 1D candles"
        )
        print("⚙️   Running backtest …")

    bt = Backtester(
        symbol=symbol,
        five_min_candles=candles_5m,
        four_hour_candles=candles_4h,
        daily_candles=candles_1d,
        tp1_rr=tp1_rr,
        tp2_rr=tp2_rr,
        tp3_rr=tp3_rr,
        initial_capital=capital,
        risk_per_trade=risk,
        check_fvg=not no_fvg,
        check_order_block=not no_ob,
    )

    result = bt.run()

    if not quiet:
        result.print_report()
    else:
        print(result.summary())

    if export_dir:
        os.makedirs(export_dir, exist_ok=True)
        base_name = symbol.replace("/", "_").replace(":", "_")
        csv_path = os.path.join(export_dir, f"{base_name}_backtest.csv")
        result.to_csv(csv_path)
        if not quiet:
            print(f"📄  Results exported to {csv_path}")

    return 0


# ── Argument parser ───────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bot.backtest_cli",
        description="360 Crypto Eye Scalping — Backtesting CLI",
    )

    # Target symbol(s)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--symbol", metavar="SYM", help="Single symbol, e.g. BTCUSDT")
    target.add_argument(
        "--multi", nargs="+", metavar="SYM", help="Multiple symbols, e.g. BTCUSDT ETHUSDT"
    )

    # Date range
    parser.add_argument(
        "--start", required=True, type=_parse_date, metavar="YYYY-MM-DD",
        help="Backtest start date (UTC)"
    )
    parser.add_argument(
        "--end", type=_parse_date, metavar="YYYY-MM-DD",
        default=datetime.now(tz=timezone.utc),
        help="Backtest end date (UTC, default: today)"
    )

    # Capital & risk
    parser.add_argument(
        "--capital", type=float, default=DEFAULT_INITIAL_CAPITAL,
        metavar="USDT", help=f"Initial capital in USDT (default: {DEFAULT_INITIAL_CAPITAL:,.0f})"
    )
    parser.add_argument(
        "--risk", type=float, default=DEFAULT_RISK_PER_TRADE,
        metavar="FRAC", help=f"Risk fraction per trade (default: {DEFAULT_RISK_PER_TRADE})"
    )

    # R:R ratios
    parser.add_argument("--tp1-rr", type=float, default=DEFAULT_TP1_RR, metavar="RR")
    parser.add_argument("--tp2-rr", type=float, default=DEFAULT_TP2_RR, metavar="RR")
    parser.add_argument("--tp3-rr", type=float, default=DEFAULT_TP3_RR, metavar="RR")

    # Gates
    parser.add_argument(
        "--no-fvg", action="store_true",
        help="Disable the optional Fair Value Gap gate"
    )
    parser.add_argument(
        "--no-ob", action="store_true",
        help="Disable the optional Order Block gate"
    )

    # Output
    parser.add_argument("--export", metavar="DIR", help="Export CSV results to this directory")
    parser.add_argument("--quiet", action="store_true", help="Print summary only (no full report)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI.  Returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    symbols: list[str]
    if args.symbol:
        symbols = [_normalise_symbol(args.symbol)]
    else:
        symbols = [_normalise_symbol(s) for s in args.multi]

    overall_rc = 0
    for sym in symbols:
        rc = run_backtest_for_symbol(
            symbol=sym,
            start=args.start,
            end=args.end,
            capital=args.capital,
            risk=args.risk,
            tp1_rr=args.tp1_rr,
            tp2_rr=args.tp2_rr,
            tp3_rr=args.tp3_rr,
            no_fvg=args.no_fvg,
            no_ob=args.no_ob,
            export_dir=args.export,
            quiet=args.quiet,
        )
        if rc != 0:
            overall_rc = rc

    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
