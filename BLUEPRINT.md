# 360 Crypto Eye Scalping — Institutional Master Blueprint

**Version:** `4.0.0-domination`  
**Status:** Canonical Authority — if code differs from this document, the code is wrong.  
**Purpose:** Single source of truth for architecture, strategy, modules, safety protocols, and deployment.

> **How to cite:** Use section numbers, e.g. "see Blueprint §3.2.4" when referencing this document in code comments, PRs, or issue trackers.

---

## Table of Contents

- [§1 — System Overview & Mission Statement](#1--system-overview--mission-statement)
- [§2 — Core Strategy: Fractal Liquidity Engine](#2--core-strategy-fractal-liquidity-engine)
  - [§2.1 Multi-Timeframe Layers](#21-multi-timeframe-layers)
  - [§2.2 Entry Logic Gate — ALL 7 Conditions Must Pass](#22-entry-logic-gate--all-7-conditions-must-pass)
  - [§2.3 BTC Correlation Gate](#23-btc-correlation-gate-for-altcoins)
  - [§2.4 Target Calculation](#24-target-calculation)
  - [§2.5 ATR-Based Dynamic Zones](#25-atr-based-dynamic-zones)
  - [§2.6 Confidence Scoring](#26-confidence-scoring)
  - [§2.7 Gate ⑧ Funding Rate Sentiment](#27-gate--funding-rate-sentiment)
  - [§2.8 Gate ⑨ Open Interest Divergence](#28-gate--open-interest-divergence)
- [§3 — Module-by-Module Specification](#3--module-by-module-specification)
  - [§3.1 config.py](#31-configpy--centralised-configuration)
  - [§3.2 bot/signal_engine.py](#32-botsignal_enginepy--fractal-liquidity-engine)
  - [§3.3 bot/risk_manager.py](#33-botrisk_managerpy--safety-protocols)
  - [§3.4 bot/bot.py](#34-botbotpy--telegram-bot--command-handlers)
  - [§3.5 bot/webhook.py](#35-botwebhookpy--tradingview-webhook-receiver)
  - [§3.6 bot/dashboard.py](#36-botdashboardpy--transparency-dashboard)
  - [§3.7 bot/news_filter.py](#37-botnews_filterpy--news-calendar)
  - [§3.8 bot/state.py](#38-botstatepy--thread-safe-bot-state)
  - [§3.9 bot/exchange.py](#39-botexchangepy--resilient-exchange-client)
  - [§3.10 bot/database.py](#310-botdatabasepy--sqlitesqlalchemy-persistence)
  - [§3.11 bot/logging_config.py](#311-botlogging_configpy--structured-logging)
  - [§3.12 bot/session_filter.py](#312-botsession_filterpy--trading-session-gate)
  - [§3.13 bot/funding_rate.py](#313-botfunding_ratepy--funding-rate-gate)
  - [§3.14 bot/open_interest.py](#314-botopen_interestpy--open-interest-monitor)
  - [§3.15 bot/loss_streak_cooldown.py](#315-botloss_streak_cooldownpy--loss-streak-cooldown)
  - [§3.16 bot/spot_scanner.py](#316-botspot_scannerpy--spot-market-scanner)
  - [§3.17 bot/ws_manager.py](#317-botws_managerpy--websocket-market-data-manager)
  - [§3.18 bot/regime_adapter.py](#318-botregime_adapterpy--regime-adaptive-parameters)
  - [§3.19 bot/insights/regime_detector.py](#319-botinsightsregime_detectorpy--market-regime-classifier)
  - [§3.20 bot/weekly_report.py](#320-botweekly_reportpy--weekly-performance-report)
  - [§3.21 bot/gate_labels.py](#321-botgate_labelspy--gate-label-registry)
  - [§3.22 bot/price_fmt.py](#322-botprice_fmtpy--adaptive-price-formatter)
- [§4 — Signal Broadcast Template](#4--signal-broadcast-template)
- [§5 — Safety Protocols](#5--safety-protocols-complete-reference)
- [§6 — Dashboard Parameters & Formulas](#6--dashboard-parameters--formulas)
- [§7 — Deployment & Infrastructure](#7--deployment--infrastructure)
- [§8 — Testing Standards](#8--testing-standards)
- [§9 — File Tree (Canonical)](#9--file-tree-canonical)
- [§10 — Coding Standards & Conventions](#10--coding-standards--conventions)
- [§11 — Backtesting Framework](#11--backtesting-framework)
- [§12 — v2.0 Multi-Channel System](#12--v20-multi-channel-system)
- [§13 — Competitive Edge: Why 360 Eye Dominates](#13--competitive-edge-why-360-eye-dominates)

---

## §1 — System Overview & Mission Statement

### §1.1 Mission

360 Crypto Eye Scalping is an **institutional-grade multi-timeframe confluence signal engine** for Binance Futures scalping, delivered via Telegram. It is not a simple alert bot — it is a complete signal lifecycle management system with:

- Multi-timeframe confluence analysis (1D + 4H + 15m + 5m)
- Automated safety protocols (break-even, cap enforcement, stale-close)
- Transparency dashboard with real-time performance metrics
- News-blackout protection against high-impact macro events
- TradingView webhook integration + autonomous background scanning

360 Crypto Eye is engineered to be the **definitive all-rounder crypto channel group** —
sitting above every institutional-level professional crypto channel in existence. Where
competitors offer one signal feed, we deliver a **5-channel ecosystem** with differentiated
risk tiers, real-time market intelligence, autonomous risk management, and institutional-
grade transparency that no paid group can match. Our edge: full automation with zero
manual intervention, battle-tested confluence logic, and a relentless focus on protecting
capital before chasing profits.

### §1.2 Architecture Data Flow

```
TradingView Webhook / Auto-Scanner
        │
        ▼
bot/webhook.py (Flask — secret verification, payload validation, rate limiting, IP allowlist)
        │
        ▼
bot/exchange.py (ResilientExchange — circuit breaker, exponential backoff, TTL cache)
        │
        ▼
bot/signal_engine.py (Fractal Liquidity Engine — 7-gate confluence)
        │
        ▼
bot/risk_manager.py (Thread-safe — 3-pair cap, BE trigger, stale-close)
        │
        ▼
bot/database.py (SQLite/SQLAlchemy — audit trail, signal lifecycle)
        │
        ▼
Telegram Bot API → Channel broadcast
        │
        ▼
bot/dashboard.py (Sharpe, drawdown, equity curve, win-rate by TF)
```

### §1.3 Version

`4.0.0-domination`

### §1.4 Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Telegram integration | python-telegram-bot 21.x |
| HTTP webhook receiver | Flask 3.x + Gunicorn |
| Scheduling | APScheduler 3.x |
| Exchange data | CCXT 4.x (Binance Futures) |
| Persistence | SQLite via SQLAlchemy |
| Configuration | Pydantic Settings / `os.environ` |
| Testing | pytest + pytest-asyncio |

---

## §2 — Core Strategy: Fractal Liquidity Engine

The Fractal Liquidity Engine is a **7-gate confluence system**. A trade signal is only generated when **all seven gates pass simultaneously**. If any single gate fails, the signal is suppressed.

### §2.1 Multi-Timeframe Layers

| Layer | Timeframe | Purpose | Implementation |
|---|---|---|---|
| Market Bias | 1D & 4H | Trend direction filter | `assess_macro_bias()` — 1D: close > prev close AND > SMA-20; 4H: close > prev close; both must agree |
| Setup | 15m | Order Block & FVG identification | `detect_order_block()`, `detect_fair_value_gap()` |
| Execution | 5m | MSS/ChoCh + Volume trigger | `detect_market_structure_shift()` with displacement filter |

### §2.2 Entry Logic Gate — ALL 7 Conditions Must Pass

Each gate is described with its function, exact logic, and failure condition.

#### Gate ① — Macro Bias (1D + 4H Alignment)

**Function:** `assess_macro_bias(daily_candles, four_hour_candles) -> Optional[Side]`

**Logic:**
- **1D Bullish** = `daily_candles[-1].close > daily_candles[-2].close` AND `daily_candles[-1].close > SMA_20_daily`
- **1D Bearish** = `daily_candles[-1].close < daily_candles[-2].close` AND `daily_candles[-1].close < SMA_20_daily`
- **4H Bullish** = `four_hour_candles[-1].close > four_hour_candles[-2].close`
- **4H Bearish** = `four_hour_candles[-1].close < four_hour_candles[-2].close`
- If 4H is **neutral** (no clear direction): the function returns the 1D bias directly (not suppressed)
- Full agreement: `(1D bullish AND 4H bullish)` → `Side.LONG`; `(1D bearish AND 4H bearish)` → `Side.SHORT`

**Minimum data:** 20 daily candles, 2 four-hour candles.

**Failure:** Returns `None` **only** when 1D and 4H give **conflicting** signals (e.g. 1D bullish but 4H bearish). When 4H is neutral, the 1D bias is returned directly. Signal is suppressed only on true conflict.

**SMA-20 formula:**
```
sma20_daily = sum(c.close for c in daily_candles[-20:]) / 20
```

#### Gate ② — Discount/Premium Zone

**Functions:**
- `is_discount_zone(price, range_low, range_high) -> bool`
- `is_premium_zone(price, range_low, range_high) -> bool`

**Logic:**
```
midpoint = (range_low + range_high) / 2
LONG entry: price <= midpoint   (lower 50% = discount zone)
SHORT entry: price >= midpoint  (upper 50% = premium zone)
```

**Range derivation:** `range_low` and `range_high` come from the lowest low and highest high of the last 10 4H candles respectively.

**Failure:** Price is outside the expected zone for the intended direction.

#### Gate ③ — Liquidity Sweep

**Function:** `detect_liquidity_sweep(candles, key_level, side) -> bool`

**Logic:** Checks last **15** candles (~75 minutes of 5m data). A sweep is a wick that pierces the key level with the body closing back on the opposite side:
- **LONG sweep:** `candle.low < key_level AND candle.close > key_level` (stop-hunt of longs)
- **SHORT sweep:** `candle.high > key_level AND candle.close < key_level` (stop-hunt of shorts)

**Key level derivation (see §3.9):**
- LONG = lowest low of last 10 5m candles
- SHORT = highest high of last 10 5m candles

**Failure:** No candle in the last 15 has swept the key level.

#### Gate ④ — Market Structure Shift (MSS/ChoCh)

**Function:** `detect_market_structure_shift(candles, side) -> bool`

**Logic:**
- Requires minimum 3 candles.
- Computes `avg_vol = sum(c.volume for c in candles) / len(candles)`
- **LONG MSS:** `last_candle.close > max(c.high for c in prior_candles) AND last_candle.volume > avg_vol`
- **SHORT MSS:** `last_candle.close < min(c.low for c in prior_candles) AND last_candle.volume > avg_vol`

**Displacement filter (ATR-adaptive):** The break must exceed an ATR-based threshold to filter false breakouts:
```
displacement = abs(last_candle.close - swing_level)
# When atr > 0 (preferred):
PASS if displacement >= 0.3 * atr
# Fallback when atr == 0:
displacement_pct = displacement / last_candle.close
PASS if displacement_pct >= 0.0015   (0.15% of price)
```

When the `atr` parameter is provided and positive, the threshold is `0.3 × ATR` (adaptive to current volatility). When `atr` is zero or not provided, falls back to the fixed 0.15% threshold.

**Function signature:**
```python
def detect_market_structure_shift(candles: list[CandleData], side: Side, atr: float = 0.0) -> bool
```

**Failure:** Last candle does not break the prior swing with above-average volume, or fewer than 3 candles provided.

#### Gate ⑤ — News Blackout

**Function:** `news_calendar.is_high_impact_imminent() -> bool`

**Logic:** Returns `True` if any HIGH-impact event is scheduled within the next `NEWS_SKIP_WINDOW_MINUTES` (default 60) minutes.

**Data source:** CoinMarketCal API (refreshed every 30 minutes by background scheduler). Falls back to manual `add_event()` if no API key configured.

**Failure:** `is_high_impact_imminent()` returns `True`. Signal is suppressed — no trade during macro events.

#### Gate ⑥ — Fair Value Gap (FVG)

**Function:** `detect_fair_value_gap(candles, side) -> bool`

**Logic (3-candle pattern):**
- **Bullish FVG:** `candles[-1].low > candles[-3].high` (gap between candle 1 and candle 3)
- **Bearish FVG:** `candles[-1].high < candles[-3].low`

This indicates an imbalance in price delivery that price will likely return to fill, confirming institutional order flow.

**Failure:** No FVG present in the recent candle sequence. This gate provides **optional additional confluence** — its weight influences confidence scoring (§2.6) but does not block the signal if other gates pass.

#### Gate ⑦ — Order Block (OB)

**Function:** `detect_order_block(candles, side) -> bool`

**Logic:** Identifies the **last opposing candle before an impulse move**.
- **Bullish OB:** The last bearish (red) candle before a strong bullish displacement.  
  Condition: Scan backwards through `candles[-5:]`; find the last candle where `close < open` followed by a candle where `close > open * 1.001` (at least 0.1% bullish displacement).
- **Bearish OB:** The last bullish (green) candle before a strong bearish displacement.

**Failure:** No order block structure identifiable. This gate also provides **optional additional confluence** — influences confidence scoring but does not block if minimum gates pass.

### §2.3 BTC Correlation Gate (for Altcoins)

**Function:** `btc_correlation_check(btc_candles, signal_side) -> bool`

**Logic:** When scanning altcoins, the BTC macro bias (§2.2 Gate ①) must agree with the signal direction:
- If BTC is **bearish**: suppress all altcoin **LONG** signals
- If BTC is **bullish**: suppress all altcoin **SHORT** signals
- If BTC bias is `None` (conflicted): allow altcoin signals to proceed on their own merit

**Implementation:** Called inside the auto-scanner loop for every non-BTC pair. BTC candles are fetched once per scan cycle and cached.

### §2.4 Target Calculation

**Function:** `calculate_targets(entry, stop_loss, side, tp1_rr, tp2_rr, tp3_rr) -> tuple[float, float, float]`

**Formula:**
```
risk = abs(entry - stop_loss)
direction = 1 if side == LONG else -1
tp1 = entry + direction * risk * tp1_rr
tp2 = entry + direction * risk * tp2_rr
tp3 = entry + direction * risk * tp3_rr
```

**Default R:R ratios** (configurable via `config.py`):
- TP1 = **1.5R** (close 50% of position, move SL to entry)
- TP2 = **2.5R** (close 25% of position, start trailing)
- TP3 = **4.0R** (final moon bag — let it run)

**Entry mid-point used as basis:** `entry = (entry_low + entry_high) / 2`

### §2.5 ATR-Based Dynamic Zones

**Function:** `calculate_atr(candles, period=14) -> float`

**True Average True Range (ATR) formula:**
```
For each candle i (after the first):
  true_range[i] = max(
      high[i] - low[i],
      abs(high[i] - close[i-1]),
      abs(low[i] - close[i-1])
  )
ATR = sum(true_range[-period:]) / period
```

**Application:**
- **Entry zone width** = `ATR * 0.5` (replaces hardcoded 0.1%)
- **Stop-loss buffer** = `ATR * 0.3` beyond the key structural level (replaces hardcoded 1% of range)

This ensures zones dynamically adapt to current volatility conditions rather than using fixed percentages.

### §2.6 Confidence Scoring

The `Confidence` enum determines how the signal is labelled and what position sizing to apply.

| Confidence | Condition | Meaning |
|---|---|---|
| `HIGH` | 4H direction agrees AND FVG present AND OB present | Full institutional setup — maximum conviction |
| `MEDIUM` | 4H direction agrees (minimum passing condition) | Valid setup — standard position size |
| `LOW` | Only basic gates (①②③④⑤) pass | Edge case — reduce position size, tighter SL |

**Implementation in `run_confluence_check`:**
```python
if direction_match and fvg_present and ob_present:
    confidence = Confidence.HIGH
elif direction_match:
    confidence = Confidence.MEDIUM
else:
    confidence = Confidence.LOW
```

---

### §2.7 Gate ⑧ Funding Rate Sentiment

**Module:** `bot/funding_rate.py`

An **optional** confidence modifier that uses Binance Futures funding rates as a contrarian sentiment signal:

| Condition | Signal Direction | Effect |
|-----------|-----------------|--------|
| Extreme negative funding (<-0.01%) | LONG | BOOST — shorts crowded, squeeze risk |
| Extreme positive funding (>0.05%) | SHORT | BOOST — longs crowded, unwind risk |
| Extreme negative funding (<-0.01%) | SHORT | REDUCE — too crowded against you |
| Extreme positive funding (>0.05%) | LONG | REDUCE — too crowded trade |
| Normal funding | Any | NEUTRAL — no adjustment |

This gate does **not block** signals. It appends a context note (`🚀 CONTRARIAN EDGE` or `⚠️ CROWDED TRADE`) to the signal broadcast. Controlled by `FUNDING_RATE_GATE_ENABLED` (default: `true`).

### §2.8 Gate ⑨ Open Interest Divergence

**Module:** `bot/open_interest.py`

Detects smart money positioning by comparing OI change vs price change:

| OI Change | Price Change | Interpretation | Effect |
|-----------|-------------|----------------|--------|
| ↑ Up | ↑ Up | Strong trend continuation | BOOST direction of trend |
| ↓ Down | ↑ Up | Weak rally / short covering | REDUCE LONG |
| ↑ Up | ↓ Down | Bearish accumulation | BOOST SHORT |
| ↓ Down | ↓ Down | Capitulation ending | BOOST LONG |

Only activates when OI change exceeds `OI_CHANGE_THRESHOLD` (default: 5%). Controlled by `OI_MONITOR_ENABLED` (default: `true`). Significant divergences are also posted to CH5 (Insights).

---

## §3 — Module-by-Module Specification

### §3.1 `config.py` — Centralised Configuration

**Pattern:** Module-level constants read from environment variables via `os.environ.get()`.

**Complete variable reference:**

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `str` | `""` | ✅ | Bot token from @BotFather. Must not be empty or placeholder. |
| `TELEGRAM_CHANNEL_ID` | `int` | — | ✅ | Numeric Telegram channel ID for signal broadcasts. No default in production — must be explicitly set. |
| `ADMIN_CHAT_ID` | `int` | — | ✅ | Telegram user ID for admin-only commands. No default in production. |
| `WEBHOOK_SECRET` | `str` | `""` | ⚠️ | Shared secret for TradingView webhook auth. WARNING: if empty, all requests are accepted (dev only). Must be ≥32 characters in production. |
| `WEBHOOK_HOST` | `str` | `"0.0.0.0"` | ❌ | Flask bind host. |
| `WEBHOOK_PORT` | `int` | `5000` | ❌ | Flask bind port. |
| `MAX_SAME_SIDE_SIGNALS` | `int` | `3` | ❌ | 3-Pair Cap: max concurrent signals on same side. Valid range: 1–10. |
| `STALE_SIGNAL_HOURS` | `int` | `4` | ❌ | Auto-close threshold in hours. Valid range: ≥1. |
| `BE_TRIGGER_FRACTION` | `float` | `0.50` | ❌ | Move SL to entry when price covers this fraction of TP1 distance. Valid range: 0.1–0.9. |
| `NEWS_SKIP_WINDOW_MINUTES` | `int` | `60` | ❌ | Freeze signals when high-impact event is within this many minutes. |
| `DEFAULT_RISK_FRACTION` | `float` | `0.01` | ❌ | Risk per trade as fraction of account (1%). |
| `LEVERAGE_MIN` | `int` | `10` | ❌ | Minimum recommended leverage. |
| `LEVERAGE_MAX` | `int` | `20` | ❌ | Maximum recommended leverage. |
| `AUTO_SCAN_PAIRS` | `list[str]` | `""` (empty = scan ALL USDT-M perpetuals) | ❌ | Comma-separated watchlist pairs (base symbols only). Empty string triggers a full Binance Futures scan. |
| `AUTO_SCAN_INTERVAL_SECONDS` | `int` | `300` | ❌ | Auto-scan cycle interval in seconds. Valid range: ≥60. |
| `FUTURES_MIN_24H_VOLUME_USDT` | `int` | `0` | ❌ | Minimum 24h volume (USDT) for a futures pair to be included in the auto-scan. 0 = no filter. |
| `FUTURES_SCAN_BATCH_SIZE` | `int` | `20` | ❌ | Number of futures pairs to process per batch in the auto-scanner. |
| `FUTURES_SCAN_BATCH_DELAY` | `float` | `0.5` | ❌ | Seconds to pause between batch iterations in the futures auto-scanner. |
| `SPOT_SCAN_ENABLED` | `bool` | `true` | ❌ | Enable/disable the spot gem scanner (CH4). |
| `SPOT_SCAN_INTERVAL_MINUTES` | `int` | `60` | ❌ | How often (in minutes) the spot gem scan runs. |
| `SPOT_MIN_24H_VOLUME_USDT` | `int` | `100000` | ❌ | Minimum 24h volume (USDT) for a spot pair to pass the gem scan filter. |
| `SPOT_GEM_VOLUME_SPIKE_RATIO` | `float` | `3.0` | ❌ | Volume spike multiplier required for DORMANT_AWAKENING gem detection. |
| `COINMARKETCAL_API_KEY` | `str` | `""` | ❌ | Optional: enables live news filtering from CoinMarketCal. |
| `SIGNALS_FILE` | `str` | `"signals.json"` | ❌ | Legacy JSON path for signal persistence (backward compatibility). |
| `DASHBOARD_LOG_FILE` | `str` | `"dashboard.json"` | ❌ | Legacy JSON path for trade results (backward compatibility). |
| `DATABASE_URL` | `str` | `"sqlite:///360eye.db"` | ❌ | SQLAlchemy database URL. |
| `ALLOWED_WEBHOOK_IPS` | `str` | `""` | ❌ | Comma-separated IP allowlist for webhooks. Empty string = allow all. |
| `WEBHOOK_RATE_LIMIT` | `int` | `30` | ❌ | Max webhook requests per minute per IP. |
| `TP1_RR` | `float` | `1.5` | ❌ | Take-profit 1 risk-reward ratio. |
| `TP2_RR` | `float` | `2.5` | ❌ | Take-profit 2 risk-reward ratio. |
| `TP3_RR` | `float` | `4.0` | ❌ | Take-profit 3 risk-reward ratio. |
| `TIMEFRAMES` | `dict[str, int]` | `{1D:1440, 4H:240, 15m:15, 5m:5}` | ❌ | Supported timeframe definitions in minutes. |

**Validation rules:**
- `TELEGRAM_BOT_TOKEN` must not be empty string or the literal `"your-bot-token-from-botfather"`
- `TELEGRAM_CHANNEL_ID` and `ADMIN_CHAT_ID` should be explicitly set — the hardcoded defaults are placeholder values for development only
- `WEBHOOK_SECRET` must be **at least 32 characters** in production; an empty value triggers a `WARNING` log at startup and accepts all webhook requests (acceptable only in local development). A `ValueError` is raised at startup if the value is non-empty but shorter than 32 characters.
- The `data/` directory is **auto-created** at module load time (no manual `mkdir` needed)
- `.env` file is supported — copy `.env.example` to `.env` and populate before running

**Reading pattern:**
```python
SOME_VAR: type = type_cast(os.environ.get("SOME_VAR", "default"))
```

---

### §3.2 `bot/signal_engine.py` — Fractal Liquidity Engine

This is the core analytical brain of the system. It contains no I/O, no network calls, and no side effects — it is a pure computation module.

#### §3.2.1 Enumerations

**`Side(str, Enum)`**
```python
class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
```
- Inherits `str` for JSON-serialisable values
- Used everywhere direction is referenced

**`Confidence(str, Enum)`**
```python
class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
```
- Note: values are title-case strings, not all-caps

#### §3.2.2 Data Classes

**`CandleData`**
```python
@dataclass
class CandleData:
    open: float
    high: float
    low: float
    close: float
    volume: float
```
Minimal OHLCV representation. All fields are `float`. Volume represents the base-asset volume for the candle period.

**`SignalResult`**
```python
@dataclass
class SignalResult:
    signal_id: str          # "SIG-XXXXXXXXXXXX" — generated by generate_signal_id()
    symbol: str             # e.g. "BTC" (base only, no /USDT suffix)
    side: Side
    confidence: Confidence
    entry_low: float
    entry_high: float
    tp1: float
    tp2: float
    tp3: float
    stop_loss: float
    structure_note: str     # e.g. "4H Bullish OB + 5m MSS Confirmed."
    context_note: str       # e.g. "BTC holding key VWAP; DXY showing weakness."
    leverage_min: int
    leverage_max: int
```

**`SignalResult.format_message() -> str`**  
Returns the standardised Telegram broadcast message (see §4 for exact format).

#### §3.2.3 Functions

**`generate_signal_id() -> str`**
```python
import uuid
def generate_signal_id() -> str:
    return f"SIG-{uuid.uuid4().hex[:12].upper()}"
```
Returns a unique signal identifier in format `SIG-XXXXXXXXXXXX` (12 uppercase hex characters).

**`_average_volume(candles: list[CandleData]) -> float`**  
Returns the simple average volume. Returns `0.0` for an empty list.

**`calculate_atr(candles: list[CandleData], period: int = 14) -> float`**  
Computes the Average True Range over `period` candles (see formula in §2.5). Returns `0.0` if insufficient candles.

**`calculate_ema(candles: list[CandleData], period: int) -> float`**  
Computes the Exponential Moving Average of closing prices over `period` candles. Public function exported in `__all__`. Returns `0.0` if fewer than `period` candles provided.

**`calculate_vwap(candles: list[CandleData]) -> float`**  
Computes the Volume-Weighted Average Price over all provided candles:
```
vwap = Σ(typical_price × volume) / Σ(volume)
typical_price = (high + low + close) / 3
```
Returns `0.0` if total volume is zero. Also exported in `__all__`. Identical implementation exists in `bot/vwap.py` (with an `is_near_vwap` helper).

**`is_discount_zone(price: float, range_low: float, range_high: float) -> bool`**  
Returns `True` when `price <= midpoint` of the range. Precondition for LONG entries.

**`is_premium_zone(price: float, range_low: float, range_high: float) -> bool`**  
Returns `True` when `price >= midpoint` of the range. Precondition for SHORT entries.

**`detect_liquidity_sweep(candles: list[CandleData], key_level: float, side: Side) -> bool`**  
Checks last 3 candles for a wick sweep of `key_level`. See §2.2 Gate ③ for exact logic.

**`detect_market_structure_shift(candles: list[CandleData], side: Side) -> bool`**  
Detects 5m MSS/ChoCh with volume confirmation. See §2.2 Gate ④. Minimum 3 candles required.

**`detect_fair_value_gap(candles: list[CandleData], side: Side) -> bool`**  
3-candle FVG pattern detection. See §2.2 Gate ⑥.

**`detect_order_block(candles: list[CandleData], side: Side) -> bool`**  
Last opposing candle before impulse move. See §2.2 Gate ⑦.

**`assess_macro_bias(daily_candles: list[CandleData], four_hour_candles: list[CandleData]) -> Optional[Side]`**  
1D + 4H confluence bias. Returns `Side.LONG`, `Side.SHORT`, or `None`. See §2.2 Gate ①.

**`calculate_targets(entry: float, stop_loss: float, side: Side, tp1_rr: float = 1.5, tp2_rr: float = 2.5, tp3_rr: float = 4.0) -> tuple[float, float, float]`**  
Derives TP1/TP2/TP3 from R:R ratios. See §2.4 for formula.

**`run_confluence_check(...) -> Optional[SignalResult]`**

Full parameter signature:
```python
def run_confluence_check(
    symbol: str,
    current_price: float,
    side: Side,
    range_low: float,
    range_high: float,
    key_liquidity_level: float,
    five_min_candles: list[CandleData],
    daily_candles: list[CandleData],
    four_hour_candles: list[CandleData],
    news_in_window: bool,
    stop_loss: float,
    structure_note: str = "",
    context_note: str = "",
    leverage_min: int = 10,
    leverage_max: int = 20,
) -> Optional[SignalResult]:
```

Gate execution order (fail-fast):
1. Gate ⑤ — news blackout (fastest check, no data needed)
2. Gate ① — macro bias
3. Gate ② — discount/premium zone
4. Gate ③ — liquidity sweep
5. Gate ④ — market structure shift

**Structured logging:** All gate results are logged in a single structured line at the conclusion of every evaluation (pass or fail), enabling easy grep-based diagnostics.

**Near-miss warning:** When exactly **one required gate** fails (all others pass), a `WARNING`-level log entry is emitted identifying the single failing gate. This makes near-misses immediately visible in logs without requiring manual gate-by-gate analysis.

If all gates pass, `SignalResult` is constructed with `signal_id = generate_signal_id()` and appropriate `confidence` scoring (§2.6).

Returns `None` if any gate fails.

---

### §3.3 `bot/risk_manager.py` — Safety Protocols

Implements all four safety protocols defined in §5.

#### §3.3.1 Thread Safety

All mutations to `_signals` are protected by `threading.Lock()`:
```python
import threading
_lock = threading.Lock()
```
Every method that reads or writes `_signals` acquires `_lock` first.

#### §3.3.2 `ActiveSignal` Dataclass

```python
@dataclass
class ActiveSignal:
    result: SignalResult
    opened_at: float        # Unix timestamp (time.time() at creation)
    be_triggered: bool = False
    closed: bool = False
    close_reason: Optional[str] = None
```

**Properties:**

`entry_mid -> float`  
```python
return (self.result.entry_low + self.result.entry_high) / 2
```

`is_stale(now: Optional[float] = None) -> bool`  
```python
elapsed_hours = ((now or time.time()) - self.opened_at) / 3600
return elapsed_hours >= STALE_SIGNAL_HOURS
```

`should_trigger_be(current_price: float) -> bool`  
Returns `True` when price covers `BE_TRIGGER_FRACTION` of the distance to TP1:
```python
distance_to_tp1 = abs(self.result.tp1 - self.entry_mid)
trigger_price = entry_mid ± BE_TRIGGER_FRACTION * distance_to_tp1
# LONG: current_price >= trigger_price
# SHORT: current_price <= trigger_price
```
Returns `False` if `be_triggered` or `closed` is already `True`.

`trigger_be() -> None`  
Sets `self.be_triggered = True`.

`close(reason: str) -> None`  
Sets `self.closed = True` and `self.close_reason = reason`.

#### §3.3.3 `RiskManager` Class

**Constructor:** `__init__(self) -> None` — loads persisted signals from disk.

**Persistence:** JSON serialisation to `SIGNALS_FILE` (legacy) or SQLite via `bot/database.py`.

**`_load() -> None`** (internal)  
Deserialises persisted signals from JSON. Now correctly restores `signal_id` and `confluence_score` fields from the stored dictionary (using `.get("signal_id", "")` and `.get("confluence_score", 0)` with safe defaults for backward compatibility).

**`can_open_signal(side: Side) -> bool`**  
Counts active (non-closed) signals on `side`. Returns `True` if count < `MAX_SAME_SIDE_SIGNALS`.

**`add_signal(result: SignalResult, origin_channel: int = 0, created_regime: str = "UNKNOWN") -> ActiveSignal`**  
Registers a new signal. Raises `RuntimeError` if the cap would be violated. Persists immediately. All channels (CH1, CH2, CH3, CH4) call `risk_manager.add_signal()` before posting to Telegram.

**`update_prices(prices: dict[str, float]) -> list[str]`**  
Feeds latest prices. The entire iteration over open signals is performed **inside a single lock acquisition** (TOCTOU fix — prevents race conditions where a signal could be concurrently modified between read and update). For each open signal:
1. Checks staleness → closes and appends broadcast message if stale
2. Checks BE trigger → marks BE and appends broadcast message if triggered

Returns list of broadcast messages to send to Telegram.

**`close_signal(symbol: str, reason: str = "manual") -> bool`**  
Closes first open signal matching `symbol`. Returns `True` on success, `False` if not found.

**Signal lifecycle broadcasts** (BE trigger, stale close, TP updates) route to `sig.origin_channel` — the channel ID that originally posted the signal — rather than a hardcoded CH1 channel. Falls back to `TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID` when `origin_channel` is 0.

**`active_signals -> list[ActiveSignal]`** (property)  
Returns all signals where `closed == False`.

**`all_signals -> list[ActiveSignal]`** (property)  
Returns all signals (including closed).

#### §3.3.4 Position Size Calculator

**`calculate_position_size(account_balance, entry_price, stop_loss_price, risk_fraction=DEFAULT_RISK_FRACTION) -> dict`**

```python
risk_amount = account_balance * risk_fraction
sl_distance = abs(entry_price - stop_loss_price)
sl_distance_pct = sl_distance / entry_price
position_size_usdt = risk_amount / sl_distance_pct
position_size_units = position_size_usdt / entry_price
```

Returns:
```python
{
    "risk_amount": float,           # USDT at risk
    "sl_distance_pct": float,       # SL distance as % of entry
    "position_size_usdt": float,    # Margin required (USDT)
    "position_size_units": float,   # Number of base-asset units
}
```

Raises `ValueError` if prices are non-positive or identical.

---

### §3.4 `bot/bot.py` — Telegram Bot & Command Handlers

#### §3.4.1 Module-Level State

```python
risk_manager: RiskManager       # singleton
news_calendar: NewsCalendar     # singleton
dashboard: Dashboard            # singleton
signal_router: SignalRouter     # channel routing singleton
_scheduler: BackgroundScheduler # APScheduler instance (daemon=True)
_bot_state: BotState            # thread-safe state singleton (§3.8)

# Futures market data (CH1/CH2/CH3)
futures_market_data: MarketDataStore   # market_type="futures"
futures_ws: WebSocketManager           # fstream.binance.com

# Backward-compatible aliases
market_data = futures_market_data
ws_manager = futures_ws

# Spot market data (CH4 spot scanner)
spot_market_data: MarketDataStore      # market_type="spot"
spot_ws: WebSocketManager              # stream.binance.com
spot_scanner: SpotScanner              # gem/scam scanner

_last_signal_broadcast_time: dict[str, float]  # rate-limit per tier
```

State is managed at module level (process singleton). For thread-safe access in a multi-threaded context, use `bot/state.py` (§3.8).

#### §3.4.2 Admin Guard

```python
def _is_admin(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == ADMIN_CHAT_ID
```

All admin commands check this first and reply `"⛔ Admin only."` if the check fails.

#### §3.4.3 Command Handlers

| Command | Access | Parameters | Action | Channel Broadcast |
|---|---|---|---|---|
| `/signal_gen SYMBOL SIDE` | Admin | `symbol` (str), `side` (LONG\|SHORT) | Fetch Binance data → run confluence → broadcast signal | ✅ |
| `/move_be [SYMBOL]` | Admin | optional symbol filter | Trigger BE on matching signals, record TP1 WIN in dashboard | ✅ |
| `/trail_sl` | Admin | none | Toggle auto-trailing SL (60s interval) | ✅ |
| `/auto_scan` | Admin | none | Toggle auto-scanner (`AUTO_SCAN_INTERVAL_SECONDS`) | ✅ |
| `/news_caution` | Admin | none | Toggle news freeze, list active signals | ✅ |
| `/risk_calc BAL ENTRY SL` | User | balance, entry, stop_loss (floats) | Calculate position size | ❌ Private reply |
| `/close_signal SYM OUTCOME PNL` | Admin | symbol, WIN\|LOSS\|BE, pnl% | Close signal, record in dashboard, broadcast summary | ✅ |
| `/spot_scan [on\|off]` | Admin | optional `on` or `off` | Enable/disable the spot gem scanner; shows current state if no arg | ❌ Private reply |
| `/spot_status` | Admin | none | Show spot scanner status: enabled state, pair count, last scan time, gem/scam counts | ❌ Private reply |
| `/scam_check SYMBOL` | Admin | base symbol (e.g. `PEPE`) | Run manual scam pattern analysis on a spot symbol; uses `validate_symbol()` for strict alphanumeric-only input sanitisation | ❌ Private reply |
| `/status` | Admin | none | Extended status: per-channel breakdown (🔴 Hard \| 🟡 Medium \| 🔵 Easy \| 💎 Spot), performance stats (win rate, profit factor), trailing SL per-signal status | ❌ Private reply |

**`/signal_gen` flow:**
1. Validate admin + args
2. Check news freeze
3. Check 3-pair cap via `risk_manager.can_open_signal(side)`
4. Call `_fetch_binance_candles(ccxt_symbol, side)` (see §3.9)
5. Call `run_confluence_check(...)` with fetched data
6. If result is not `None`: `risk_manager.add_signal(result)` + `_broadcast(context, result.format_message())`
7. If result is `None`: reply "No valid setup found"

**`/close_signal` flow:**
1. Validate admin + args
2. Parse outcome (`WIN|LOSS|BE`) and pnl_pct (float)
3. `risk_manager.close_signal(symbol, reason=outcome)`
4. Record `TradeResult` in `dashboard.record_result(...)`
5. Broadcast formatted close summary to channel

#### §3.4.4 Background Jobs (APScheduler)

| Job ID | Interval | Condition | Logic |
|---|---|---|---|
| `news_refresh` | 30 min | Always running | `fetch_and_reload(news_calendar)` — calls CoinMarketCal API |
| `trailing_sl` | 60 sec | `_bot_state.trail_active == True` | Fetch last 3 × 5m candles per open signal; trail SL to Higher Low (LONG) or Lower High (SHORT); only move SL in favourable direction |
| `auto_scan` | `AUTO_SCAN_INTERVAL_SECONDS` | `_bot_state.auto_scan_active == True` | For each pair in `AUTO_SCAN_PAIRS` (or all Binance USDT-M perpetuals if empty): skip if already active, check both sides, run full confluence, broadcast qualifying signals; batched with `FUTURES_SCAN_BATCH_SIZE` and `FUTURES_SCAN_BATCH_DELAY` |
| `spot_scan` | `SPOT_SCAN_INTERVAL_MINUTES` min | `SPOT_SCAN_ENABLED == True` | Iterates `spot_scanner._pairs`, reads candles from `spot_market_data`, posts gems → CH4, scams → CH5 |
| `spot_scanner_refresh` | Daily | Always | `spot_scanner.refresh_pairs()` + `_seed_spot_historical_candles()` |
| `dead_man_check` | 60 min | `_bot_state.auto_scan_active == True` | Alerts admin via DM if no signal generated in past 24h (dead-man switch) |
| `weekly_report` | Sunday 20:00 UTC | Always | `send_weekly_report(app, dashboard)` — see §3.20 |

**`_broadcast(context, text) -> None`** (internal async)  
Channel routing: uses `TELEGRAM_CHANNEL_ID_HARD or TELEGRAM_CHANNEL_ID` as fallback. If neither is set, the call is silently skipped with a debug log.

**`_seed_spot_historical_candles(pairs: list[dict]) -> None`** (internal)  
Seeds 1h/4h/1d candle history (up to 210 candles each) into `spot_market_data` at startup using `ThreadPoolExecutor`. Ensures the spot scanner has sufficient historical data before the first scan cycle.

**Signal delivery latency tracking:**  
After each successful CH1/CH2/CH3 broadcast, the bot logs `signal_delivery_latency_ms` (from candle-close event to Telegram API response). If latency exceeds **10 seconds**, an admin DM is sent with the symbol, tier, and latency value.

**Dead-man switch:**  
The hourly `dead_man_check` job reads `_bot_state.seconds_since_last_signal()`. If no signal has been generated in `_DEAD_MAN_SILENCE_HOURS` (24h) while the scanner is active, it sends an alert DM to the admin with the silence duration and a recommended action to check WS connection and scanner state.

**TP1 hit → auto-activate trailing SL:**  
When TP1 is hit on any open signal, `_bot_state.trail_active` is automatically set to `True` (if not already active), activating the 60s trailing SL job.

#### §3.4.5 Async Bridge Pattern

Background jobs run in APScheduler threads (synchronous context). To call Telegram API:
```python
def _bg_broadcast(text: str) -> None:
    loop = asyncio.new_event_loop()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        loop.run_until_complete(
            bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text, parse_mode="Markdown")
        )
    finally:
        loop.close()
```
**Do not use `asyncio.run()`** — it fails if called from a thread that already has a running loop. Always create a fresh event loop per broadcast batch.

#### §3.4.6 `process_webhook(payload: dict) -> Optional[str]`

Called by `bot/webhook.py` after payload validation. Runs full confluence logic and returns the formatted message string (or `None` if confluence fails).

---

### §3.5 `bot/webhook.py` — TradingView Webhook Receiver

#### §3.5.1 App Factory

```python
def create_app() -> Flask:
```
Returns a configured Flask application instance. Use this pattern for both direct execution and Gunicorn.

**Dashboard route wiring:** `create_app()` calls `register_dashboard_routes(app, get_dashboard_fn, get_risk_manager_fn)` from `bot/dashboard_web.py`, which wires three additional routes:

| Route | Description |
|---|---|
| `GET /dashboard` | HTML dashboard page |
| `GET /api/stats` | JSON performance statistics |
| `GET /api/signals` | JSON active signal list |

#### §3.5.2 Routes

**`GET /health`**  
Returns status information (no authentication required):
```json
{
    "status": "ok",
    "service": "360-crypto-eye-scalping",
    "version": "3.0.0-domination",
    "uptime_seconds": 1234,
    "last_scan_time": "2025-01-01T12:00:00Z",
    "active_signal_count": 2
}
```

**`POST /webhook`**  
Requires `X-Webhook-Secret` header. Full processing pipeline:
1. Secret verification (§3.5.3)
2. IP allowlist check (if `ALLOWED_WEBHOOK_IPS` configured)
3. Rate limit check (`WEBHOOK_RATE_LIMIT` req/min)
4. Payload validation (§3.5.4)
5. `process_webhook(payload)` call
6. Telegram broadcast
7. Return `X-Request-ID` header in response

Response codes:
- `200` — Signal broadcast or confluence not met (check `status` field)
- `400` — Invalid JSON or missing required fields
- `403` — Invalid or missing webhook secret
- `429` — Rate limit exceeded
- `500` — Internal processing error

#### §3.5.3 Security

**Secret verification:**
```python
def _verify_secret(incoming: str) -> bool:
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET is not set — all requests are accepted.")
        return True
    return hmac.compare_digest(incoming, WEBHOOK_SECRET)
```
Uses `hmac.compare_digest()` for constant-time comparison to prevent timing attacks.

**IP allowlisting:**
```python
ALLOWED_WEBHOOK_IPS = os.environ.get("ALLOWED_WEBHOOK_IPS", "")
# If non-empty, parse comma-separated list and check request.remote_addr
```

#### §3.5.4 Payload Validation

Minimum required fields:
```json
{
    "symbol": "BTCUSDT",
    "side": "LONG"
}
```

Optional fields:
```json
{
    "price": 65000.0,
    "range_low": 63000.0,
    "range_high": 67000.0,
    "key_level": 64500.0,
    "stop_loss": 63800.0
}
```

If optional fields are missing, they are fetched from Binance via `bot/exchange.py`.

#### §3.5.5 Rate Limiting

In-memory per-IP rate limiting:
```python
_request_counts: dict[str, list[float]] = {}  # IP → list of request timestamps
# Prune timestamps older than 60s, reject if count >= WEBHOOK_RATE_LIMIT
```

---

### §3.6 `bot/dashboard.py` — Transparency Dashboard

#### §3.6.1 `TradeResult` Dataclass

```python
@dataclass
class TradeResult:
    symbol: str
    side: str               # "LONG" | "SHORT"
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    opened_at: float        # Unix timestamp
    closed_at: Optional[float]
    outcome: str            # "WIN" | "LOSS" | "BE" | "OPEN"
    pnl_pct: float          # % PnL relative to entry
    timeframe: str          # "5m" | "15m" | "1h"
```

#### §3.6.2 `Dashboard` Class Methods

**`__init__(log_file: str = DASHBOARD_LOG_FILE) -> None`**  
Loads persisted results from disk on construction.

**`record_result(result: TradeResult) -> None`**  
Appends result to in-memory list and persists to disk immediately.

**`update_open_pnl(symbol: str, current_price: float) -> None`**  
Refreshes floating PnL for OPEN trades:
```python
direction = 1 if side == "LONG" else -1
pnl_pct = direction * (current_price - entry_price) / entry_price * 100
```

**`win_rate(timeframe: Optional[str] = None) -> float`**  
```
closed = trades where outcome in (WIN, LOSS, BE)
       filtered by timeframe if specified
win_rate = (wins / total_closed) * 100
```

**`profit_factor() -> float`**  
```
gross_profit = sum of pnl_pct where pnl_pct > 0
gross_loss   = abs(sum of pnl_pct where pnl_pct < 0)
profit_factor = gross_profit / gross_loss
```
Returns `0.0` when there are no losing trades.

**`current_open_pnl() -> float`**  
Sum of `pnl_pct` for all OPEN trades.

**`total_trades() -> int`**  
Count of all non-OPEN outcomes.

**`sharpe_ratio() -> float`**  
```
returns = [r.pnl_pct for r in closed trades]
sharpe = (mean(returns) - risk_free_rate) / std_dev(returns)
# risk_free_rate = 0.0 (conservative default)
```
Returns `0.0` if fewer than 2 trades.

**`max_drawdown() -> float`**  
Peak-to-trough percentage of the equity curve:
```
equity_curve = cumulative sum of pnl_pct values
peak = running maximum of equity_curve
drawdown = (peak - equity_curve) / (1 + peak/100) * 100
max_drawdown = max(drawdown values)
```

**`avg_holding_time() -> float`**  
Average hours between `opened_at` and `closed_at` for closed trades.

**`win_streak() -> int`** / **`loss_streak() -> int`**  
Current consecutive WIN or LOSS streak counting backwards from the most recent trade.

**`equity_curve() -> list[dict]`**  
List of `{"timestamp": float, "cumulative_pnl": float}` dicts, one per closed trade.

**`per_symbol_stats() -> dict`**  
```python
{
    "BTCUSDT": {"trades": 10, "win_rate": 70.0, "profit_factor": 2.1},
    ...
}
```

**`summary() -> str`**  
Formatted Telegram-ready dashboard summary including all key statistics.

**`protected_win_rate(timeframe: Optional[str] = None) -> float`**  
Win rate counting break-even trades as wins (BE = protected capital = success):
```
protected_wins = count(outcome == WIN) + count(outcome == BE)
protected_win_rate = (protected_wins / total_closed) * 100
```

**`avg_risk_reward() -> float`**  
Average realised risk-reward ratio across all closed trades:
```
for each closed trade:
    sl_dist_pct = abs(entry_price - stop_loss) / entry_price * 100
    rr = abs(pnl_pct) / sl_dist_pct   (only when sl_dist_pct > 0)
avg_rr = mean(rr values)
```
Returns `0.0` if no valid trades.

**`win_rate_rolling(days: int = 7) -> float`**  
Win rate over the last `days` days (rolling window). Uses `opened_at` timestamp for the window calculation.

**`check_drawdown_halt(threshold_pct: float = -15.0) -> bool`**  
Returns `True` if current max drawdown (from `max_drawdown()`) exceeds the threshold. Used to trigger an automatic trading halt at -15% drawdown.

---

### §3.7 `bot/news_filter.py` — News Calendar

#### §3.7.1 `NewsEvent` Dataclass

```python
@dataclass
class NewsEvent:
    title: str
    timestamp: float    # Unix UTC timestamp
    impact: str         # "HIGH" | "MEDIUM" | "LOW"
    currency: str       # e.g. "USD", "BTC"
```

Class method: `from_dict(data: dict) -> NewsEvent`

#### §3.7.2 `NewsCalendar` Class

**`__init__(skip_window_minutes: int = NEWS_SKIP_WINDOW_MINUTES) -> None`**

**`load_events(events: Sequence[NewsEvent]) -> None`**  
Replaces the full event list.

**`add_event(event: NewsEvent) -> None`**  
Appends a single event.

**`clear() -> None`**  
Removes all events.

**`is_high_impact_imminent(now: float | None = None) -> bool`**  
Returns `True` if any event satisfies:
```python
event.impact == "HIGH" and now <= event.timestamp <= now + skip_window_seconds
```

**`upcoming_high_impact(now: float | None = None) -> list[NewsEvent]`**  
Returns all HIGH events within the window, sorted by timestamp ascending.

**`format_caution_message(now: float | None = None) -> str`**  
Human-readable Telegram message listing all imminent events with UTC times.

---

### §3.8 `bot/state.py` — Thread-Safe Bot State

Provides a thread-safe singleton for shared bot state, replacing the module-level globals in `bot.py` for multi-threaded contexts.

```python
import threading
import time

class BotState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._news_freeze: bool = False
        self._trail_active: bool = False
        self._auto_scan_active: bool = False
        self._last_signal_generated_at: float = 0.0  # dead-man switch

    @property
    def news_freeze(self) -> bool:
        with self._lock:
            return self._news_freeze

    @news_freeze.setter
    def news_freeze(self, value: bool) -> None:
        with self._lock:
            self._news_freeze = value

    # ... same pattern for trail_active and auto_scan_active

    def record_signal_generated(self) -> None:
        """Update the timestamp of the last signal generated (for dead-man switch)."""
        with self._lock:
            self._last_signal_generated_at = time.time()

    def seconds_since_last_signal(self) -> float:
        """Return seconds since last signal, or float('inf') if no signal ever generated."""
        with self._lock:
            if self._last_signal_generated_at == 0.0:
                return float("inf")
            return time.time() - self._last_signal_generated_at

# Module-level singleton
bot_state = BotState()
```

All property accesses acquire the lock before reading or writing.

**Dead-man switch integration:** `record_signal_generated()` is called every time a signal is successfully broadcast. The hourly APScheduler job in `bot.py` reads `seconds_since_last_signal()` and sends an admin DM alert if silence exceeds 24 hours while the scanner is active (see §3.4.4).

---

### §3.9 `bot/exchange.py` — Resilient Exchange Client

#### §3.9.1 `ResilientExchange` Class

Wraps CCXT Binance Futures with reliability features.

**`__init__() -> None`**  
Initialises CCXT exchange in Binance Futures mode:
```python
exchange = ccxt.binance({
    "options": {"defaultType": "future"},
    "enableRateLimit": True,
})
```

**`fetch_ohlcv_safe(symbol: str, timeframe: str, limit: int, retries: int = 3) -> list`**  
Fetches OHLCV with exponential backoff + jitter:
```
delay = 2^attempt + random(0, 1)
```
Raises last exception after all retries are exhausted.

**Circuit Breaker:** After 5 consecutive failures across any symbol/timeframe:
1. Set `_circuit_open = True`, record `_circuit_open_until = time.time() + 120`
2. All subsequent calls raise `RuntimeError("Circuit breaker open")` until the 120s cooldown expires
3. Alert admin via Telegram (async bridge pattern — see §3.4.5)

**TTL Cache:**
| Timeframe | Cache TTL |
|---|---|
| 1D (daily) | 4 hours |
| 4H | 30 minutes |
| 5m | No cache (always fresh) |

Cache key: `f"{symbol}:{timeframe}"`. Cache stored as `_cache: dict[str, tuple[list, float]]` (data, expiry_timestamp).

**`_evict_expired_cache() -> None`** (internal)  
Removes all cache entries whose `expiry_timestamp` has passed. Called automatically on every `fetch_ohlcv_safe` call before inserting a new entry, preventing unbounded memory growth during long-running sessions.

**`fetch_binance_candles(symbol: str, side: Side) -> dict`**

Returns a dictionary with all data needed by `run_confluence_check`:
```python
{
    "price": float,         # last 5m close price
    "range_low": float,     # lowest low of last 10 4H candles
    "range_high": float,    # highest high of last 10 4H candles
    "key_level": float,     # LONG: lowest 5m low / SHORT: highest 5m high
    "stop_loss": float,     # key_level ± ATR * 0.3
    "5m": list[CandleData],
    "1D": list[CandleData],
    "4H": list[CandleData],
}
```

**Symbol normalisation:**
```python
def _normalise_symbol(raw: str) -> str:
    # "BTC" → "BTC/USDT:USDT"
    # "BTCUSDT" → "BTC/USDT:USDT"
```

**Request weight tracking:**  
Estimates Binance API weight from OHLCV call parameters. Throttles proactively if approaching Binance's 1200 weight/minute limit.

---

### §3.10 `bot/database.py` — SQLite/SQLAlchemy Persistence

#### §3.10.1 Tables

**`signals` table:**
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `signal_id` | TEXT UNIQUE | `SIG-XXXXXXXXXXXX` |
| `symbol` | TEXT | Base symbol |
| `side` | TEXT | `LONG` or `SHORT` |
| `confidence` | TEXT | `High`, `Medium`, or `Low` |
| `entry_low` | REAL | Lower bound of entry zone |
| `entry_high` | REAL | Upper bound of entry zone |
| `tp1` | REAL | Take-profit 1 price |
| `tp2` | REAL | Take-profit 2 price |
| `tp3` | REAL | Take-profit 3 price |
| `stop_loss` | REAL | Stop-loss price |
| `opened_at` | REAL | Unix timestamp |
| `closed_at` | REAL | Unix timestamp or NULL |
| `closed` | INTEGER | 0 or 1 |
| `close_reason` | TEXT | `manual`, `stale`, `WIN`, `LOSS`, `BE`, or NULL |
| `be_triggered` | INTEGER | 0 or 1 |
| `confluence_gates_json` | TEXT | JSON audit trail of gate results |

**`trade_results` table:**  
Mirrors the `TradeResult` dataclass from `bot/dashboard.py`. Stores all closed trade records for performance analytics.

#### §3.10.2 Functions

**`init_db() -> None`**  
Creates all tables if they do not exist. Called at startup.

**`migrate_json_to_db() -> None`**  
Imports legacy `signals.json` and `dashboard.json` files into SQLite on first run. Called once and idempotent.

**Session management:**
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
```
Use `with Session() as session:` context manager for all database operations.

---

### §3.11 `bot/logging_config.py` — Structured Logging

#### §3.11.1 Configuration

JSON-formatted structured logging output:
```json
{
    "timestamp": "2025-01-01T12:00:00.000Z",
    "level": "INFO",
    "logger": "bot.signal_engine",
    "event": "signal_generated",
    "signal_id": "SIG-ABCDEF123456",
    "symbol": "BTC",
    "side": "LONG",
    "confidence": "High",
    "duration_ms": 42
}
```

#### §3.11.2 Structured Events

| Event Key | Logged When |
|---|---|
| `signal_generated` | `run_confluence_check()` returns a `SignalResult` |
| `confluence_gate_result` | Each gate pass/fail in `run_confluence_check()` |
| `be_triggered` | `ActiveSignal.trigger_be()` called |
| `signal_closed` | `ActiveSignal.close()` called |
| `auto_scan_started` | Background auto-scanner job begins |
| `auto_scan_completed` | Background auto-scanner job finishes |
| `trailing_sl_updated` | SL moved during trailing SL job |

#### §3.11.3 Timing Context Manager

```python
from contextlib import contextmanager
import time

@contextmanager
def timed(event_name: str):
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(event_name, extra={"duration_ms": elapsed_ms})
```

Usage: `with timed("binance_fetch"):` wraps API call blocks.

---

### §3.12 `bot/session_filter.py` — Trading Session Gate

Restricts signal generation to high-liquidity trading sessions.

**Sessions (UTC):**

| Session | Hours (UTC) | Active for Signals |
|---------|------------|-------------------|
| `LONDON` | 07:00–12:00 | ✅ Yes |
| `LONDON+NYC_OVERLAP` | 12:00–16:00 | ✅ Yes (peak liquidity) |
| `NEW_YORK` | 16:00–21:00 | ✅ Yes |
| `ASIA` | 00:00–07:00 | ❌ No (suppressed) |
| `OFF_HOURS` | 21:00–00:00 | ❌ No (suppressed) |

When `SESSION_FILTER_ENABLED=false` (default): 24/7 scanning, no restrictions.

> **Default changed:** `SESSION_FILTER_ENABLED` defaults to `False` (changed from `True`). This was changed to ensure that crypto markets — which trade 24/7 — are not artificially restricted out of the box. Operators who want session-based restrictions must explicitly set `SESSION_FILTER_ENABLED=true`.

**Key functions:**
- `get_current_session(now)` → session name string
- `is_active_session(now)` → `True` if signals are allowed

### §3.13 `bot/funding_rate.py` — Funding Rate Gate

See §2.7 for the gate logic. Key functions:

- `fetch_funding_rate(symbol)` → `Optional[float]` — Binance Futures API, returns `None` on error
- `get_funding_sentiment(funding_rate, side)` → `"BOOST" | "REDUCE" | "NEUTRAL"`

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `FUNDING_RATE_GATE_ENABLED` | `true` | Enable/disable the gate |
| `FUNDING_EXTREME_NEGATIVE` | `-0.0001` | Threshold for extreme negative funding (-0.01%) |
| `FUNDING_EXTREME_POSITIVE` | `0.0005` | Threshold for extreme positive funding (+0.05%) |

### §3.14 `bot/open_interest.py` — Open Interest Monitor

See §2.8 for the gate logic. Key functions:

- `fetch_open_interest(symbol)` → `Optional[float]` — Binance Futures API, returns `None` on error
- `analyze_oi_change(current_oi, previous_oi, price_change_pct, side)` → `"BOOST" | "REDUCE" | "NEUTRAL"`

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `OI_MONITOR_ENABLED` | `true` | Enable/disable OI monitoring |
| `OI_CHANGE_THRESHOLD` | `0.05` | Minimum OI % change to act on (5%) |

### §3.15 `bot/loss_streak_cooldown.py` — Loss Streak Cooldown

After 3+ consecutive losses, automatically activates a protective cooldown:

1. **Position size reduced** to 50% of normal for the next 3 signals
2. **LOW confidence signals suppressed** entirely during cooldown
3. **Auto-reset** after 3 profitable signals OR 24 hours
4. **Warning posted** to CH5 (Insights) when cooldown activates/deactivates

**Class:** `CooldownManager`

> **Thread-safe:** All methods use `threading.RLock` (re-entrant lock) to support concurrent access from asyncio tasks, background jobs, and command handlers without deadlocks.

| Method | Returns | Description |
|--------|---------|-------------|
| `record_outcome(outcome)` | `bool` | Record WIN/LOSS/BE. Returns `True` if cooldown just activated |
| `is_cooldown_active()` | `bool` | Check if cooldown is active (auto-resets by time) |
| `get_risk_modifier()` | `float` | 0.5 during cooldown, 1.0 normal |
| `should_suppress_low_confidence()` | `bool` | True during cooldown |

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `LOSS_STREAK_THRESHOLD` | `3` | Consecutive losses to trigger cooldown |
| `COOLDOWN_SIGNALS` | `3` | Profitable signals needed to exit cooldown early |
| `COOLDOWN_HOURS` | `24` | Maximum cooldown duration in hours |

---

### §3.16 `bot/spot_scanner.py` — Spot Market Scanner

Scans all active Binance USDT spot pairs for gem opportunities and manipulation patterns. Gem signals route to CH4; scam alerts route to CH5.

#### §3.16.1 Module Functions

**`fetch_binance_spot_pairs() -> list[dict]`**  
Returns all active USDT spot pairs from Binance via ccxt, filtered by `SPOT_MIN_24H_VOLUME_USDT`. Each entry is a dict with `symbol`, `base`, `volume` keys.

**`validate_symbol(raw: str) -> Optional[str]`**  
Strict input sanitisation for user-supplied symbol in `/scam_check`. Returns the uppercased symbol if it matches `^[A-Z0-9]{1,20}$` (alphanumeric only, max 20 chars), or `None` if invalid. Used to prevent injection via Telegram command parameters.

#### §3.16.2 `SpotGemResult` Dataclass

```python
@dataclass
class SpotGemResult:
    symbol: str
    gem_type: str       # see table below
    entry_low: float
    entry_high: float
    tp1: float          # +15%
    tp2: float          # +30%
    tp3: float          # +50%
    stop_loss: float    # -10%
    score: int          # 0–100 confidence score
    reason: str
    risk_flags: list[str]
```

**Gem types:**

| Type | Detection Logic |
|---|---|
| `NEW_LISTING` | Listed within the last `SPOT_NEW_LISTING_LOOKBACK_DAYS` (90) days |
| `DORMANT_AWAKENING` | Low volume for 30+ days, then `SPOT_GEM_VOLUME_SPIKE_RATIO` (3×)+ volume spike |
| `MOMENTUM_BREAKOUT` | Price breaks `SPOT_GEM_BREAKOUT_LOOKBACK_DAYS` (30)-day high with volume confirmation |
| `ACCUMULATION` | Price within `SPOT_GEM_ACCUMULATION_RANGE_PCT` (10%) of 90-day low with rising volume |
| `CATALYST_DRIVEN` | Upcoming CoinMarketCal event (mainnet launch / listing / partnership) |

#### §3.16.3 `ScamAlert` Dataclass

```python
@dataclass
class ScamAlert:
    symbol: str
    alert_type: str     # "PUMP_AND_DUMP" | "WASH_TRADING"
    description: str
    severity: str       # "HIGH" | "MEDIUM"
```

**Scam types:**

| Type | Detection Logic |
|---|---|
| `PUMP_AND_DUMP` | >500% price spike followed by >50% crash within 24h |
| `WASH_TRADING` | Volume coefficient of variation (CV = std_dev / mean) < 2% — unrealistically uniform volume |

#### §3.16.4 `SpotScanner` Class

**`__init__(spot_market_data: MarketDataStore, max_buffer_size: int = _DEFAULT_BUF_1D) -> None`**  
Accepts an optional `max_buffer_size` parameter (default: `_BUF_1D` = 210) for the history buffer size used during gem detection.

**`scan_once() -> tuple[list[SpotGemResult], list[ScamAlert]]`**  
Runs a full pass over all tracked spot pairs. Returns `(gems, scams)`. Gems are wrapped in `SignalResult` and registered via `risk_manager.add_signal()` before being posted to CH4. Scams are posted directly to CH5.

**`scam_check_symbol(symbol: str) -> Optional[ScamAlert]`**  
Runs scam detection on a single symbol. Used by the `/scam_check` admin command.

**`get_status() -> dict`**  
Returns scanner state: `enabled`, `pair_count`, `last_scan_at`, `total_gems_found`, `total_scams_found`.

**`refresh_pairs() -> None`**  
Re-fetches the full Binance spot pair list and updates `_pairs`.

**`set_enabled(value: bool) -> None`**  
Enables or disables scanning.

---

### §3.17 `bot/ws_manager.py` — WebSocket Market Data Manager

Connects to Binance combined-stream endpoints and maintains in-memory ring buffers of OHLCV candles for real-time signal processing.

#### §3.17.1 Constants

| Constant | Value | Description |
|---|---|---|
| `_WS_FUTURES_URL` | `wss://fstream.binance.com/stream` | Futures WebSocket endpoint |
| `_WS_SPOT_URL` | `wss://stream.binance.com:9443/stream` | Spot WebSocket endpoint |
| `_BUF_5M` | `50` | Futures 5m candle buffer size |
| `_BUF_15M` | `50` | Futures 15m candle buffer size |
| `_BUF_4H` | `30` | 4H candle buffer size (both markets) |
| `_BUF_1D` | `210` | 1D candle buffer size — 210 candles required for 200-day SMA in regime detector |
| `_BUF_1H` | `50` | Spot 1h candle buffer size |
| `_STALE_THRESHOLD` | `60.0` | Seconds without any message before stream is considered unhealthy (reduced from 120s) |
| `_MAX_SYMBOLS_PER_CONN` | `50` | Symbols per WebSocket connection (Binance hard limit: 200 streams / 4–5 streams per symbol) |

#### §3.17.2 `MarketDataStore` Class

```python
class MarketDataStore:
    def __init__(self, market_type: str = "futures") -> None
```

Central in-memory store for all symbols' candles and live prices.

**Timeframe buffers by `market_type`:**

| `market_type` | Timeframes buffered |
|---|---|
| `"futures"` | `5m`, `15m`, `4h`, `1d` |
| `"spot"` | `1h`, `4h`, `1d` |

**Key methods:**
- `update_candle(symbol, timeframe, ohlcv)` — appends or replaces in-progress candle (same `open_time` → replace; new → append)
- `set_price(symbol, price)` — updates live price
- `get_price(symbol) -> Optional[float]`
- `get_candles(symbol, timeframe) -> list[list[float]]` — snapshot of the buffer as plain list
- `has_sufficient_data(symbol) -> bool` — checks all timeframes meet minimum candle counts

All reads and writes are protected by `threading.Lock`.

#### §3.17.3 `WebSocketManager` Class

```python
class WebSocketManager:
    def __init__(
        self,
        store: MarketDataStore,
        market_type: str = "futures",
        on_candle_close: Optional[OnCandleClose] = None,
    ) -> None
```

Manages multiple WebSocket connections to Binance:
- **Futures** (`market_type="futures"`) → connects to `fstream.binance.com`; subscribes to `@kline_5m`, `@kline_15m`, `@kline_4h`, `@kline_1d`, `@miniTicker`
- **Spot** (`market_type="spot"`) → connects to `stream.binance.com:9443`; subscribes to `@kline_1h`, `@kline_4h`, `@kline_1d`, `@miniTicker`

**Key features:**
- Splits pairs across multiple connections (≤200 streams / ~50 symbols per connection)
- Fires `on_candle_close(base_symbol, timeframe)` callback on every **closed** kline event
- Auto-reconnects with exponential backoff + jitter (1s base, 60s cap)
- `is_healthy() -> bool` — returns `True` if `last_message_at` within `_STALE_THRESHOLD` seconds

---

### §3.18 `bot/regime_adapter.py` — Regime-Adaptive Parameters

Maps the current market regime to concrete signal-generation parameter adjustments.

**`get_regime_adjustments(regime: str) -> dict`**

```python
# Returns dict with keys: tp3_rr, max_signals, risk_modifier
get_regime_adjustments("BULL")    # {'tp3_rr': 5.0, 'max_signals': 5, 'risk_modifier': 1.0}
get_regime_adjustments("BEAR")    # {'tp3_rr': 3.0, 'max_signals': 3, 'risk_modifier': 0.75}
get_regime_adjustments("SIDEWAYS") # {'tp3_rr': 2.5, 'max_signals': 2, 'risk_modifier': 0.5}
get_regime_adjustments("UNKNOWN") # {'tp3_rr': 4.0, 'max_signals': 4, 'risk_modifier': 0.85}
```

**`UNKNOWN` handling:** When the regime cannot be determined (e.g. insufficient data for the 200-day SMA), `UNKNOWN` returns **neutral/moderate** settings — NOT the same as `SIDEWAYS`. This prevents silently throttling signal generation during startup or data gaps.

Any unrecognised regime string is treated as `SIDEWAYS`.

---

### §3.19 `bot/insights/regime_detector.py` — Market Regime Classifier

Classifies BTC market regime daily at 09:00 UTC. Stores result in `BotState.market_regime`.

**`classify_regime(daily_candles, current_price, fear_and_greed) -> str`**

**Regime rules:**

| Regime | Condition |
|---|---|
| `BULL` | `current_price > 200d SMA` AND `fear_and_greed > 50` |
| `BEAR` | `current_price < 200d SMA` AND `fear_and_greed < 40` |
| `SIDEWAYS` | Anything else (SMA and F&G disagree, or F&G is None) |
| `UNKNOWN` | Fewer than 50 daily candles available |

**Graceful degradation:** When 50–199 candles are available (below the 200-day SMA threshold), the function falls back to the **50-day SMA** instead of returning `UNKNOWN`. A `DEBUG` log records the fallback. Returns `UNKNOWN` only when fewer than 50 candles are available.

```python
if len(daily_candles) >= 200:
    sma = sum(c.close for c in daily_candles[-200:]) / 200
elif len(daily_candles) >= 50:
    sma = sum(c.close for c in daily_candles[-50:]) / 50  # 50-day fallback
else:
    return "UNKNOWN"
```

**`fetch_fear_and_greed(url, timeout) -> Optional[int]`**  
Fetches the current Fear & Greed Index from `alternative.me` API. Returns `0–100` or `None` on failure.

---

### §3.20 `bot/weekly_report.py` — Weekly Performance Report

Generates an automated weekly performance summary. Wired as an APScheduler `cron` job in `bot.py` running every **Sunday at 20:00 UTC**.

**`generate_weekly_report(dashboard: Dashboard, days: int = 7) -> str`**

Returns a Telegram-formatted report covering the rolling `days`-day window:

| Metric | Description |
|---|---|
| Total signals | Count of WIN + LOSS + BE in the window |
| Win rate | `wins / total * 100` |
| Protected win rate | `(wins + BE) / total * 100` |
| Profit factor | `gross_profit / gross_loss` |
| Average R:R | Mean realised risk-reward ratio |
| Best trade | Symbol + PnL% of the highest-return trade |
| Worst trade | Symbol + PnL% of the lowest-return trade |

**`send_weekly_report(application, dashboard) -> None`**  
Async wrapper that calls `generate_weekly_report()` and posts the result to the CH5 (Insights) channel.

---

### §3.21 `bot/gate_labels.py` — Gate Label Registry

Single source of truth for all gate keys, human-readable labels, and circled-number symbols. Used by `narrative.py`, `postmortem.py`, and any future gate-related modules.

**`GATE_KEYS`** (class with string constants):
```python
class GATE_KEYS:
    MACRO_BIAS = "macro_bias"
    ZONE = "zone"
    SWEEP = "sweep"
    MSS = "mss"
    NEWS = "news"
    FVG = "fvg"
    ORDER_BLOCK = "order_block"
    CONFLUENCE_SCORE = "confluence_score"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    SESSION_FILTER = "session_filter"
```

**`GATE_LABELS: dict[str, str]`** — maps gate key → human-readable label (e.g. `"macro_bias"` → `"Macro Bias (Gate ①)"`)

**`GATE_SYMBOLS: dict[str, str]`** — maps gate key → circled-number symbol (e.g. `"macro_bias"` → `"①"`)

**`gate_symbols_str(gates_fired: list[str]) -> str`**  
Formats a list of gate keys to a compact `"①②③④"` style string for display in signal messages and postmortems.

---

### §3.22 `bot/price_fmt.py` — Adaptive Price Formatter

Provides adaptive decimal precision for price display, replacing the previous fixed `:.4f` format throughout the codebase.

**`fmt_price(price: float) -> str`**

```python
def fmt_price(price: float) -> str:
    abs_price = abs(price)
    if abs_price >= 1_000:   return f"{price:,.2f}"   # BTC: "90,000.00"
    if abs_price >= 0.01:    return f"{price:.4f}"    # mid-range: "0.4567"
    if abs_price >= 0.0001:  return f"{price:.6f}"    # micro: "0.000123"
    return f"{price:.8f}"                              # nano: "0.00000012"
```

All `SignalResult.format_message()` price fields use `fmt_price()` — entry zone, TP1/TP2/TP3, stop loss, and the copy-trade line. This replaces the previous hardcoded `:.4f` format.

---

## §4 — Signal Broadcast Template

Every Telegram signal message follows this exact format:

```
🚀 #SYMBOL/USDT (LONG|SHORT) | 360 EYE SCALP
Signal ID: SIG-XXXXXXXXXXXX
Confidence: High/Medium/Low

📊 STRATEGY MAP:
- Structure: 4H Bullish OB + 5m MSS Confirmed.
- Context: BTC holding key VWAP; DXY showing weakness.
- Risk: 1% of Account Balance.

⚡ ENTRY ZONE: [Low] – [High]
🎯 TARGETS:
- TP 1: [Price] (Close 50% + Move SL to Entry)
- TP 2: [Price] (Close 25% + Start Trailing)
- TP 3: [Price] (Final Moon Bag)

🛑 STOP LOSS: [Price] (Structural Invalidation)
Leverage: Cross 10x - 20x (Recommended)

👇 CLICK TO COPY FOR BINANCE:
`SYMBOL LONG|SHORT ENTRY [Price] TP [TP1], [TP2], [TP3] SL [Price]`
```

**Field mappings:**
- `SYMBOL` → `result.symbol`
- `LONG|SHORT` → `result.side.value`
- `SIG-XXXXXXXXXXXX` → `result.signal_id`
- `High/Medium/Low` → `result.confidence.value`
- `[Low] – [High]` → `f"{fmt_price(result.entry_low)} – {fmt_price(result.entry_high)}"`
- `[Price]` for ENTRY in copy trade block → `fmt_price((entry_low + entry_high) / 2)`
- All prices formatted using `fmt_price()` (adaptive decimal precision — see §3.22): ≥$1k → 2dp, ≥$0.01 → 4dp, ≥$0.0001 → 6dp, else 8dp
- Parse mode: `Markdown`

**Break-Even Broadcast Template:**
```
🔒 #SYMBOL/USDT LONG|SHORT: Move SL to Entry [entry_mid] (Risk-Free Mode ON).
```

**Stale Close Broadcast Template:**
```
⚠️ #SYMBOL/USDT LONG|SHORT signal CLOSED (stale — no activity for >4h).
```

**Close Signal Summary Template:**
```
📋 SIGNAL CLOSED — #SYMBOL/USDT LONG|SHORT
Outcome: WIN ✅ | LOSS ❌ | BE 🔒
PnL: +X.XX% | -X.XX%
Held for: X.Xh
```

---

## §5 — Safety Protocols (Complete Reference)

### §5.1 Break-Even (BE) Trigger

**Trigger condition:**
```
distance_to_tp1 = abs(tp1 - entry_mid)
trigger_level = entry_mid + BE_TRIGGER_FRACTION * distance_to_tp1  (LONG)
trigger_level = entry_mid - BE_TRIGGER_FRACTION * distance_to_tp1  (SHORT)

LONG:  current_price >= trigger_level
SHORT: current_price <= trigger_level
```

**Default:** `BE_TRIGGER_FRACTION = 0.50` (price covers 50% of the TP1 distance)

**Effect:** `ActiveSignal.be_triggered = True`. SL is now at entry (tracked in the signal — not automatically placed on the exchange).

**Automatic detection:** `RiskManager.update_prices(prices)` checks all open signals on every price update.

**Manual trigger:** `/move_be [SYMBOL]` admin command.

**TP1 hit → auto-trailing SL:** When TP1 price is reached, `_bot_state.trail_active` is automatically set to `True` (if not already active). This ensures the 60-second trailing SL job activates immediately on first profit target.

**Broadcast message:** `"🔒 #{SYMBOL}/USDT {SIDE}: Move SL to Entry {entry_mid} (Risk-Free Mode ON)."` (price formatted via `fmt_price()`)

### §5.2 3-Pair Cap

**Trigger condition:** `count_active_same_side >= MAX_SAME_SIDE_SIGNALS`

**Default:** `MAX_SAME_SIDE_SIGNALS = 3`

**Effect:** New signal generation is blocked for that side. Returns `False` from `can_open_signal()`.

**Purpose:** Prevents total directional exposure wipeout in a single market flush.

**Checked in:** `cmd_signal_gen`, `auto_scan` background job, `process_webhook`.

**Error message when cap hit:** `"🚫 3-Pair Cap reached — cannot open another {SIDE} signal."`

### §5.3 Stale Close

**Trigger condition:**
```
elapsed_hours = (current_time - opened_at) / 3600
is_stale = elapsed_hours >= STALE_SIGNAL_HOURS
```

**Default:** `STALE_SIGNAL_HOURS = 4`

**Effect:** Signal is auto-closed with `reason = "stale"`. A broadcast message is sent.

**Checked in:** `RiskManager.update_prices()` — called periodically by the trailing SL background job.

**Broadcast message:** `"⚠️ #{SYMBOL}/USDT {SIDE} signal CLOSED (stale — no activity for >{STALE_SIGNAL_HOURS}h)."`

**Rationale:** A scalp that hasn't triggered after 4 hours indicates the setup has invalidated. Holding it risks adverse gap fills.

### §5.4 News Blackout

**Trigger condition:** `news_calendar.is_high_impact_imminent() == True`

**Default window:** `NEWS_SKIP_WINDOW_MINUTES = 60`

**Effect:** All new signal generation frozen — `run_confluence_check()` returns `None` immediately (Gate ⑤).

**Manual toggle:** `/news_caution` admin command sets `_news_freeze = True`.

**Automatic:** Gate ⑤ in confluence engine always checks the live calendar regardless of manual freeze state.

**Data refresh:** Background job `news_refresh` runs every 30 minutes to fetch latest events from CoinMarketCal API.

**Broadcast on activation:**
```
⚠️ NEWS CAUTION MODE ACTIVATED
🚫 New signals are FROZEN until further notice.

📌 Active signals — consider closing partials:
  • #BTCUSDT LONG
  [list of active signals]

[format_caution_message() output]
```

---

## §6 — Dashboard Parameters & Formulas

### §6.1 Win Rate

```
closed_trades = trades where outcome ∈ {WIN, LOSS, BE}
                optionally filtered by timeframe

win_rate = (count(outcome == WIN) / count(closed_trades)) × 100
```

Reported per timeframe (5m / 15m / 1h) and in aggregate.

### §6.2 Profit Factor

```
gross_profit = Σ pnl_pct for all closed trades where pnl_pct > 0
gross_loss   = |Σ pnl_pct for all closed trades where pnl_pct < 0|

profit_factor = gross_profit / gross_loss
```

Returns `0.0` when `gross_loss == 0` (no losing trades recorded yet).

### §6.3 Sharpe Ratio

```
returns = [r.pnl_pct for r in closed_trades]
mean_return = Σ returns / n
variance = Σ (r - mean_return)² / (n - 1)
std_dev = √variance
risk_free_rate = 0.0

sharpe_ratio = (mean_return - risk_free_rate) / std_dev
```

Returns `0.0` for fewer than 3 trades (Bessel's correction requires n ≥ 3 for meaningful sample std_dev).

### §6.4 Maximum Drawdown

```
equity = cumulative sum of pnl_pct values in chronological order
peak = running maximum of equity

for each point i:
    drawdown[i] = (peak[i] - equity[i]) / (100 + peak[i]) × 100

max_drawdown = max(drawdown)
```

### §6.5 Equity Curve

```python
[
    {"timestamp": opened_at, "cumulative_pnl": 0.0},  # starting point
    {"timestamp": closed_at_1, "cumulative_pnl": pnl_1},
    {"timestamp": closed_at_2, "cumulative_pnl": pnl_1 + pnl_2},
    ...
]
```

### §6.6 Position Size Formula

```
risk_amount         = account_balance × risk_fraction
sl_distance         = |entry_price - stop_loss_price|
sl_distance_pct     = sl_distance / entry_price
position_size_usdt  = risk_amount / sl_distance_pct
position_size_units = position_size_usdt / entry_price
```

**Example:** $10,000 account, 1% risk, entry $65,000, SL $64,350:
```
risk_amount         = $100
sl_distance         = $650
sl_distance_pct     = 1.0%
position_size_usdt  = $100 / 0.01 = $10,000
position_size_units = $10,000 / $65,000 ≈ 0.1538 BTC
```

---

## §7 — Deployment & Infrastructure

### §7.1 Environment Variables Checklist

Before deploying, verify all required variables are set:

```bash
# ✅ REQUIRED — replace each value with your actual credentials
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHANNEL_ID=-100XXXXXXXXXX
ADMIN_CHAT_ID=your_telegram_user_id
WEBHOOK_SECRET=your_strong_random_secret_min_32_chars

# ⚠️ STRONGLY RECOMMENDED
COINMARKETCAL_API_KEY=your_coinmarketcal_api_key

# ❌ OPTIONAL (have safe defaults)
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=5000
MAX_SAME_SIDE_SIGNALS=3
STALE_SIGNAL_HOURS=4
BE_TRIGGER_FRACTION=0.50
NEWS_SKIP_WINDOW_MINUTES=60
DEFAULT_RISK_FRACTION=0.01
LEVERAGE_MIN=10
LEVERAGE_MAX=20
# empty = scan ALL Binance USDT-M perpetuals
AUTO_SCAN_PAIRS=
AUTO_SCAN_INTERVAL_SECONDS=300
FUTURES_MIN_24H_VOLUME_USDT=0
FUTURES_SCAN_BATCH_SIZE=20
FUTURES_SCAN_BATCH_DELAY=0.5
SPOT_SCAN_ENABLED=true
SPOT_SCAN_INTERVAL_MINUTES=60
SPOT_MIN_24H_VOLUME_USDT=100000
SPOT_GEM_VOLUME_SPIKE_RATIO=3.0
# default false — set true to restrict signals to London/NYC sessions
SESSION_FILTER_ENABLED=false
SIGNALS_FILE=data/signals.json
DASHBOARD_LOG_FILE=data/dashboard.json
DATABASE_URL=sqlite:///data/360eye.db
ALLOWED_WEBHOOK_IPS=
WEBHOOK_RATE_LIMIT=30
TP1_RR=1.5
TP2_RR=2.5
TP3_RR=4.0
```

### §7.2 Docker Deployment

**`Dockerfile`:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create volume mount point for persistence
VOLUME ["/app/data"]
ENV SIGNALS_FILE=/app/data/signals.json
ENV DASHBOARD_LOG_FILE=/app/data/dashboard.json
ENV DATABASE_URL=sqlite:////app/data/360eye.db

CMD ["python", "main.py"]
```

**`docker-compose.yml`:**
```yaml
version: "3.9"

services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
    command: python main.py

  webhook:
    build: .
    restart: unless-stopped
    env_file: .env
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    command: gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:5000 --workers 2
```

**Start:**
```bash
cp .env.example .env
# Edit .env with real values
docker-compose up -d
```

### §7.3 Heroku / Render Deployment

**`Procfile`:**
```
worker: python main.py
web: gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:$PORT
```

Heroku requires `web` dyno for HTTP endpoints and `worker` dyno for the Telegram polling bot.

### §7.4 Production vs. Development Differences

| Feature | Development | Production |
|---|---|---|
| `WEBHOOK_SECRET` | Can be empty (all requests accepted) | **Must be set** (min 32 random chars) |
| `TELEGRAM_BOT_TOKEN` | Test bot token acceptable | Production bot token required |
| Logging level | `DEBUG` | `INFO` or `WARNING` |
| SQLite file | Local path | Mounted persistent volume |
| `ALLOWED_WEBHOOK_IPS` | Empty (all IPs) | Set to TradingView webhook IPs |
| HTTPS | Optional | **Required** for webhook receiver |

### §7.5 Manual Installation

```bash
# 1. Clone repository
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git
cd 360-Crypto-Eye-Scalping-

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your values

# 4. Start the Telegram bot (polling mode)
python main.py

# 5. Start the webhook receiver (separate terminal)
gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:5000
```

---

## §8 — Testing Standards

### §8.1 Test Coverage Requirements

All 75+ tests must pass before any code is merged. Coverage targets:

| Module | Coverage Target |
|---|---|
| `bot/signal_engine.py` | ≥ 95% |
| `bot/risk_manager.py` | ≥ 95% |
| `bot/dashboard.py` | ≥ 90% |
| `bot/news_filter.py` | ≥ 90% |
| `bot/webhook.py` | ≥ 85% |
| `config.py` | ≥ 80% |

### §8.2 Test Categories

**Unit Tests (`tests/test_signal_engine.py`):**
- Zone detection: `is_discount_zone`, `is_premium_zone`
- Liquidity sweep: LONG and SHORT scenarios, edge cases
- MSS: volume threshold, displacement filter, minimum candle count
- Macro bias: all four combinations (bullish/bullish, bearish/bearish, mixed)
- Target calculation: LONG and SHORT, custom R:R ratios
- Signal formatting: `format_message()` output format verification
- `generate_signal_id()`: format validation (`SIG-` prefix + 12 hex chars)

**Unit Tests (`tests/test_risk_manager.py`):**
- 3-pair cap: enforcement, boundary conditions, cap count
- BE trigger: formula verification, double-trigger prevention
- Stale close: time boundary conditions
- Position size calculator: formula accuracy, error cases
- Persistence: save/load cycle

**Unit Tests (`tests/test_dashboard.py`):**
- Win rate: by timeframe, with mixed outcomes
- Profit factor: gross profit/loss calculation
- Edge cases: empty dashboard, all wins, all losses
- Persistence: save/load cycle

**Integration Tests:**
- Webhook: secret verification, IP allowlist, rate limiting, payload validation
- Auto-scan: full pipeline with mocked Binance data
- Thread-safety: concurrent signal operations

### §8.3 Running Tests

```bash
# Install all test dependencies (required)
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_signal_engine.py -v

# Run with coverage report
pytest tests/ --cov=bot --cov-report=term-missing

# Run thread-safety tests
pytest tests/ -v -k "thread"
```

> **CI note:** The GitHub Actions CI pipeline installs `requirements-dev.txt` (not just `requirements.txt`) to ensure test-only dependencies (pytest, pytest-asyncio, etc.) are available.

### §8.4 Test Fixtures (`tests/conftest.py`)

Key fixtures available to all tests:
- `sample_candles` — list of 30 `CandleData` objects with realistic OHLCV values
- `bullish_candles` / `bearish_candles` — directional candle sequences
- `risk_manager` — fresh `RiskManager` instance with temp file
- `dashboard` — fresh `Dashboard` instance with temp file
- `news_calendar` — `NewsCalendar` instance with no events

**Environment isolation:** `conftest.py` sets dummy environment variables (`TELEGRAM_BOT_TOKEN`, channel IDs, API keys) before any bot module imports. This prevents real network calls to Binance or Telegram during test runs. An `autouse` fixture patches `httpx` and `ccxt` clients to return mock data.

---

## §9 — File Tree (Canonical)

```
360-Crypto-Eye-Scalping/
│
├── main.py                        # Entry point — starts polling bot (imports bot.main)
├── Procfile                       # Heroku/Render: worker=bot, web=webhook
├── .env.example                   # Environment variable template (no secrets)
├── .gitignore                     # Excludes .env, *.db, *.json data files
├── requirements.txt               # Pinned Python production dependencies
├── requirements-dev.txt           # Test-only dependencies (pytest, etc.)
├── requirements-prod.txt          # Production-optimised subset of requirements.txt
├── config.py                      # Centralised config (§3.1) — all env vars
├── README.md                      # Professional project page (references Blueprint)
├── BLUEPRINT.md                   # This document — canonical authority
│
├── bot/
│   ├── __init__.py                # Package marker
│   ├── bot.py                     # Telegram bot, command handlers, schedulers (§3.4)
│   ├── signal_engine.py           # Fractal Liquidity Engine — pure computation (§3.2)
│   ├── risk_manager.py            # Safety protocols, signal lifecycle (§3.3)
│   ├── news_filter.py             # News calendar, high-impact detection (§3.7)
│   ├── news_fetcher.py            # CoinMarketCal API integration
│   ├── dashboard.py               # Transparency dashboard, statistics (§3.6)
│   ├── dashboard_web.py           # Flask routes: /dashboard, /api/stats, /api/signals
│   ├── webhook.py                 # TradingView Flask webhook receiver (§3.5)
│   ├── exchange.py                # ResilientExchange: CCXT wrapper (§3.9)
│   ├── database.py                # SQLite/SQLAlchemy persistence (§3.10)
│   ├── state.py                   # Thread-safe bot state singleton (§3.8)
│   ├── logging_config.py         # Structured JSON logging (§3.11)
│   ├── session_filter.py          # Trading session gate — London/NYC/Asia (§3.12)
│   ├── funding_rate.py            # Gate ⑧ — Funding rate sentiment (§3.13)
│   ├── open_interest.py           # Gate ⑨ — OI divergence monitor (§3.14)
│   ├── loss_streak_cooldown.py    # Smart cooldown after loss streak, RLock (§3.15)
│   ├── spot_scanner.py            # Spot gem/scam scanner (§3.16)
│   ├── ws_manager.py              # WebSocket market data manager (§3.17)
│   ├── regime_adapter.py          # Regime-adaptive signal parameters (§3.18)
│   ├── weekly_report.py           # Sunday weekly performance report (§3.20)
│   ├── gate_labels.py             # Gate key/label/symbol registry (§3.21)
│   ├── price_fmt.py               # Adaptive price formatter fmt_price() (§3.22)
│   ├── signal_router.py           # Channel routing + deduplication
│   ├── vwap.py                    # VWAP + is_near_vwap helpers
│   ├── btc_correlation.py         # BTC correlation gate
│   ├── correlation_guard.py       # Cross-pair correlation guard
│   ├── invalidation_detector.py   # Signal invalidation detector
│   ├── auto_close_monitor.py      # Auto-close monitor background job
│   ├── performance.py             # Historical performance metrics
│   ├── narrative.py               # Signal narrative generator
│   ├── postmortem.py              # Post-trade analysis
│   ├── structure_detector.py      # Market structure detection utilities
│   ├── confluence_score.py        # Confluence score calculation
│   ├── signal_tracker.py          # Signal tracking utilities
│   ├── admin_alerts.py            # Admin DM alert helpers
│   ├── backtester.py              # Walk-forward backtesting engine (§11)
│   ├── backtest_cli.py            # Backtest command-line interface (§11)
│   ├── chart_generator.py         # Chart image generation
│   ├── exchange_formatter.py      # Exchange response formatter
│   ├── funding_rate.py            # Funding rate fetcher + sentiment
│   ├── open_interest.py           # Open interest monitor
│   ├── news_filter.py             # News calendar
│   ├── news_fetcher.py            # CoinMarketCal API
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── hard_scalp.py          # CH1 gate runner (full 7 gates, HIGH only)
│   │   ├── medium_scalp.py        # CH2 gate runner (relaxed gates, HIGH+MEDIUM)
│   │   ├── easy_breakout.py       # CH3 breakout detector + BreakoutResult
│   │   └── spot_momentum.py       # CH4 spot scanner + SpotSignalResult
│   └── insights/
│       ├── __init__.py
│       ├── btc_structure.py       # CH5A — BTC 4H structure post
│       ├── fear_greed.py          # CH5B — Fear & Greed Index every 6h (uses httpx)
│       ├── news_digest.py         # CH5C — Daily news brief at 08:00 UTC
│       ├── regime_detector.py     # CH5D — BULL/BEAR/SIDEWAYS classifier (§3.19)
│       ├── daily_performance.py   # CH5E — Daily Performance Recap at 23:00 UTC
│       ├── weekly_briefing.py     # CH5F — Weekly BTC analysis on Sundays
│       ├── liquidation_map.py     # Liquidation map analysis (uses httpx)
│       └── market_briefing.py     # Market briefing generator
│
├── data/                          # Auto-created at startup (signals.json, dashboard.json, *.db)
│
└── tests/
    ├── __init__.py
    ├── conftest.py                # Shared fixtures + dummy env vars + network patches
    ├── test_signal_engine.py      # Unit tests for Fractal Liquidity Engine
    ├── test_risk_manager.py       # Unit tests for safety protocols
    ├── test_dashboard.py          # Unit tests for dashboard statistics
    ├── test_news_fetcher.py       # Unit tests for news fetcher
    ├── test_signal_tracker.py     # Unit tests for signal tracker
    ├── test_session_filter.py     # Unit tests for trading session gate
    ├── test_funding_rate.py       # Unit tests for funding rate sentiment gate
    ├── test_open_interest.py      # Unit tests for OI divergence monitor
    ├── test_loss_cooldown.py      # Unit tests for loss streak cooldown
    ├── test_fear_greed.py         # Unit tests for Fear & Greed index
    ├── test_daily_performance.py  # Unit tests for daily performance recap
    ├── test_spot_scanner.py       # Unit tests for spot gem/scam scanner
    ├── test_ws_and_fallback.py    # Unit tests for WebSocket manager
    ├── test_regime_adapter.py     # Unit tests for regime adapter
    ├── test_weekly_report.py      # Unit tests for weekly report generator
    ├── test_gate_labels.py        # Unit tests for gate label registry
    ├── test_price_fmt.py          # Unit tests for adaptive price formatter
    ├── test_separate_market_data.py # Tests for dual futures/spot market stores
    └── [... additional test files for each module]
```

---

## §10 — Coding Standards & Conventions

### §10.1 Language & Runtime

- **Python 3.12+** required. Use new-style type hints (`list[str]`, `dict[str, int]`, `X | Y`).
- No compatibility shims for Python < 3.10.

### §10.2 Type Hints

- **All** function signatures must include parameter and return type hints.
- Use `Optional[X]` or `X | None` for nullable values — be explicit.
- Use `from __future__ import annotations` at the top of each module.

### §10.3 Docstrings

- Google-style docstrings for all public functions, classes, and modules.
- Format:
  ```python
  def some_function(param: str) -> bool:
      """
      One-line summary.

      Longer description if needed.

      Parameters
      ----------
      param:
          Description of the parameter.

      Returns
      -------
      bool
          Description of the return value.

      Raises
      ------
      ValueError
          When param is empty.
      """
  ```

### §10.4 Enumerations

All enums must inherit from `(str, Enum)` to ensure JSON serialisability:
```python
class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
```
This allows `json.dumps(Side.LONG)` to produce `"LONG"` without a custom encoder.

### §10.5 Data Classes vs. Pydantic

- Use `@dataclass` for **value objects** that are internal to a module (e.g., `CandleData`, `SignalResult`, `TradeResult`).
- Use Pydantic `BaseModel` for **external data validation** (webhook payload parsing, API response models).
- Use Pydantic `BaseSettings` for **configuration** (alternative to raw `os.environ.get()`).

### §10.6 Linting & Formatting

- **Ruff** for linting and formatting (replaces Black + isort + Flake8).
- **mypy** for static type checking.
- Configuration in `pyproject.toml` or `ruff.toml`.

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy bot/ config.py
```

### §10.7 Error Handling

- Use specific exception types — avoid bare `except:` clauses.
- Use `except Exception as exc:  # noqa: BLE001` only in top-level handlers where broad catching is intentional (e.g., webhook endpoint).
- Log exceptions with `logger.exception(...)` (includes traceback) or `logger.error(...)` (no traceback) as appropriate.

### §10.8 Thread Safety

- All shared mutable state accessed from multiple threads must be protected with `threading.Lock`.
- Background APScheduler jobs run in daemon threads — treat all module-level state as potentially concurrent.
- Prefer the `BotState` singleton (§3.8) over raw module-level booleans for shared toggle flags.

### §10.9 Async Conventions

- The Telegram bot (`bot.py`) is fully async (python-telegram-bot 21.x).
- Avoid mixing async and sync code. Use the async bridge pattern (§3.4.5) when background threads need to call Telegram API.
- Use `asyncio.new_event_loop()` + `loop.run_until_complete()` in background threads — never `asyncio.run()` from a thread.

### §10.10 Constants and Magic Numbers

- All configuration values live in `config.py` (§3.1) — never hardcode thresholds in module files.
- Import constants from `config` explicitly: `from config import BE_TRIGGER_FRACTION` (not `import config`).
- Magic numbers in formulas must have inline comments explaining their meaning.

### §10.11 Commit Conventions

Use conventional commit format:
```
feat: add ATR-based dynamic zone calculation
fix: prevent double BE trigger on same signal
docs: update BLUEPRINT §3.2 with displacement filter spec
test: add thread-safety tests for RiskManager
refactor: extract exchange module from bot.py
```

---

*End of Blueprint — version `4.0.0-domination`*  
*Maintained by the 360 Crypto Eye development team.*  
*If code behaviour differs from this document, the code must be corrected to match.*

---

## §11 — Backtesting Framework

### §11.1 Overview

The backtesting framework replays historical candle data through the **exact same** 7-gate confluence engine (`bot/signal_engine.py`) used in production. It simulates the full signal lifecycle — entry, BE trigger, trailing SL, stale close, and TP hits — and produces institutional-grade performance reports.

**Zero-divergence guarantee**: the backtester imports and calls `run_confluence_check()` and all helper functions directly from `bot/signal_engine.py`. No logic is duplicated or modified.

### §11.2 Files

| File | Purpose |
|---|---|
| `bot/backtester.py` | Core engine: `HistoricalDataFetcher`, `SimulatedTrade`, `Backtester`, `BacktestResult` |
| `bot/backtest_cli.py` | Command-line interface |
| `tests/test_backtester.py` | 44 unit / integration tests |

### §11.3 `bot/backtester.py`

#### §11.3.1 `HistoricalDataFetcher`

```python
class HistoricalDataFetcher:
    def __init__(self, exchange=None, sleep_seconds=0.5): ...
    def fetch(self, symbol, timeframe, since_ms, until_ms) -> list[CandleData]: ...
```

Paginates through Binance OHLCV history using CCXT (max 1 000 candles/request).
Rate-limited with `sleep_seconds` pause between pages.

#### §11.3.2 `SimulatedTrade` dataclass

Fields: `signal_id`, `symbol`, `side`, `confidence`, `entry_price`, `stop_loss`, `tp1`, `tp2`, `tp3`, `opened_at`, `closed_at`, `close_reason`, `pnl_pct`, `be_triggered`, `max_favorable_excursion`, `max_adverse_excursion`, `bars_held`.

`close_reason` is one of: `"TP1"`, `"TP2"`, `"TP3"`, `"SL"`, `"BE"`, `"STALE"`.

#### §11.3.3 `Backtester`

```python
class Backtester:
    def __init__(
        self,
        symbol: str,
        five_min_candles: list[CandleData],
        four_hour_candles: list[CandleData],
        daily_candles: list[CandleData],
        be_trigger_fraction: float = 0.50,
        stale_hours: float = 4.0,
        tp1_rr: float = 1.5,
        tp2_rr: float = 2.5,
        tp3_rr: float = 4.0,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
        check_fvg: bool = False,
        check_order_block: bool = False,
    ): ...

    def run(self) -> BacktestResult: ...
```

Walk-forward replay with sliding windows (50 × 5m, 15 × 4H, 25 × 1D).

**Exit priority** (conservative simulation):
1. Stop-loss (worst-case — SL + TP same candle → SL wins).
2. TP3 → TP2 → TP1.
3. Break-even trigger (price covers `be_trigger_fraction` of TP1 distance).
4. Stale close after `stale_hours` × 12 bars.

Capital is compounded: risk % applied to current equity, not initial.

#### §11.3.4 `BacktestResult` dataclass

Key fields:
- `total_trades`, `wins`, `losses`, `break_evens`, `stale_closes`
- `win_rate`, `profit_factor`, `sharpe_ratio`
- `max_drawdown_pct`, `max_drawdown_duration`, `calmar_ratio`
- `avg_win_pct`, `avg_loss_pct`, `largest_win_pct`, `largest_loss_pct`
- `avg_holding_time`, `max_consecutive_wins`, `max_consecutive_losses`
- `equity_curve`, `monthly_returns`
- `long_trades`, `short_trades`, `long_win_rate`, `short_win_rate`

Methods:
- `summary() -> str` — one-line metrics string
- `print_report()` — formatted console report with go-live threshold indicators
- `to_csv(filepath: str)` — exports all trades to CSV

#### §11.3.5 Go-live Thresholds

| Check | Threshold |
|---|---|
| Minimum trades | ≥ 30 |
| Win rate | ≥ 50% |
| Profit factor | ≥ 1.5 |
| Max drawdown | ≤ 20% |
| Sharpe ratio | ≥ 1.0 |

All five checks must pass for the `print_report()` verdict to show **READY FOR LIVE DEPLOYMENT**.

### §11.4 `bot/backtest_cli.py`

```bash
python -m bot.backtest_cli --symbol BTCUSDT --start 2024-01-01 --end 2024-04-01
python -m bot.backtest_cli --multi BTCUSDT ETHUSDT --start 2024-01-01 --export results/
```

| Flag | Default | Description |
|---|---|---|
| `--symbol SYM` | — | Single symbol (mutually exclusive with `--multi`) |
| `--multi SYM [SYM …]` | — | Multiple symbols |
| `--start YYYY-MM-DD` | required | Backtest start date (UTC) |
| `--end YYYY-MM-DD` | today | Backtest end date (UTC) |
| `--capital USDT` | 10 000 | Initial capital |
| `--risk FRAC` | 0.01 | Risk fraction per trade |
| `--tp1-rr RR` | 1.5 | TP1 risk-reward ratio |
| `--tp2-rr RR` | 2.5 | TP2 risk-reward ratio |
| `--tp3-rr RR` | 4.0 | TP3 risk-reward ratio |
| `--no-fvg` | off | Disable FVG gate (Gate ⑥) |
| `--no-ob` | off | Disable Order Block gate (Gate ⑦) |
| `--export DIR` | — | Export CSV results to directory |
| `--quiet` | off | Print one-line summary only |

### §11.5 Telegram `/backtest` Command

```
/backtest SYMBOL START [END]
```

Admin-only. Runs the backtest in a thread pool via `run_in_executor` (non-blocking). Sends `⏳ Running backtest …` first, then sends the formatted performance report.

Example:
```
/backtest BTCUSDT 2024-01-01 2024-04-01
```

Reply includes: trade count, win/loss/BE/stale breakdown, win rate, profit factor, Sharpe, max drawdown, Calmar, equity change, and go-live checks.

### §11.6 Design Principles

1. **Zero divergence** — imports real `run_confluence_check()` from `bot/signal_engine.py`.
2. **Conservative simulation** — SL + TP same candle → SL wins; entry at midpoint of entry zone.
3. **Sliding windows** — same sizes as live engine (50 × 5m, 15 × 4H, 25 × 1D).
4. **Compounding capital** — risk % of current equity, not initial.
5. **Rate limiting** — configurable sleep between Binance pagination requests.
6. **No new dependencies** — uses stdlib `csv`, `argparse`, `datetime`, `statistics`, `math` plus existing `ccxt`.

---

## §12 — v2.0 Multi-Channel System

> **Added in v2.0** — Five dedicated Telegram channels with tiered gate stacks, regime-aware signal suppression, and multi-module market insights.

### §12.1 Architecture Overview

```
Binance WS/REST Data
        │
        ▼
Signal Engine (Fractal Liquidity Engine)
        │
        ▼
   SignalRouter ──────────────────────────────────────────────────────┐
        │                                                              │
        ├──► CH1 Hard Scalp     (7 gates, HIGH only)                 │
        ├──► CH2 Medium Scalp   (relaxed gates, HIGH+MEDIUM)          │
        ├──► CH3 Easy Breakout  (volume+4H+RSI, all confidence)       │
        ├──► CH4 Spot Momentum  (5 gates, 4H scan interval)           │
        └──► CH5 Market Insights (BTC Structure + Regime + News)       │
                                                                       │
                         Market Regime (BULL/BEAR/SIDEWAYS) ◄─────────┘
                         feeds back into CH1/CH2 LONG suppression
```

### §12.2 Channel Definitions

#### CH1 — Hard Scalp (`bot/channels/hard_scalp.py`)
- **Gates:** All 7 (news 60min + macro bias 1D+4H + zone 50% + sweep 7c + MSS 7c + FVG + OB)
- **Confidence filter:** HIGH only
- **Regime:** LONG suppressed in BEAR regime
- **Signal format:** Full signal with entry zone, TP1/TP2/TP3, SL, leverage
- **Env var:** `TELEGRAM_CHANNEL_ID_HARD` (falls back to `TELEGRAM_CHANNEL_ID`)

#### CH2 — Medium Scalp (`bot/channels/medium_scalp.py`)
- **Gates:** news 30min + 4H-only bias + zone 50% + sweep 10c + MSS 10c (no FVG/OB)
- **Confidence filter:** HIGH + MEDIUM
- **Regime:** LONG suppressed in BEAR regime
- **Signal format:** Full signal (same as CH1)
- **Env var:** `TELEGRAM_CHANNEL_ID_MEDIUM`

#### CH3 — Easy Breakout (`bot/channels/easy_breakout.py`)
- **Gates:** Volume spike >150% avg + 4H breakout close + RSI momentum (>55 LONG / <45 SHORT)
- **Confidence filter:** ALL (informational alerts)
- **Regime:** Never suppressed
- **Signal format:** Simplified `⚡ MOMENTUM ALERT` (entry, TP1, TP2, SL — no TP3, no leverage)
- **Env var:** `TELEGRAM_CHANNEL_ID_EASY`

#### CH4 — Spot Momentum (`bot/channels/spot_momentum.py`)
- **Gates:** Weekly bias (10w SMA) + accumulation zone (within 15% of 90d low) + volume building (3d > 90d avg) + RSI 1D 40–60 + 4H higher lows
- **Scan frequency:** Every `CH4_SCAN_INTERVAL_HOURS` hours (default 4)
- **Signal format:** `🎯 SPOT SETUP` — entry zone, TP1/TP2/TP3 (+15%/+30%/+50%), SL, "SPOT ONLY — No Leverage"
- **Env var:** `TELEGRAM_CHANNEL_ID_SPOT`

#### CH5 — Market Insights (`bot/insights/`)
- **5A:** BTC Structure post every 4H (`btc_structure.py`)
- **5B:** Fear & Greed Index every 6 hours (`fear_greed.py`) — score, label, emoji, contextual advice
- **5C:** Daily news digest at 08:00 UTC (`news_digest.py`)
- **5D:** Regime detector at 09:00 UTC (`regime_detector.py`) — sets `BotState.market_regime`
- **5E:** Daily Performance Recap at 23:00 UTC (`daily_performance.py`) — full stats with best/worst signal
- **5F:** Weekly briefing every Sunday 18:00 UTC (`weekly_briefing.py`)
- **Env var:** `TELEGRAM_CHANNEL_ID_INSIGHTS`

### §12.3 Signal Router (`bot/signal_router.py`)

The `SignalRouter` class manages channel routing and deduplication:
- **Channel mapping:** `ChannelTier` enum (HARD/MEDIUM/EASY/SPOT/INSIGHTS) → channel ID
- **Deduplication:** If the same symbol fires on CH1 within `DEDUP_WINDOW_MINUTES` (default 15), CH2 and CH3 are suppressed
- **Graceful degradation:** Channels with ID=0 are silently skipped

### §12.4 Market Regime (`bot/insights/regime_detector.py`)

Classifies market into three states daily at 09:00 UTC:
- **BULL:** BTC price > 200d SMA AND Fear & Greed > 50
- **BEAR:** BTC price < 200d SMA AND Fear & Greed < 40
- **SIDEWAYS:** Anything else
- **UNKNOWN:** Fewer than 50 daily candles available (graceful degradation)

**Graceful degradation:** Falls back to 50-day SMA when 50–199 candles are available (instead of returning `UNKNOWN`). Only returns `UNKNOWN` when fewer than 50 candles exist. See §3.19 for full details.

In **BEAR** regime:
- CH1 and CH2 suppress new LONG signals automatically
- CH3 (Easy Breakout) is unaffected — informational alerts continue
- CH4 (Spot) is unaffected — accumulation longs are valid regardless of regime

Regime is stored in `BotState.market_regime` and accessible via the `/regime` command. The `get_regime_adjustments()` function in `bot/regime_adapter.py` (§3.18) maps the regime to concrete TP3/max_signals/risk_modifier parameters.

### §12.5 Bug Fixes in Signal Engine

Three critical bugs fixed in v2.0 that caused zero signals on live VPS:

**Bug 1 — `assess_macro_bias` too strict** (fixed):
- Old: required `close > prev_close AND close > SMA-20` (AND — too strict)
- New: requires `close > prev_close AND (close > SMA-20 OR close > EMA-9)` (OR — handles ranging markets)

**Bug 2 — MSS uses all 49 prior candles** (fixed):
- Old: `swing_high = max(c.high for c in prior_candles)` — all candles (~4 hours)
- New: `swing_high = max(c.high for c in prior_candles[-7:])` — last 7 candles (~35 min)

**Bug 3 — Liquidity sweep window too narrow** (fixed):
- Old: `candles[-3:]` — only 15 minutes of data
- New: `candles[-15:]` — 75 minutes (wider sweep detection window; previously intermediate fix used `candles[-7:]`)

**Bug 4 — No gate-level logging** (fixed):
- Added `[GATE_FAIL]` and `[GATE_FAIL][RELAXED]` INFO-level log entries in `run_confluence_check()` and `run_confluence_check_relaxed()` showing exactly which gate killed each scan
- All gates are now evaluated up-front and logged in a single structured line; near-miss WARNING emitted when exactly one gate fails (see §3.2)

### §12.6 New Commands

| Command | Description |
|---------|-------------|
| `/regime` | Show current BULL/BEAR/SIDEWAYS regime and its effect on signal generation |
| `/channels` | Show all 5 channel IDs and their configuration status |
| `/spot_scan [on\|off]` | Enable/disable spot gem scanner |
| `/spot_status` | Show spot scanner health: enabled, pair count, last scan, gem/scam counts |
| `/scam_check SYMBOL` | Run manual scam detection on a spot pair |
| `/status` | Extended status with per-channel breakdown, performance stats, trailing SL state |

### §12.7 Configuration Reference (v2.0 additions)

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_CHANNEL_ID_HARD` | `0` | CH1 Hard Scalp channel (falls back to `TELEGRAM_CHANNEL_ID`) |
| `TELEGRAM_CHANNEL_ID_MEDIUM` | `0` | CH2 Medium Scalp channel |
| `TELEGRAM_CHANNEL_ID_EASY` | `0` | CH3 Easy Breakout channel |
| `TELEGRAM_CHANNEL_ID_SPOT` | `0` | CH4 Spot Momentum channel |
| `TELEGRAM_CHANNEL_ID_INSIGHTS` | `0` | CH5 Market Insights channel |
| `CH2_NEWS_WINDOW_MINUTES` | `30` | Relaxed news window for CH2 (vs 60 for CH1) |
| `CH3_VOLUME_SPIKE_RATIO` | `1.5` | Volume must be 150% of 20-period avg for CH3 |
| `CH4_SCAN_INTERVAL_HOURS` | `4` | Spot scan frequency in hours |
| `CH4_ACCUMULATION_THRESHOLD` | `0.15` | Price within 15% of 90d low for spot entry |
| `BTC_FEAR_GREED_URL` | `https://api.alternative.me/fng/` | Fear & Greed API endpoint |
| `REGIME_DETECTOR_ENABLED` | `true` | Enable/disable regime classification |
| `DEDUP_WINDOW_MINUTES` | `15` | Suppress CH2/CH3 if CH1 fired same symbol within N minutes |

### §12.8 Technical Standards Added in v4.0

- **`httpx` standardization:** All async HTTP calls now use `httpx` (replacing `requests`). `fear_greed.py` and `liquidation_map.py` use `httpx.AsyncClient` for proper async I/O.
- **Price formatting standardized:** All signal message prices use `fmt_price()` from `bot/price_fmt.py` (§3.22) instead of hardcoded `:.4f`.
- **Gate labels centralised:** `bot/gate_labels.py` (§3.21) is the single source of truth for all gate keys, labels, and symbols.
- **Dual market architecture:** Separate `futures_market_data`/`futures_ws` and `spot_market_data`/`spot_ws` instances with backward-compatible aliases.
- **1D buffer expanded:** `_BUF_1D = 210` (up from 30) to support the 200-day SMA regime detector.
- **CH3/CH4 signal registration:** `BreakoutResult` (CH3) and `SpotGemResult` (CH4) are now wrapped in `SignalResult` and registered via `risk_manager.add_signal()` before posting to Telegram.

### §12.9 New v4.0 File Tree Additions

```
bot/
├── spot_scanner.py            # Spot gem/scam scanner (§3.16)
├── ws_manager.py              # WebSocket market data manager (§3.17)
├── regime_adapter.py          # Regime-adaptive signal parameters (§3.18)
├── weekly_report.py           # Sunday weekly performance report (§3.20)
├── gate_labels.py             # Gate key/label/symbol registry (§3.21)
├── price_fmt.py               # Adaptive price formatter (§3.22)
└── insights/
    └── regime_detector.py     # Updated: 50-day SMA fallback, UNKNOWN handling (§3.19)
tests/
├── conftest.py                # Updated: dummy env vars + network patches
├── test_spot_scanner.py
├── test_ws_and_fallback.py
├── test_regime_adapter.py
├── test_weekly_report.py
├── test_gate_labels.py
├── test_price_fmt.py
└── test_separate_market_data.py
```

---

## §13 — Competitive Edge: Why 360 Eye Dominates

### §13.1 Feature Comparison vs Top Crypto Channels

| Feature | 360 Crypto Eye | Palm | Crypto Banter | Jacob Bury |
|---------|---------------|------|---------------|------------|
| Multi-channel tiers | 5 channels ✅ | 1 ❌ | 1 ❌ | 1 ❌ |
| Full automation | Zero manual ✅ | Manual ❌ | Manual ❌ | Manual ❌ |
| Real-time risk mgmt | BE + Trail + Cap ✅ | None ❌ | None ❌ | None ❌ |
| News blackout | Auto CoinMarketCal ✅ | None ❌ | None ❌ | None ❌ |
| Funding rate edge | Contrarian gate ✅ | None ❌ | None ❌ | None ❌ |
| OI divergence | Auto-detected ✅ | None ❌ | None ❌ | None ❌ |
| Loss streak protection | Auto-cooldown ✅ | None ❌ | None ❌ | None ❌ |
| Session awareness | London/NYC filter ✅ | None ❌ | None ❌ | None ❌ |
| Performance transparency | Live dashboard ✅ | None ❌ | None ❌ | None ❌ |
| Spot + Futures + Insights | All-in-one ✅ | Futures only ❌ | Mixed ❌ | Futures only ❌ |

### §13.2 The 360 Eye Advantage

No other crypto signal channel can claim:
1. **Zero human intervention** — every signal is algorithmically generated, tracked, and closed
2. **5 differentiated channels** — something for every trader profile
3. **Real-time SL management** — break-even, trailing, and stale-close automation
4. **Institutional transparency** — Sharpe, drawdown, equity curve posted daily
5. **Smart cooldown** — protects members during drawdowns automatically
6. **Market regime awareness** — suppresses wrong-side trades in bear markets
7. **Funding rate contrarian edge** — detects crowded trades before they unwind
8. **Open interest intelligence** — sees what smart money is actually doing
