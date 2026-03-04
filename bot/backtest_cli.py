"""
bot/backtest_cli.py — Command-Line Interface for the 360 Crypto Eye Backtester
================================================================================

Usage examples
--------------
Single pair:
    python -m bot.backtest_cli --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-30

Multi-pair:
    python -m bot.backtest_cli --multi BTC,ETH,SOL --start 2025-01-01 --end 2025-06-30

Custom parameters:
    python -m bot.backtest_cli --symbol ETH/USDT:USDT \\
        --start 2025-01-01 --end 2025-06-30 \\
        --capital 5000 --risk 0.005

Export results:
    python -m bot.backtest_cli --symbol BTC/USDT:USDT \\
        --start 2025-01-01 --end 2025-06-30 --export results/
"""

from __future__ import annotations

import argparse
import os
import sys

from bot.backtester import Backtester, BacktestResult


def _normalise_symbol(raw: str) -> str:
    """Convert short base symbol (e.g. ``BTC``) to CCXT futures format."""
    raw = raw.upper().strip()
    if ":" in raw:
        return raw
    if "/" in raw:
        base, quote = raw.split("/", 1)
        return f"{base}/{quote}:{quote}"
    if raw.endswith("USDT"):
        base = raw[:-4]
        return f"{base}/USDT:USDT"
    return f"{raw}/USDT:USDT"


def _run_single(args: argparse.Namespace, symbol: str) -> BacktestResult:
    """Run a backtest for one *symbol* and return the result."""
    bt = Backtester(
        symbol=symbol,
        start_date=args.start,
        end_date=args.end,
        tp1_rr=args.tp1_rr,
        tp2_rr=args.tp2_rr,
        tp3_rr=args.tp3_rr,
        check_fvg=not args.no_fvg,
        check_order_block=not args.no_ob,
        initial_capital=args.capital,
        risk_per_trade=args.risk,
    )
    return bt.run()


def _export(result: BacktestResult, directory: str, symbol_slug: str) -> None:
    """Save CSV trade log and text report to *directory*."""
    os.makedirs(directory, exist_ok=True)

    csv_path = os.path.join(directory, f"{symbol_slug}_trades.csv")
    result.to_csv(csv_path)
    print(f"  CSV exported → {csv_path}")

    report_path = os.path.join(directory, f"{symbol_slug}_report.txt")
    # Redirect print_report output to file
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result.print_report()
    with open(report_path, "w") as fh:
        fh.write(buf.getvalue())
    print(f"  Report exported → {report_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="360 Crypto Eye Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--symbol",
        type=str,
        help="Trading pair, e.g. BTC/USDT:USDT or just BTC",
    )
    group.add_argument(
        "--multi",
        type=str,
        help="Comma-separated base symbols for multi-pair backtest, e.g. BTC,ETH,SOL",
    )
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital (default: 10000)")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade fraction (default: 0.01)")
    parser.add_argument("--tp1-rr", type=float, default=1.5, dest="tp1_rr", help="TP1 R:R ratio (default: 1.5)")
    parser.add_argument("--tp2-rr", type=float, default=2.5, dest="tp2_rr", help="TP2 R:R ratio (default: 2.5)")
    parser.add_argument("--tp3-rr", type=float, default=4.0, dest="tp3_rr", help="TP3 R:R ratio (default: 4.0)")
    parser.add_argument("--no-fvg", action="store_true", help="Disable FVG gate")
    parser.add_argument("--no-ob", action="store_true", help="Disable Order Block gate")
    parser.add_argument("--export", type=str, default=None, help="Export directory for CSV + report")
    parser.add_argument("--quiet", action="store_true", help="Only print summary, no detailed report")

    args = parser.parse_args(argv)

    if args.symbol is None and args.multi is None:
        parser.error("Provide --symbol or --multi.")

    # Build list of symbols to backtest
    if args.multi:
        symbols = [
            _normalise_symbol(s.strip())
            for s in args.multi.split(",")
            if s.strip()
        ]
    else:
        symbols = [_normalise_symbol(args.symbol)]

    results: list[BacktestResult] = []
    for sym in symbols:
        print(f"\n⏳ Running backtest for {sym}  ({args.start} → {args.end}) …")
        try:
            result = _run_single(args, sym)
        except Exception as exc:
            print(f"  ❌ Error: {exc}", file=sys.stderr)
            continue

        results.append(result)

        if args.quiet:
            print(result.summary())
        else:
            result.print_report()

        if args.export:
            slug = sym.replace("/", "_").replace(":", "_")
            _export(result, args.export, slug)

    if len(results) > 1:
        print("\n" + "═" * 60)
        print(" MULTI-PAIR AGGREGATE SUMMARY")
        print("═" * 60)
        total_trades = sum(r.total_trades for r in results)
        total_wins = sum(r.wins for r in results)
        overall_wr = total_wins / total_trades * 100 if total_trades else 0.0
        print(f"  Symbols    : {', '.join(r.symbol for r in results)}")
        print(f"  Total Trades: {total_trades}  (wins {total_wins})")
        print(f"  Overall WR  : {overall_wr:.1f}%")
        for r in results:
            net = (r.final_capital - r.initial_capital) / r.initial_capital * 100
            print(f"  {r.symbol:<20} WR={r.win_rate:.1f}%  PF={r.profit_factor:.2f}  Net={net:+.2f}%")
        print("═" * 60)


if __name__ == "__main__":
    main()
