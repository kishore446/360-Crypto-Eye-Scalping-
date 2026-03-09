# Changelog

All notable changes to **360 Crypto Eye Scalping** are documented here.

## [2.0.0] — 2026-03-09

### Critical Bug Fixes

- **BUG #1 — CH5 Insights Channel Pollution (FIXED):** `_broadcast_close()` and `_broadcast_close_raw()` in `bot/auto_close_monitor.py` now route messages to the signal's **origin channel** (`signal.origin_channel`) instead of always routing to CH5 Insights. Close summaries, SL/TP hits, stale closes, and invalidation alerts for CH1-CH4 signals now reach the correct channel. Added `get_tier_for_channel_id(channel_id)` reverse-lookup method to `SignalRouter`.
- **BUG #2 — CloseResult.channel_tier Always "AGGREGATE" (FIXED):** `_check_tp_sl_hit()` and `_build_stale_result()` now derive `channel_tier` from `signal.origin_channel` via the reverse-lookup, enabling accurate per-channel win rate tracking in the dashboard.
- **BUG #3 — TP Sequential Tracking (FIXED):** Added `_tp_levels_hit: dict[str, set[str]]` tracker to `AutoCloseMonitor`. When price gaps directly to TP2 or TP3, lower TPs are recorded sequentially (TP1 first, then TP2, then TP3) to correctly feed the partial position system.
- **BUG #4 — Bot Instance Created Every Broadcast (FIXED):** `AutoCloseMonitor.__init__()` now accepts an optional `telegram_bot` parameter. When provided, the shared bot instance is reused for all broadcasts instead of creating a new `Bot()` on every message.
- **BUG #5 — Macro Bias Single Candle (FIXED):** `assess_macro_bias()` in `bot/signal_engine.py` now uses a **3-day close comparison** (at least 2 of 3 daily closes rising/falling) instead of a single candle comparison. A single red candle in a strong bull trend no longer kills all long signals.
- **BUG #6 — Volume Percentile All Candles (FIXED):** `detect_market_structure_shift()` now uses only the **last 20 candles** for volume rank calculation instead of the entire candle history, providing relevant volume context.

### New Features

#### New Indicators (bonus scores, non-blocking)
- **MACD Momentum Confirmation** — `calculate_macd()` and `detect_macd_confirmation()` added to `bot/signal_engine.py`. Wired into `run_confluence_check()` as +10 bonus score when MACD histogram aligns with trade direction and a crossover occurred within the last 3 candles.
- **Bollinger Band Squeeze Detection** — `detect_bollinger_squeeze()` added, returns True when bandwidth (upper-lower)/middle < 4%. Wired as +10 bonus score.
- **CVD (Cumulative Volume Delta)** — `calculate_cvd()` and `detect_cvd_confirmation()` added, estimating buy/sell volume pressure. Wired as +10 confirm / -5 divergence.
- **EMA Ribbon (8/13/21/55)** — `detect_ema_ribbon_alignment()` added, checks if EMAs are fully stacked bullishly (LONG) or bearishly (SHORT). Wired as +10 bonus.

#### New Channels (CH6-CH9)
- **CH6 — Altcoin Gems** (`TELEGRAM_CHANNEL_ID_ALTGEMS`): Low-cap DCA/swing signals
- **CH7 — Whale Tracker** (`TELEGRAM_CHANNEL_ID_WHALE`): Dedicated whale movement + liquidation alerts. Whale alerts now route to CH7 if configured, falling back to CH5.
- **CH8 — Education** (`TELEGRAM_CHANNEL_ID_EDUCATION`): Post-trade reviews, pattern education
- **CH9 — VIP Discussion** (`TELEGRAM_CHANNEL_ID_VIP`): Member analysis & discussion
- All new channels default to `0` (disabled) — fully backward compatible.

#### Confluence Scoring Updates
- **`ConfluenceFactors`** — New fields: `macd_confirmed`, `bb_squeeze`, `cvd_confirmed`, `ema_ribbon_aligned`, `funding_favorable`, `oi_divergence`, `btc_correlated`, `rsi_divergence`, `vwap_favorable`
- **`WEIGHTS`** — `session_active` increased from 5 → 10; `in_discount_premium_zone` increased from 15 → 20; new factors `macd_confirmed`, `bb_squeeze`, `cvd_confirmed`, `ema_ribbon_aligned` each weighted at 10.
- `build_confluence_factors()` now evaluates and returns all new indicator factors.

#### Postmortem Routing Fix
- Postmortem messages in `bot/bot.py` now route to the signal's origin channel instead of always CH5 Insights.

#### Whale Alert Improvements
- `bot/insights/whale_alerts.py` migrated from `requests` to `httpx` (async HTTP)
- Added `get_target_channel_id()` helper that returns CH7 if configured, falling back to CH5

### Configuration
- Added `telegram_channel_id_altgems`, `telegram_channel_id_whale`, `telegram_channel_id_education`, `telegram_channel_id_vip` to both Pydantic Settings and fallback config.
- Updated `.env.example` with CH6-CH9 entries (all default to `0`).

### Signal Router
- `ChannelTier` enum extended with `ALTGEMS`, `WHALE_TRACKER`, `EDUCATION`, `VIP_DISCUSSION`
- `SignalRouter.__init__()` accepts new optional `channel_altgems`, `channel_whale`, `channel_education`, `channel_vip` parameters
- New `get_tier_for_channel_id(channel_id)` reverse-lookup method

### Tests
- `test_new_features.py` — 40+ new tests covering all bug fixes and new features
- `test_auto_close_monitor.py` — Updated for sequential TP tracking and new `origin_channel` field
- `test_confluence_score.py` — Updated for new factors and weights
- `test_channel_cleanup.py` — Updated for new optional CH6-CH9 tiers

## [Unreleased]

### Added
- `bot/state.py` — Thread-safe `BotState` singleton replacing global booleans
- `bot/logging_config.py` — Structured JSON logging with `JsonFormatter` and `generate_signal_id()`
- `bot/database.py` — SQLite persistence layer with WAL mode and JSON migration utilities
- `bot/exchange.py` — Resilient CCXT exchange client with circuit breaker, retry, and candle caching
- `bot/signal_engine.py` — `LOW` confidence level, `signal_id` field, `calculate_atr()`, `detect_fair_value_gap()`, `detect_order_block()`, displacement filter for MSS detection
- `bot/dashboard.py` — Advanced metrics: Sharpe ratio, max drawdown, average holding time, win/loss streaks, equity curve, per-symbol performance
- `bot/webhook.py` — IP allowlisting, per-IP rate limiting, Pydantic payload validation, `X-Request-ID` response header, enriched `/health` endpoint
- `config.py` — Pydantic Settings rewrite with backward-compatible module-level aliases
- `Dockerfile`, `docker-compose.yml`, `.dockerignore` — Container deployment support
- `.github/workflows/ci.yml` — GitHub Actions CI pipeline
- `pyproject.toml` — Ruff and mypy configuration
- `requirements-dev.txt` — Development dependencies

### Changed
- `bot/risk_manager.py` — All `_signals` list mutations now protected by `threading.Lock`
- `bot/bot.py` — Global booleans replaced by `BotState` singleton; safer `asyncio` loop handling in background jobs
