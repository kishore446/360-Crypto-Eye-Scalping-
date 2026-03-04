# Changelog

All notable changes to **360 Crypto Eye Scalping** are documented here.

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
