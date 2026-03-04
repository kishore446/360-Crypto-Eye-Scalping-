"""
Backtesting CLI — 360 Crypto Eye Scalping
==========================================
Command-line interface for running historical backtests.

Usage examples::

    python -m bot.backtest_cli --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-30
    python -m bot.backtest_cli --multi BTC,ETH,SOL   --start 2025-01-01 --end 2025-06-30
    python -m bot.backtest_cli --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-30 --export results/

See Blueprint §11 for full CLI reference.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import ccxt

from bot.backtester import Backtester, BacktestResult, HistoricalDataFetcher


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date_to_ms(date_str: str) -> int:
    """Parse ``YYYY-MM-DD`` string to Unix milliseconds (UTC midnight)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _normalise_symbol(sym: str) -> str:
    """
    Convert a short symbol string to the CCXT Binance Futures format
    ``BASE/QUOTE:SETTLE``.

    Examples
    --------
    ``BTC``         → ``BTC/USDT:USDT``
    ``ETH/USDT``    → ``ETH/USDT:USDT``
    ``BTC/USDT:USDT`` → unchanged
    """
    sym = sym.upper().strip()
    if ":" in sym:
        return sym
    if "/" in sym:
        base, quote = sym.split("/", 1)
        return f"{base}/{quote}:{quote}"
    if sym.endswith("USDT"):
        return f"{sym[:-4]}/USDT:USDT"
    if sym.endswith("BTC") and len(sym) > 3:
        return f"{sym[:-3]}/BTC:BTC"
    return f"{sym}/USDT:USDT"


# ── Single-symbol runner ──────────────────────────────────────────────────────

def run_single(
    symbol: str,
    since_ms: int,
    until_ms: int,
    fetcher: HistoricalDataFetcher,
    backtester: Backtester,
    export_dir: Optional[str] = None,
    quiet: bool = False,
) -> BacktestResult:
    """
    Fetch data and run a backtest for one *symbol*.

    Parameters
    ----------
    symbol:
        CCXT Binance Futures format, e.g. ``BTC/USDT:USDT``.
    since_ms / until_ms:
        Unix-millisecond window.
    fetcher:
        Configured :class:`HistoricalDataFetcher` instance.
    backtester:
        Configured :class:`Backtester` instance.
    export_dir:
        If supplied, write per-trade CSV to this directory.
    quiet:
        Suppress informational output.

    Returns
    -------
    BacktestResult
    """
    if not quiet:
        print(f"📥  Fetching historical data for {symbol} …")

    five_min_rows = fetcher.fetch(symbol, "5m", since_ms, until_ms)
    four_h_rows = fetcher.fetch(symbol, "4h", since_ms, until_ms)
    daily_rows = fetcher.fetch(symbol, "1d", since_ms, until_ms)

    if not quiet:
        print(
            f"     5m: {len(five_min_rows):,} candles | "
            f"4H: {len(four_h_rows):,} | "
            f"1D: {len(daily_rows):,}"
        )
        print(f"⚙️   Running backtest for {symbol} …")

    # Use the short base symbol in signal results (e.g. "BTC")
    short_symbol = symbol.split("/")[0]
    result = backtester.run(short_symbol, five_min_rows, four_h_rows, daily_rows)

    if not quiet:
        result.print_report()

    if export_dir is not None:
        os.makedirs(export_dir, exist_ok=True)
        safe_name = symbol.replace("/", "_").replace(":", "_")
        csv_path = os.path.join(export_dir, f"{safe_name}_backtest.csv")
        result.to_csv(csv_path)
        if not quiet:
            print(f"📊  Results exported to {csv_path}")

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> None:
    """Parse arguments and run the backtest(s)."""
    parser = argparse.ArgumentParser(
        prog="python -m bot.backtest_cli",
        description="360 Crypto Eye — Backtesting CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--symbol",
        metavar="SYM",
        help="Single symbol, e.g. BTC/USDT:USDT or BTC",
    )
    group.add_argument(
        "--multi",
        metavar="SYMS",
        help="Comma-separated symbols, e.g. BTC,ETH,SOL",
    )

    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD", help="Start date (UTC)")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD", help="End date (UTC)")
    parser.add_argument("--capital", type=float, default=10_000.0, metavar="USDT",
                        help="Initial capital in USDT")
    parser.add_argument("--risk", type=float, default=0.01, metavar="FRAC",
                        help="Fraction of equity to risk per trade (e.g. 0.01 = 1%%)")
    parser.add_argument("--tp1-rr", type=float, default=1.5, dest="tp1_rr",
                        metavar="RR", help="TP1 risk-reward ratio")
    parser.add_argument("--tp2-rr", type=float, default=2.5, dest="tp2_rr",
                        metavar="RR", help="TP2 risk-reward ratio")
    parser.add_argument("--tp3-rr", type=float, default=4.0, dest="tp3_rr",
                        metavar="RR", help="TP3 risk-reward ratio")
    parser.add_argument("--no-fvg", action="store_true",
                        help="Disable optional FVG confluence gate")
    parser.add_argument("--no-ob", action="store_true",
                        help="Disable optional Order Block confluence gate")
    parser.add_argument("--export", metavar="DIR",
                        help="Directory to write per-trade CSV results")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress all output except errors")

    args = parser.parse_args(argv)

    # Validate dates
    try:
        since_ms = _parse_date_to_ms(args.start)
        until_ms = _parse_date_to_ms(args.end)
    except ValueError as exc:
        print(f"❌  Invalid date format: {exc}", file=sys.stderr)
        sys.exit(1)

    if until_ms <= since_ms:
        print("❌  --end must be after --start", file=sys.stderr)
        sys.exit(1)

    exchange = ccxt.binance({"options": {"defaultType": "future"}})
    fetcher = HistoricalDataFetcher(exchange)
    backtester = Backtester(
        initial_capital=args.capital,
        risk_per_trade=args.risk,
        tp1_rr=args.tp1_rr,
        tp2_rr=args.tp2_rr,
        tp3_rr=args.tp3_rr,
        check_fvg=not args.no_fvg,
        check_order_block=not args.no_ob,
    )

    symbols: list[str] = (
        [_normalise_symbol(args.symbol)]
        if args.symbol
        else [_normalise_symbol(s.strip()) for s in args.multi.split(",") if s.strip()]
    )

    exit_code = 0
    for symbol in symbols:
        try:
            run_single(
                symbol=symbol,
                since_ms=since_ms,
                until_ms=until_ms,
                fetcher=fetcher,
                backtester=backtester,
                export_dir=args.export,
                quiet=args.quiet,
            )
        except Exception as exc:
            print(f"❌  Backtest failed for {symbol}: {exc}", file=sys.stderr)
            exit_code = 1
            if len(symbols) == 1:
                sys.exit(exit_code)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
