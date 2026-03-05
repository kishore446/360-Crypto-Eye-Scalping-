# 👁️ 360 Crypto Eye Scalping Signals

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-75%2B%20passing-brightgreen)
![Version](https://img.shields.io/badge/version-2.0.0--institutional-blueviolet)

**An institutional-grade, multi-timeframe confluence signal engine for Binance Futures scalping — delivered via Telegram.**

The system implements the **Fractal Liquidity Engine**: a 7-gate signal filter that combines macro bias (1D/4H), discount/premium zones, liquidity sweeps, market structure shifts, fair value gaps, order blocks, and news blackouts. A signal is only generated when all seven conditions align simultaneously.

> 📐 For the complete technical specification — every function signature, data flow, configuration parameter, safety protocol, and architectural decision — see [`BLUEPRINT.md`](BLUEPRINT.md).

---

## ✨ Feature Highlights

- **7-gate confluence engine** — eliminates low-quality setups at the source
- **Multi-timeframe analysis** — 1D + 4H bias, 15m setup, 5m execution
- **Autonomous background scanner** — no TradingView subscription required
- **4 automated safety protocols** — BE trigger, 3-pair cap, stale close, news blackout
- **TradingView webhook integration** — optional real-time alert routing
- **Live transparency dashboard** — win rate, profit factor, Sharpe ratio, drawdown
- **ATR-based dynamic zones** — adapts to live volatility (no hardcoded percentages)
- **Institutional signal format** — copy-trade ready, Signal ID for full audit trail
- **SQLite persistence** — signal lifecycle survives process restarts

---

## 🏗️ Architecture

```
TradingView Webhook / Auto-Scanner
        │
        ▼
bot/webhook.py  (Flask — secret verification, payload validation, rate limiting)
        │
        ▼
bot/exchange.py  (ResilientExchange — circuit breaker, backoff, TTL cache)
        │
        ▼
bot/signal_engine.py  (Fractal Liquidity Engine — 7-gate confluence)
        │
        ▼
bot/risk_manager.py  (Thread-safe — 3-pair cap, BE trigger, stale-close)
        │
        ▼
bot/database.py  (SQLite/SQLAlchemy — audit trail, signal lifecycle)
        │
        ▼
Telegram Bot API  ──►  Channel broadcast
        │
        ▼
bot/dashboard.py  (Sharpe, drawdown, equity curve, win-rate by TF)
```

For the annotated module descriptions, see [Blueprint §9](BLUEPRINT.md#9--file-tree-canonical).

---

## 🚀 Quickstart

### Option A — Docker (Recommended)

```bash
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git
cd 360-Crypto-Eye-Scalping-

cp .env.example .env
# Edit .env with your values (see Configuration section below)

docker-compose up -d
```

### Option B — Manual Installation

```bash
# 1. Clone and install dependencies
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git
cd 360-Crypto-Eye-Scalping-
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your values

# 3. Start the Telegram bot
python main.py

# 4. Start the webhook receiver (separate terminal)
gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:5000
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and populate the required values:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Bot token issued by [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHANNEL_ID` | Numeric ID of the broadcast channel (e.g. `-100XXXXXXXXXX`) |
| `ADMIN_CHAT_ID` | Your Telegram user ID (admin-only commands) |
| `WEBHOOK_SECRET` | Min 32-char random secret for TradingView webhook auth |

### Key Optional Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `COINMARKETCAL_API_KEY` | `""` | Enables live high-impact news filtering |
| `AUTO_SCAN_PAIRS` | `""` | Comma-separated watchlist pairs (empty = all 200+ pairs) |
| `AUTO_SCAN_INTERVAL_SECONDS` | `60` | Fallback poll interval when WS is degraded (≥60s) |
| `AUTO_SCAN_ENABLED_ON_BOOT` | `true` | Start auto-scanner automatically on boot; set to `false` to require manual `/auto_scan` |
| `MAX_SAME_SIDE_SIGNALS` | `5` | Same-side signal limit |
| `SESSION_FILTER_ENABLED` | `false` | Restrict signals to London+NYC hours only; `false` enables 24/7 scanning |
| `STALE_SIGNAL_HOURS` | `4` | Auto-close threshold |
| `BE_TRIGGER_FRACTION` | `0.50` | BE trigger at 50% of TP1 distance |

> 📋 For the complete configuration reference with all 25+ variables, validation rules, and defaults, see [Blueprint §3.1](BLUEPRINT.md#31-configpy--centralised-configuration).

---

## 📋 Command Reference

| Command | Access | Action |
| :--- | :--- | :--- |
| `/signal_gen SYMBOL LONG\|SHORT` | Admin | Run full confluence on symbol and broadcast signal if gates pass |
| `/move_be [SYMBOL]` | Admin | Move SL to entry (Risk-Free Mode). Records TP1 WIN in dashboard |
| `/trail_sl` | Admin | Toggle auto-trailing SL (60s interval, Higher Low / Lower High) |
| `/auto_scan` | Admin | Toggle background auto-scanner across all watchlist pairs |
| `/news_caution` | Admin | Toggle news freeze; lists active signals with partial-close advisory |
| `/risk_calc <balance> <entry> <sl>` | User | Calculate exact position size from account balance and SL distance |
| `/close_signal SYMBOL OUTCOME PNL` | Admin | Close signal, record WIN/LOSS/BE + PnL%, broadcast summary |

> 📋 Full command specification including parameters and broadcast behaviour: [Blueprint §3.4.3](BLUEPRINT.md#343-command-handlers).

---

## 🔄 TradingView Webhook Integration

Send a POST request to `http://your-server:5000/webhook`:

```json
{
  "symbol": "BTCUSDT",
  "side": "LONG"
}
```

Include header: `X-Webhook-Secret: <your-webhook-secret>`

Optional fields (`price`, `range_low`, `range_high`, `key_level`, `stop_loss`) are fetched from Binance automatically if omitted.

Health check endpoint: `GET /health`

> 📋 Full webhook security and rate limiting specification: [Blueprint §3.5](BLUEPRINT.md#35-botwebhookpy--tradingview-webhook-receiver).

---

## 📊 Signal Format

Every Telegram broadcast follows this standardised format:

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

---

## 🛡️ Safety Protocols

| Protocol | Default | Description |
| :--- | :--- | :--- |
| **Break-Even Trigger** | 50% of TP1 | SL automatically moved to entry when triggered |
| **3-Pair Cap** | 3 signals | Max concurrent signals per side to prevent directional overexposure |
| **Stale Close** | 4 hours | Auto-close alert if entry zone is untouched |
| **News Blackout** | 60 min window | All new signals frozen near HIGH-impact events |

> 📋 Full safety protocol specifications with trigger formulas and broadcast templates: [Blueprint §5](BLUEPRINT.md#5--safety-protocols-complete-reference).

---

## 📈 Dashboard

The live transparency dashboard tracks:

- **Win Rate %** — filtered by timeframe (5m / 15m / 1h) and overall
- **Profit Factor** — Gross Profit ÷ Gross Loss
- **Sharpe Ratio** — risk-adjusted returns
- **Max Drawdown** — peak-to-trough percentage
- **Equity Curve** — cumulative PnL over time
- **Current Open PnL** — floating profit/loss across all active signals

Results are persisted to SQLite (with JSON fallback) and survive process restarts.

> 📋 All dashboard formulas: [Blueprint §6](BLUEPRINT.md#6--dashboard-parameters--formulas).

---

## 🏗️ Project Structure

```
360-Crypto-Eye-Scalping/
├── main.py                   # Entry point — starts the polling bot
├── Procfile                  # Heroku/Render deployment (worker + web)
├── .env.example              # Environment variable template (no secrets)
├── config.py                 # Centralised configuration (§3.1)
├── requirements.txt          # Pinned Python dependencies
├── README.md                 # This file
├── BLUEPRINT.md              # Canonical technical reference
├── bot/
│   ├── bot.py                # Telegram bot + command handlers (§3.4)
│   ├── signal_engine.py      # Fractal Liquidity Engine — pure computation (§3.2)
│   ├── risk_manager.py       # Safety protocols, signal lifecycle (§3.3)
│   ├── news_filter.py        # High-impact news calendar (§3.7)
│   ├── news_fetcher.py       # CoinMarketCal API integration
│   ├── dashboard.py          # Transparency log + statistics (§3.6)
│   └── webhook.py            # TradingView webhook receiver (§3.5)
└── tests/
    ├── conftest.py
    ├── test_signal_engine.py
    ├── test_risk_manager.py
    └── test_dashboard.py
```

> 📋 Full annotated file tree: [Blueprint §9](BLUEPRINT.md#9--file-tree-canonical).

---

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=bot --cov-report=term-missing
```

All 75+ tests cover: zone detection, liquidity sweep, MSS/ChoCh, macro bias, target calculation, signal formatting, 3-pair cap, BE trigger, stale-close, position sizing, dashboard statistics, and news filtering.

> 📋 Full testing standards and coverage targets: [Blueprint §8](BLUEPRINT.md#8--testing-standards).

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-improvement`
3. Verify all tests pass: `pytest tests/ -v`
4. Check that changes conform to the canonical specification in `BLUEPRINT.md`
5. Submit a pull request with a clear description

When modifying any module, refer to the relevant Blueprint section to ensure the change is consistent with the documented architecture. **If code behaviour differs from the Blueprint, the code must be corrected.**

---

## 📜 License

MIT License — see `LICENSE` for details.