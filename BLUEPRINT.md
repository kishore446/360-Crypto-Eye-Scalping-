# 360 Crypto Eye: Binance Futures Signal Blueprint

## Overview

Three Futures Channels:

| Channel | Timeframe | Goal | Signal Frequency |
|---------|-----------|------|----------------|
| Scalping | 1–5 min | Fast micro-moves | Every candle / second scan |
| Intraday / Swing | 15–60 min | Multi-hour moves | Every 5–15 min |
| Trend / Positional | 4H–1D | Daily trend capture | Every daily candle |

Universal Principles:

- Trade only top 50–100 liquid pairs.
- Multi-layer confirmation required: Trend + Momentum + Volume + Volatility.
- Avoid choppy/illiquid periods (low ATR + RSI ~50).
- Adaptive risk: max 1–2% capital per trade, position sizing based on ATR.

---

## Channel 1: Scalping / Quick Trades (1–5 min)

**Filters & Logic:**

1. Trend Filter: EMA9, EMA21, EMA50
   - EMA9 > EMA21 > EMA50 → Uptrend
   - EMA9 < EMA21 < EMA50 → Downtrend
2. Momentum Filter: RSI5 or Stochastic 5,3,3
   - RSI <30 → Long
   - RSI >70 → Short
3. Volume Filter: Current candle volume ≥ 1.5× last 20-candle average
4. Volatility Filter: ATR14 > last 20-candle average
5. Entry Confirmation: Candle bounce from EMA ribbon + momentum alignment
6. Exit Strategy:
   - Take Profit: 0.3–0.6%
   - Stop Loss: trailing 0.2–0.3% behind recent swing

---

## Channel 2: Intraday / Swing (15–60 min)

**Filters & Logic:**

1. Trend Filter: EMA50 & EMA200 crossover
2. Momentum Filter: MACD histogram + RSI14
3. Support/Resistance Filter: Fibonacci 38–61% / Pivot points
4. Volume Filter: Candle volume ≥ 1.3× last 20-candle average
5. Volatility Filter: ATR > median ATR of last 50 candles

Entry Confirmation: Trend + Momentum + S/R alignment; avoid chasing breakouts.

Exit Strategy:

- Take Profit: 1–2× ATR14
- Stop Loss: below/above nearest S/R

---

## Channel 3: Trend / Positional (4H–1D)

**Filters & Logic:**

1. Primary Trend Filter: EMA50 & EMA200 alignment
2. Multi-Timeframe Confirmation: H4 + Daily
3. Momentum Filter: RSI14 >55 Long / <45 Short + MACD
4. Liquidity Filter: Only pairs with daily volume > $100M
5. Volatility Filter: ATR > threshold
6. Fundamental / Market Filter: Avoid major news events (CPI, FOMC, Binance updates)

Entry Confirmation: Daily candle close confirms trend + volume spike

Exit Strategy:

- Take Profit: 2–3× ATR
- Stop Loss: below/above previous swing low/high

---

## Universal Filters & Enhancements

- Pair Selection: Top 50–100 by liquidity + ATR
- Time-of-Day Filter: Avoid 00:00–06:00 UTC
- Adaptive Risk Management: Position sizing scaled to volatility
- Choppy Market Avoidance: Skip trades if ATR < median ATR AND RSI ~50
- Multi-Layer Confirmation:
  - Scalping → 3 filters
  - Intraday → 4 filters
  - Trend → 5 filters

---

## Visual Flowcharts

**1. Scalping**
Start → Select Liquid Pair → EMA Trend Check → RSI/Stoch → Volume Spike → ATR Filter → All Filters Passed?
→ No → Wait Next Candle
→ Yes → Entry Signal → Exit TP 0.3–0.6% / SL trailing 0.2–0.3%

**2. Intraday / Swing**
Start → Select Liquid Pair → EMA50/200 Trend → MACD/RSI Momentum → S/R Alignment → Volume Spike → ATR Filter → All Filters Passed?
→ No → Wait
→ Yes → Entry Signal → Exit TP 1–2× ATR / SL at S/R

**3. Trend / Positional**
Start → Select Liquid Pair (Volume > $100M) → EMA50/200 Trend → Multi-Timeframe Check → RSI/MACD → ATR Filter → Market Filter → All Filters Passed?
→ No → Wait Next Candle
→ Yes → Entry Signal → Exit TP 2–3× ATR / SL swing low/high

---

## Signal Quality Hierarchy

- Scalping: Fast micro-moves, 3 aligned filters
- Intraday: Multi-hour precision, 4 aligned filters
- Trend: Long-term trend, 5 aligned filters

Signal Strength Color Code:

- ✅ 3/3 filters → High probability
- ⚡ 2/3 filters → Medium probability
- ⚠ 1/3 filters → Low probability / ignore
