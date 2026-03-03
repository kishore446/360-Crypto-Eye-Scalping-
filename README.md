# 👁️ 360 Crypto Eye Scalping Signals

A production-ready Python middleware that implements the **Fractal Liquidity Engine** — a multi-timeframe confluence system for Binance Futures scalping signals delivered via Telegram.

---

## I. Core Strategy: Fractal Liquidity Engine

| Layer | Timeframe | Purpose |
| :--- | :--- | :--- |
| Market Bias | 1D & 4H | Trend direction filter |
| Setup | 15m | Order block & FVG identification |
| Execution | 5m | MSS / ChoCh + Volume trigger |

**Entry Logic Gate** — all four conditions must be met simultaneously:

1. Price is in a **Discount** (Long) or **Premium** (Short) zone.
2. A **Liquidity Sweep** (stop-hunt) has occurred at the key level.
3. A **5m Change of Character (ChoCh)** with above-average volume is confirmed.
4. No high-impact news event (FED/CPI) falls within the next **60 minutes**.

---

## II. System Architecture

```
TradingView Webhook Alert
        │
        ▼
bot/webhook.py  (Flask endpoint — verifies secret, parses payload)
        │
        ▼
bot/signal_engine.py  (Confluence checks: zone / sweep / MSS / news)
        │
        ▼
bot/risk_manager.py  (3-Pair Cap · BE trigger · Stale-close)
        │
        ▼
Telegram Bot API  ──►  Channel  (-1003851389127)
        │
        ▼
bot/dashboard.py  (Win-rate · Profit Factor · Live PnL log)
```

---

## III. Signal Template

Every broadcast follows this exact format:

```
🚀 #SYMBOL/USDT (LONG|SHORT) | 360 EYE SCALP
Confidence: High/Medium

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

## IV. Bot Commands

| Command | Access | Action |
| :--- | :--- | :--- |
| `/signal_gen SYMBOL LONG\|SHORT` | Admin | Auto-scans and generates a formatted 360 Eye signal. |
| `/move_be [SYMBOL]` | Admin | Broadcasts "Move SL to Entry (Risk-Free Mode ON)." Records TP1 result in dashboard. |
| `/trail_sl` | Admin | Toggles auto-trailing SL behind every 5m Higher Low / Lower High. |
| `/news_caution` | Admin | Freezes new signals; triggers "Close Partials" recommendation on active trades. |
| `/risk_calc <balance> <entry> <sl>` | User | Calculates exact position size based on SL distance and account balance. |
| `/close_signal SYMBOL OUTCOME PNL` | Admin | Closes a signal, records WIN/LOSS/BE + PnL in the dashboard, broadcasts summary. |

---

## V. Safety Protocols

1. **Break-Even Trigger** — SL is moved to entry when price covers 50 % of the distance to TP1.
2. **3-Pair Cap** — Maximum **3 active signals** on the same side at any time to prevent total-market-flush exposure.
3. **Stale Close** — Auto-close or alert when a scalp remains in the entry zone for **> 4 hours** without triggering.
4. **News Blackout** — All new signal generation is frozen when a HIGH-impact event is scheduled within **60 minutes**.

---

## VI. Dashboard Parameters

The live transparency log tracks:

- **Real-Time Win Rate %** — broken down by entry timeframe (5m / 15m / 1h).
- **Profit Factor** — `Gross Profit ÷ Gross Loss`.
- **Current PnL** — floating profit/loss across all open 360 Eye signals.

Results are persisted to `dashboard.json` and survive process restarts.

---

## VII. Getting Started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Bot token issued by [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHANNEL_ID` | Numeric ID of the broadcast channel (e.g. `-1003851389127`) |
| `ADMIN_CHAT_ID` | Your Telegram user ID (admin-only commands) |
| `WEBHOOK_SECRET` | Random secret for TradingView webhook authentication |
| `COINMARKETCAL_API_KEY` | Optional — enables live high-impact news filtering |
| `SIGNALS_FILE` | Path for active-signal persistence (default: `signals.json`) |
| `DASHBOARD_LOG_FILE` | Path for trade results log (default: `dashboard.json`) |

Or export them directly:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token-from-botfather"
export TELEGRAM_CHANNEL_ID="-1003851389127"
export ADMIN_CHAT_ID="710718010"
export WEBHOOK_SECRET="your-strong-random-secret"
```

### 3. Run the Telegram bot (polling mode)

```bash
python main.py
```

### 4. Run the TradingView webhook receiver

```bash
python -m bot.webhook
# or via gunicorn in production:
gunicorn "bot.webhook:create_app()" --bind 0.0.0.0:5000
```

### 5. Configure TradingView alert

Send a POST request to `http://your-server:5000/webhook` with:

```json
{
  "symbol": "BTCUSDT",
  "side": "LONG",
  "price": 65000.0,
  "range_low": 63000.0,
  "range_high": 67000.0,
  "key_level": 64500.0,
  "stop_loss": 63800.0
}
```

Include header: `X-Webhook-Secret: your-strong-random-secret`

---

## VIII. Project Structure

```
360-Crypto-Eye-Scalping/
├── main.py                   # Entry point — starts the polling bot
├── Procfile                  # Heroku/Render deployment (worker + web)
├── .env.example              # Environment variable template
├── config.py                 # Centralised configuration (env-var backed)
├── requirements.txt          # Python dependencies
├── bot/
│   ├── __init__.py
│   ├── bot.py                # Telegram bot + command handlers
│   ├── signal_engine.py      # Fractal Liquidity Engine (confluence logic)
│   ├── risk_manager.py       # BE trigger · 3-pair cap · stale-close · JSON persistence
│   ├── news_filter.py        # High-impact news calendar
│   ├── dashboard.py          # Transparency log + statistics
│   └── webhook.py            # TradingView webhook receiver (Flask)
└── tests/
    ├── conftest.py
    ├── test_signal_engine.py
    ├── test_risk_manager.py
    └── test_dashboard.py
```

---

## IX. Running Tests

```bash
pytest tests/ -v
```

All 75 tests cover: zone detection, liquidity sweep, MSS/ChoCh, macro bias, target calculation, signal formatting, 3-pair cap, BE trigger, stale-close, position sizing, dashboard statistics, and news filtering.