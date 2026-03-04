# 360 Crypto Eye Scalping — Master Blueprint

This document describes the design and operation of the 360 Crypto Eye Scalping system.

---

## §11 — Backtesting Framework

The backtesting framework in `bot/backtester.py` and `bot/backtest_cli.py` replays historical
candle data through the **exact same** 7-gate confluence engine in `bot/signal_engine.py` to
produce institutional-grade performance reports.

---

### 11.1 Architecture

```
HistoricalDataFetcher
  └─ fetch_historical(symbol, timeframe, start, end) → list[_OHLCVRow]
        Paginates Binance Futures OHLCV API (1,000 candles/request max)

Backtester.run()
  1. Fetch 1D, 4H, 5m data via HistoricalDataFetcher
  2. Slide windows forward one 5m bar at a time
  3. Per bar:
       a. Update active SimulatedTrade objects (_simulate_trade_update)
       b. Scan LONG + SHORT with run_confluence_check() from signal_engine.py
       c. Open SimulatedTrade when signal returned
  4. Force-close remaining open trades (STALE reason)
  5. Aggregate metrics → BacktestResult
```

---

### 11.2 Backtester Class API

```python
Backtester(
    symbol: str,               # CCXT Binance Futures format, e.g. "BTC/USDT:USDT"
    start_date: str,           # "YYYY-MM-DD"
    end_date: str,             # "YYYY-MM-DD"
    be_trigger_fraction: float = 0.50,   # fraction of TP1 distance to trigger BE
    stale_hours: int = 4,                # hours before an open trade is force-closed
    max_same_side: int = 3,              # 3-pair cap per direction
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.5,
    tp3_rr: float = 4.0,
    initial_capital: float = 10_000.0,
    risk_per_trade: float = 0.01,        # fraction of equity risked per trade
)

result: BacktestResult = backtester.run()
```

Sliding windows fed to the signal engine:

| Timeframe | Window size | Purpose                     |
|-----------|-------------|------------------------------|
| 1D        | last 25     | SMA-20 + macro bias          |
| 4H        | last 15     | Range derivation + 4H bias   |
| 5m        | last 50     | MSS, sweep, volume           |

---

### 11.3 SimulatedTrade Lifecycle

```
opened_at (Unix timestamp)
      │
      ▼
[ACTIVE — bars_held increments each 5m candle]
      │
      ├─ SL hit (candle.low ≤ SL for LONG / candle.high ≥ SL for SHORT)
      │     └─ close_reason = "SL"  (or "BE" if be_triggered)
      │
      ├─ TP3 hit → close_reason = "TP3"
      ├─ TP2 hit → close_reason = "TP2"
      ├─ TP1 hit → close_reason = "TP1"
      │
      ├─ BE trigger (price covers be_trigger_fraction of entry→TP1 distance)
      │     └─ stop_loss moved to entry_price; be_triggered = True
      │
      ├─ Stale (time open > stale_hours × 3 600s) → close_reason = "STALE"
      │
      └─ Force-close at end of data range → close_reason = "STALE"
```

**Exit priority order** (conservative worst-case):
1. SL hit first — if both SL and TP are hit on the same candle, SL wins
2. TP3 then TP2 then TP1

---

### 11.4 BacktestResult Fields and Formulas

| Field                       | Formula / Notes                                                    |
|-----------------------------|--------------------------------------------------------------------|
| `win_rate`                  | `wins / total_trades × 100`                                        |
| `profit_factor`             | `gross_profit / gross_loss` (∞ when no losses)                    |
| `sharpe_ratio`              | `(mean_pnl / std_pnl) × sqrt(trades_per_year)`  (annualised)      |
| `max_drawdown_pct`          | Peak-to-trough equity drawdown as a percentage                     |
| `max_drawdown_duration`     | Human-readable length of the longest drawdown period               |
| `calmar_ratio`              | `annualised_return_pct / max_drawdown_pct`                         |
| `avg_max_favorable_excursion` | Mean best unrealised PnL % across all trades                    |
| `avg_max_adverse_excursion` | Mean worst unrealised PnL % across all trades                      |
| `monthly_returns`           | `{YYYY-MM: sum_of_pnl_pct}` for each calendar month               |

**Position sizing (compounding):**
```
sl_frac        = |entry_price - stop_loss| / entry_price
equity_delta   = equity × risk_per_trade × (pnl_pct / 100) / sl_frac
new_equity     = max(equity + equity_delta, 0)
```
This ensures a full SL loss always costs exactly `risk_per_trade` of current equity (e.g. −1 %).

---

### 11.5 CLI Usage

```bash
# Single pair
python -m bot.backtest_cli --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-30

# Custom parameters
python -m bot.backtest_cli --symbol ETH/USDT:USDT \
    --start 2025-01-01 --end 2025-06-30 \
    --capital 5000 --risk 0.005

# Multi-pair (aggregate summary printed at end)
python -m bot.backtest_cli --multi BTC,ETH,SOL \
    --start 2025-01-01 --end 2025-06-30

# Export CSV trade log + text report to directory
python -m bot.backtest_cli --symbol BTC/USDT:USDT \
    --start 2025-01-01 --end 2025-06-30 --export results/

# Quiet mode (summary only, no full report)
python -m bot.backtest_cli --symbol BTC/USDT:USDT \
    --start 2025-01-01 --end 2025-06-30 --quiet
```

**Available flags:**

| Flag            | Default | Description                              |
|-----------------|---------|------------------------------------------|
| `--symbol`      | —       | Single trading pair                      |
| `--multi`       | —       | Comma-separated base symbols             |
| `--start`       | —       | Start date YYYY-MM-DD (required)         |
| `--end`         | —       | End date YYYY-MM-DD (required)           |
| `--capital`     | 10000   | Initial capital in USDT                  |
| `--risk`        | 0.01    | Risk per trade (fraction of equity)      |
| `--tp1-rr`      | 1.5     | TP1 R:R ratio                            |
| `--tp2-rr`      | 2.5     | TP2 R:R ratio                            |
| `--tp3-rr`      | 4.0     | TP3 R:R ratio                            |
| `--no-fvg`      | False   | Disable FVG gate                         |
| `--no-ob`       | False   | Disable Order Block gate                 |
| `--export`      | None    | Directory to export CSV + text report    |
| `--quiet`       | False   | Print summary only                       |

---

### 11.6 Telegram /backtest Command

```
/backtest SYMBOL START_DATE END_DATE
```

Example:
```
/backtest BTC 2025-01-01 2025-06-30
```

The bot sends an acknowledgement ("⏳ Running backtest…") immediately,
runs the backtest in a thread-pool executor (non-blocking), then replies
with the formatted summary when complete.  Admin-only.

---

### 11.7 Go-Live Thresholds

A backtest result is considered ready for live deployment when **all four** of the
following conditions are met:

| Metric             | Threshold    |
|--------------------|--------------|
| Win Rate           | > 55 %       |
| Profit Factor      | > 1.5        |
| Max Drawdown       | < 15 %       |
| Sharpe Ratio       | > 1.0        |

These thresholds are enforced by `BacktestResult.print_report()` which displays a ✅/❌
status line for each one at the bottom of the console report.
