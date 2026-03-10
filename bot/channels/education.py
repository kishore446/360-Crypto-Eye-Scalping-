"""
CH8 — Education Auto-Posts
Rotating educational content: trading lessons, pattern of the day,
and a glossary accessible via /learn command.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from config import (
        EDUCATION_LESSON_HOUR_UTC,
        EDUCATION_PATTERN_HOUR_UTC,
        TELEGRAM_CHANNEL_ID_EDUCATION,
    )
except Exception:  # pragma: no cover
    EDUCATION_LESSON_HOUR_UTC = 10
    EDUCATION_PATTERN_HOUR_UTC = 16
    TELEGRAM_CHANNEL_ID_EDUCATION = 0

# ── Lesson Library ────────────────────────────────────────────────────────────

LESSONS: list[dict[str, str]] = [
    {
        "title": "What is a Fair Value Gap (FVG)?",
        "content": (
            "A Fair Value Gap occurs when price moves so quickly that a candle's "
            "body leaves a gap between the high of one candle and the low of two candles "
            "later. This imbalance acts as a magnet — price often retraces to fill the gap "
            "before continuing in the original direction."
        ),
        "category": "ICT Concepts",
        "pro_tip": "Look for FVGs on the 15m timeframe within the context of a higher-timeframe trend.",
        "related": "Order Blocks, Market Structure",
    },
    {
        "title": "Risk Management: The 1% Rule",
        "content": (
            "Never risk more than 1% of your total account balance on a single trade. "
            "This means if your account is $10,000, your maximum loss per trade is $100. "
            "This rule ensures that even a streak of 10 consecutive losses only costs you 10% "
            "of your capital — survivable and recoverable."
        ),
        "category": "Risk Management",
        "pro_tip": "Use a position size calculator: Risk Amount ÷ (Entry − Stop Loss) = Position Size.",
        "related": "Position Sizing, Stop Loss Placement",
    },
    {
        "title": "Understanding Market Structure",
        "content": (
            "Market structure consists of Higher Highs (HH), Higher Lows (HL) in an uptrend, "
            "and Lower Lows (LL), Lower Highs (LH) in a downtrend. "
            "A Break of Structure (BOS) occurs when price closes beyond the previous swing high/low, "
            "confirming the trend continuation or reversal."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Always trade in the direction of the higher-timeframe market structure.",
        "related": "BOS, CHoCH, Swing Points",
    },
    {
        "title": "What is an Order Block (OB)?",
        "content": (
            "An Order Block is the last down-candle (for a bullish OB) or last up-candle "
            "(for a bearish OB) before a strong impulsive move. It represents institutional "
            "order flow — the area where large players placed their orders. Price tends to "
            "return to these zones before continuing in the direction of the imbalance."
        ),
        "category": "ICT Concepts",
        "pro_tip": "The strongest OBs are those that caused a Break of Structure.",
        "related": "FVG, Breaker Blocks, Mitigation Blocks",
    },
    {
        "title": "Liquidity & Stop Hunts Explained",
        "content": (
            "Liquidity refers to clusters of stop-loss orders sitting above resistance (sell stops) "
            "or below support (buy stops). Smart money — institutions and market makers — often "
            "engineer moves into these clusters to trigger retail stops and fill their own large "
            "orders at better prices. This is called a 'stop hunt' or 'liquidity sweep'."
        ),
        "category": "ICT Concepts",
        "pro_tip": "Wait for a liquidity sweep followed by a Market Structure Shift before entering.",
        "related": "Equal Highs/Lows, Stop Hunt, MSS",
    },
    {
        "title": "The Psychology of Losing Trades",
        "content": (
            "Every professional trader has losing trades — it's an unavoidable part of the process. "
            "The key is to accept losses as the cost of doing business. Never move your stop loss "
            "to avoid a loss, never revenge trade after a loss, and never risk more to 'make it back'. "
            "Your edge plays out over hundreds of trades, not individual ones."
        ),
        "category": "Psychology",
        "pro_tip": "Keep a trading journal. Review your emotions during losing streaks to find patterns.",
        "related": "Risk Management, Discipline, Trade Review",
    },
    {
        "title": "Understanding Funding Rates",
        "content": (
            "Funding rates are periodic payments between long and short traders on perpetual futures. "
            "A positive funding rate means longs pay shorts — indicating over-leveraged bullish sentiment. "
            "Extremely positive funding (>0.05%) can precede a correction as longs get squeezed. "
            "Negative funding means shorts pay longs, often a contrarian bullish signal."
        ),
        "category": "Funding/OI",
        "pro_tip": "Avoid opening long positions when funding is extremely positive (>0.1%).",
        "related": "Open Interest, Perpetual Futures, Leverage",
    },
    {
        "title": "What is Open Interest (OI)?",
        "content": (
            "Open Interest is the total number of outstanding futures contracts that have not been "
            "settled. Rising OI with rising price = trend continuation (new money entering longs). "
            "Rising OI with falling price = bearish (new money entering shorts). "
            "Falling OI with any price direction = trend weakening as positions close."
        ),
        "category": "Funding/OI",
        "pro_tip": "Watch for OI spikes on liquidation events — they often mark local tops/bottoms.",
        "related": "Funding Rate, Long/Short Ratio, Liquidations",
    },
    {
        "title": "Market Sessions: When to Trade",
        "content": (
            "The three major trading sessions are:\n"
            "• Asian (00:00–08:00 UTC): Low volume, range-bound, liquidity raids\n"
            "• London (08:00–16:00 UTC): High volume, trend initiation\n"
            "• New York (13:00–21:00 UTC): Highest volume, trend continuation or reversal\n"
            "The London-New York overlap (13:00–16:00 UTC) is historically the most volatile."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Most fake breakouts occur during the Asian session. Wait for London confirmation.",
        "related": "Killzones, Session Gaps, Manipulation",
    },
    {
        "title": "How to Place a Stop Loss",
        "content": (
            "A stop loss should be placed at a level that, if hit, proves your trade thesis wrong. "
            "Common placements:\n"
            "• Below the swing low (for longs) / above swing high (for shorts)\n"
            "• Below the Order Block that triggered your entry\n"
            "• Below the Fair Value Gap you entered into\n"
            "Never place stops at round numbers — that's where everyone else puts theirs."
        ),
        "category": "Risk Management",
        "pro_tip": "Give your stop a few ticks of buffer beyond the invalidation level to avoid premature hits.",
        "related": "Position Sizing, Invalidation, R:R Ratio",
    },
    {
        "title": "Understanding the Risk-Reward Ratio (R:R)",
        "content": (
            "Risk-Reward Ratio measures how much you stand to gain vs. lose on a trade. "
            "A 1:2 R:R means you risk $100 to make $200. "
            "Even with a 40% win rate, a consistent 1:2 R:R is profitable: "
            "4 wins × $200 = $800, 6 losses × $100 = $600 → net +$200."
        ),
        "category": "Risk Management",
        "pro_tip": "Only take trades with a minimum 1:1.5 R:R. Aim for 1:2 or better.",
        "related": "Win Rate, Position Sizing, Take Profit",
    },
    {
        "title": "What is a Market Structure Shift (MSS)?",
        "content": (
            "A Market Structure Shift (MSS) is a significant change in the direction of price "
            "after a liquidity sweep. In a downtrend, an MSS occurs when price sweeps a swing low, "
            "then aggressively closes above the last swing high — signalling bullish reversal. "
            "An MSS is stronger evidence of reversal than a simple Break of Structure."
        ),
        "category": "ICT Concepts",
        "pro_tip": "MSS on the 5m/15m after a liquidity sweep is a prime entry signal for ICT traders.",
        "related": "BOS, FVG, Liquidity Sweep",
    },
    {
        "title": "DCA Strategy: Dollar-Cost Averaging",
        "content": (
            "Dollar-Cost Averaging (DCA) means buying a fixed dollar amount of an asset at regular "
            "intervals, regardless of price. This removes emotional timing decisions and reduces "
            "the impact of volatility. Over time, you accumulate more units when prices are low "
            "and fewer when prices are high, lowering your average entry cost."
        ),
        "category": "Technical Analysis",
        "pro_tip": "DCA into strong-fundamental assets only. DCA into scams just multiplies your losses.",
        "related": "Position Building, Accumulation, Long-Term Investing",
    },
    {
        "title": "Bull Flag Pattern",
        "content": (
            "A Bull Flag forms after a sharp upward move (the pole), followed by a consolidation "
            "period with parallel downward-sloping or horizontal channels (the flag). "
            "When price breaks above the upper trendline of the flag with increased volume, "
            "it signals continuation of the uptrend. Target: pole height added to breakout point."
        ),
        "category": "Technical Analysis",
        "pro_tip": "The flag should retrace 38-50% of the pole. Deeper retracements invalidate the pattern.",
        "related": "Bear Flag, Pennant, Ascending Triangle",
    },
    {
        "title": "Head & Shoulders Pattern",
        "content": (
            "The Head & Shoulders is a reversal pattern with three peaks: a higher middle peak "
            "(head) flanked by two lower peaks (shoulders). The 'neckline' connects the two troughs. "
            "A close below the neckline confirms a bearish reversal. "
            "Inverse H&S is the bullish equivalent — a bottoming pattern."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Volume should decline from left shoulder to head to right shoulder, then spike on breakout.",
        "related": "Double Top/Bottom, Bearish Reversal, Neckline",
    },
    {
        "title": "What is the Fear & Greed Index?",
        "content": (
            "The Crypto Fear & Greed Index measures overall market sentiment on a scale of 0-100:\n"
            "• 0-25: Extreme Fear (potential buy zone)\n"
            "• 25-45: Fear\n"
            "• 45-55: Neutral\n"
            "• 55-75: Greed\n"
            "• 75-100: Extreme Greed (potential sell zone)\n"
            "Warren Buffett's rule: 'Be fearful when others are greedy, greedy when others are fearful.'"
        ),
        "category": "Technical Analysis",
        "pro_tip": "Use it as a contrarian indicator, not a timing tool. Extremes can persist for weeks.",
        "related": "Market Sentiment, Long/Short Ratio, Funding Rate",
    },
    {
        "title": "Candlestick Patterns: Hammer & Shooting Star",
        "content": (
            "A Hammer has a small body at the top with a long lower wick (2× body length minimum). "
            "It signals a bullish reversal — sellers pushed price down but buyers rejected it. "
            "A Shooting Star is the inverse: small body at the bottom, long upper wick — "
            "buyers tried to push higher but were overwhelmed by sellers. Bullish/bearish context matters."
        ),
        "category": "Technical Analysis",
        "pro_tip": "A Hammer at a key support level or Order Block is much more reliable than in isolation.",
        "related": "Doji, Engulfing, Pin Bar",
    },
    {
        "title": "Understanding Leverage in Crypto",
        "content": (
            "Leverage amplifies both gains and losses. 10× leverage means a 1% move in your favour "
            "gives +10%, but a 1% adverse move gives -10%. At 10× leverage, a 10% adverse move "
            "wipes your entire margin (liquidation). "
            "Most professionals use 2-5× maximum. Higher leverage = shorter viable stop distances."
        ),
        "category": "Risk Management",
        "pro_tip": "Calculate your effective leverage: (Position Size) ÷ (Account Balance). Keep it under 5×.",
        "related": "Liquidation, Margin, Position Sizing",
    },
    {
        "title": "Support & Resistance Zones",
        "content": (
            "Support is a price level where buying pressure historically exceeds selling, "
            "causing price to bounce upward. Resistance is the opposite. "
            "Key insight: once a support level is broken and price closes below it, "
            "that level becomes resistance (polarity flip) — and vice versa."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Use zones (price ranges), not exact levels — price rarely reacts at a single number.",
        "related": "Supply/Demand, Order Blocks, FVG",
    },
    {
        "title": "What is BTC Dominance (BTC.D)?",
        "content": (
            "Bitcoin Dominance (BTC.D) measures BTC's market cap as a percentage of total crypto market cap. "
            "Rising BTC.D = capital flowing into Bitcoin, often at the expense of altcoins. "
            "Falling BTC.D = capital rotating into altcoins (altseason). "
            "Watch for BTC.D rejection at key levels as a leading indicator for altcoin runs."
        ),
        "category": "Technical Analysis",
        "pro_tip": "When BTC.D drops below key support while BTC price holds → high-probability altseason signal.",
        "related": "Altseason Index, Market Cap, Sector Rotation",
    },
    {
        "title": "RSI: Relative Strength Index",
        "content": (
            "RSI measures the speed and magnitude of price changes on a 0-100 scale. "
            "Traditional levels: above 70 = overbought, below 30 = oversold. "
            "In crypto, use 80/20 for strong trends. "
            "RSI Divergence: price makes new high but RSI makes lower high = bearish divergence "
            "(momentum weakening) → potential reversal signal."
        ),
        "category": "Technical Analysis",
        "pro_tip": "RSI divergence is most reliable on 4H/1D timeframes at key structural levels.",
        "related": "MACD, Stochastic, Momentum",
    },
    {
        "title": "Wyckoff Method: Accumulation & Distribution",
        "content": (
            "The Wyckoff Method describes market cycles in phases:\n"
            "• Phase A: Selling/buying climax (SC/BC)\n"
            "• Phase B: Building the cause (range-bound)\n"
            "• Phase C: Spring/Upthrust (final liquidity grab)\n"
            "• Phase D: Sign of Strength/Weakness\n"
            "• Phase E: Markup/Markdown\n"
            "Recognising these phases helps time entries in accumulation/distribution zones."
        ),
        "category": "Technical Analysis",
        "pro_tip": "The Spring in Phase C (a false breakdown below range support) is the highest-probability entry.",
        "related": "Volume Analysis, Market Structure, Institutional Order Flow",
    },
    {
        "title": "What are Liquidation Levels?",
        "content": (
            "Liquidation occurs when a trader's margin is insufficient to cover losses, "
            "forcing their position to close automatically. "
            "Liquidation heatmaps show price levels with concentrated leveraged positions. "
            "When price reaches these levels, cascading liquidations can amplify moves — "
            "creating both opportunities and risks."
        ),
        "category": "Funding/OI",
        "pro_tip": "Large liquidation clusters above/below current price act as magnets for price action.",
        "related": "Open Interest, Leverage, Stop Hunts",
    },
    {
        "title": "MACD: Moving Average Convergence Divergence",
        "content": (
            "MACD consists of two EMAs (typically 12 and 26 period) and a signal line (9 EMA of MACD). "
            "Bullish signal: MACD crosses above signal line. Bearish: crosses below. "
            "The histogram shows the distance between MACD and signal — fading bars = momentum loss. "
            "MACD divergence (like RSI divergence) is a powerful reversal signal."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Use MACD for momentum confirmation, not as a standalone entry trigger.",
        "related": "RSI, EMA, Momentum",
    },
    {
        "title": "Volume Profile & POC",
        "content": (
            "Volume Profile shows the amount of trading activity at each price level over a period. "
            "The Point of Control (POC) is the price level with the highest traded volume — "
            "a strong magnet for price. "
            "Value Area (VA) covers 70% of volume — price tends to return to this zone when trading outside it."
        ),
        "category": "Technical Analysis",
        "pro_tip": "When price gaps away from POC, it often returns — use this for target selection.",
        "related": "Volume, Support/Resistance, Market Profile",
    },
    {
        "title": "Stablecoins as Market Indicators",
        "content": (
            "Stablecoin supply (USDT, USDC) on exchanges is 'dry powder' — capital ready to enter crypto. "
            "Rising stablecoin balances on exchanges = potential buying pressure. "
            "Falling stablecoin balances (converted to crypto) = capital deployed = bullish signal. "
            "Large USDT mints often precede bullish price moves as new capital enters the ecosystem."
        ),
        "category": "Technical Analysis",
        "pro_tip": "Monitor Tether treasury wallets on-chain for large USDT mints as early bullish signals.",
        "related": "Exchange Flows, On-Chain Analysis, Market Sentiment",
    },
    {
        "title": "The Importance of Trade Journaling",
        "content": (
            "A trading journal records every trade: entry/exit price, size, reason, emotional state, "
            "and outcome. Reviewing your journal reveals patterns — your best setups, your biggest "
            "mistakes, and the emotional triggers that cause you to deviate from your plan. "
            "Professional traders review their journals weekly. It's the fastest path to improvement."
        ),
        "category": "Psychology",
        "pro_tip": "Use screenshots of your charts with annotations. A picture is worth 1000 words.",
        "related": "Discipline, Process, Performance Review",
    },
    {
        "title": "Understanding Market Manipulations",
        "content": (
            "Common manipulation tactics in crypto:\n"
            "• Stop Hunt: Engineer a move to trigger retail stops before reversing\n"
            "• Wash Trading: Fake volume to appear active\n"
            "• Pump & Dump: Inflate price, sell to late buyers\n"
            "• Spoofing: Place large orders to fake support/resistance, cancel before fill\n"
            "Understanding these tactics helps you trade with the manipulators, not against them."
        ),
        "category": "Psychology",
        "pro_tip": "If a move feels too obvious — sweeping a clear level then reversing — it probably was a stop hunt.",
        "related": "Liquidity, Stop Hunts, Smart Money",
    },
    {
        "title": "Ascending & Descending Triangles",
        "content": (
            "An Ascending Triangle has a flat resistance top with rising lows — accumulation pattern. "
            "Each test of resistance with higher lows signals increasing buying pressure. "
            "Breakout above resistance (usually with volume) targets the triangle height added to breakout. "
            "Descending Triangle is the bearish mirror — flat support, lower highs, breakdown expected."
        ),
        "category": "Technical Analysis",
        "pro_tip": "False breakouts above/below triangles are common — wait for a candle close outside.",
        "related": "Bull Flag, Wedge, Consolidation",
    },
    {
        "title": "Order Types Every Trader Must Know",
        "content": (
            "• Market Order: Immediate execution at current price (uses best available)\n"
            "• Limit Order: Set your price, wait for it to fill (maker, no slippage)\n"
            "• Stop Market: Triggers a market order at your stop price\n"
            "• Stop Limit: Triggers a limit order at your stop price (risk: may not fill)\n"
            "• Trailing Stop: Moves with price in your favour, triggers on reversal\n"
            "Use limit orders for entries, stop market for exits (guaranteed fill)."
        ),
        "category": "Order Types",
        "pro_tip": "In fast-moving markets, stop-limit orders can fail to fill. Use stop-market for critical exits.",
        "related": "Slippage, Execution, Order Book",
    },
    {
        "title": "The Power of Confluence",
        "content": (
            "Confluence means multiple independent signals aligning at the same price level. "
            "A single indicator giving a signal is weak. But when an FVG, an Order Block, "
            "a key support level, AND the 200 EMA all align at the same zone, "
            "the probability of a reaction increases dramatically. "
            "This bot requires 5-7 confluence gates before firing a signal."
        ),
        "category": "ICT Concepts",
        "pro_tip": "Build a checklist: only trade when 4+ factors align. Quality over quantity.",
        "related": "Gate System, Multi-Timeframe Analysis, Signal Quality",
    },
]

# ── Glossary ──────────────────────────────────────────────────────────────────

GLOSSARY: dict[str, str] = {
    "FVG": "Fair Value Gap — An imbalance in price where a candle moves so fast it leaves a gap "
           "between three candles. Price tends to return to fill this gap.",
    "OB": "Order Block — The last down-candle before a bullish impulse (bullish OB) or last "
          "up-candle before a bearish impulse (bearish OB). Represents institutional order flow.",
    "MSS": "Market Structure Shift — When price sweeps liquidity (a swing low/high), then "
           "aggressively breaks the opposite swing, signalling a change in trend direction.",
    "BOS": "Break of Structure — Price closes beyond the previous swing high (bullish BOS) or "
           "swing low (bearish BOS), confirming trend continuation.",
    "CHoCH": "Change of Character — A weaker form of MSS. The first sign that the current trend "
             "may be losing momentum, often precedes a full MSS.",
    "PDH": "Previous Day High — The highest price reached in the prior trading day. Acts as a "
           "key resistance/target for liquidity raids.",
    "PDL": "Previous Day Low — The lowest price of the prior trading day. Acts as a key support/"
           "liquidity target.",
    "EQH": "Equal Highs — Two or more swing highs at the same price level. This clusters buy-side "
           "liquidity (stop losses) and is a prime target for smart money.",
    "EQL": "Equal Lows — Two or more swing lows at the same price level. Clusters sell-side "
           "liquidity; often swept before a bullish move.",
    "POI": "Point of Interest — Any high-probability price zone: OB, FVG, EQH/EQL, or key "
           "structural level that price is likely to react at.",
    "HTF": "Higher Time Frame — Any timeframe larger than your entry TF. Used to determine "
           "trend direction and major POIs. E.g., 4H/1D relative to 5m/15m entries.",
    "LTF": "Lower Time Frame — Timeframes smaller than your analysis TF. Used for precise entry "
           "timing. E.g., 1m/5m for entries identified on 4H.",
    "ATR": "Average True Range — A measure of market volatility. Calculated as average of true "
           "ranges over N periods. Used for position sizing and stop placement.",
    "RSI": "Relative Strength Index — Momentum oscillator (0-100). Above 70 = overbought, "
           "below 30 = oversold. Divergence from price action signals potential reversal.",
    "VWAP": "Volume Weighted Average Price — Average price weighted by volume. Institutions use "
            "it as a benchmark. Price above VWAP = bullish bias; below = bearish.",
    "OI": "Open Interest — Total outstanding futures contracts not yet settled. Rising OI with "
          "rising price = bullish (new longs). Rising OI with falling price = bearish (new shorts).",
    "FR": "Funding Rate — Periodic payment between long and short traders on perpetual futures. "
          "Positive = longs pay shorts. Extreme positive rates precede long squeezes.",
    "PnL": "Profit and Loss — The financial result of a trade. Unrealised PnL = paper profit/loss "
           "on open position. Realised PnL = locked-in result after closing.",
    "RR": "Risk-Reward Ratio — Ratio of potential profit to potential loss. 1:2 RR means "
          "risking $1 to make $2. Use a minimum of 1:1.5 for positive expectancy.",
    "DCA": "Dollar-Cost Averaging — Buying fixed dollar amounts at regular intervals to reduce "
           "timing risk and lower average entry cost over time.",
    "BTC.D": "Bitcoin Dominance — BTC's market cap as % of total crypto. Rising BTC.D = Bitcoin "
             "season. Falling BTC.D = altseason (capital rotating to altcoins).",
}

# ── Pattern detection ─────────────────────────────────────────────────────────


@dataclass
class PatternResult:
    """Result of a chart pattern detection."""

    name: str
    description: str
    timeframe: str = "4H"


def detect_pattern_btc_4h(candles: list[dict]) -> PatternResult:
    """
    Detect the most notable pattern from recent BTC 4H candles.

    *candles* is a list of OHLCV dicts with keys: open, high, low, close, volume.
    Returns the best detected pattern or a default 'No Clear Pattern'.
    """
    if len(candles) < 10:
        return PatternResult(
            name="No Clear Pattern",
            description="Insufficient candle data to detect a reliable pattern.",
        )

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    n = len(candles)

    # ── Bull Flag ────────────────────────────────────────────────────
    recent_high = max(highs[-10:])
    recent_low = min(lows[-10:])
    range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0
    pole_close = closes[-10]
    pole_open = candles[-10]["open"]
    if (
        pole_close > pole_open * 1.03
        and closes[-1] > closes[-5]
        and range_pct < 8
    ):
        return PatternResult(
            name="Bull Flag",
            description=(
                "Price made a sharp impulsive move (the pole) and is now consolidating "
                "in a tight range. A breakout above the flag's upper boundary targets the "
                "pole height added to the breakout point. Watch for volume confirmation."
            ),
        )

    # ── Bear Flag ────────────────────────────────────────────────────
    if (
        pole_close < pole_open * 0.97
        and closes[-1] < closes[-5]
        and range_pct < 8
    ):
        return PatternResult(
            name="Bear Flag",
            description=(
                "After a sharp downward impulse (the pole), price is consolidating in a "
                "tight upward-drifting channel. A breakdown below the flag targets the "
                "pole height subtracted from the breakdown point."
            ),
        )

    # ── Double Top ───────────────────────────────────────────────────
    if n >= 15:
        peak1 = max(highs[-15:-8])
        peak2 = max(highs[-8:])
        if abs(peak1 - peak2) / peak1 < 0.015 and closes[-1] < peak1 * 0.97:
            return PatternResult(
                name="Double Top",
                description=(
                    f"Two peaks formed near ${peak1:,.0f}, creating a classic reversal pattern. "
                    "The neckline is at the valley between the two peaks. A close below the "
                    "neckline confirms the pattern with a target equal to the peak-to-neckline distance."
                ),
            )

    # ── Double Bottom ────────────────────────────────────────────────
    if n >= 15:
        trough1 = min(lows[-15:-8])
        trough2 = min(lows[-8:])
        if abs(trough1 - trough2) / trough1 < 0.015 and closes[-1] > trough1 * 1.03:
            return PatternResult(
                name="Double Bottom",
                description=(
                    f"Two troughs formed near ${trough1:,.0f}, signalling a potential bullish reversal. "
                    "Confirmation comes on a close above the neckline (the peak between the two troughs). "
                    "Target is the trough-to-neckline distance added to the breakout."
                ),
            )

    # ── Ascending Triangle ───────────────────────────────────────────
    recent_highs = highs[-8:]
    recent_lows = lows[-8:]
    flat_top = max(recent_highs) - min(recent_highs) < max(recent_highs) * 0.01
    rising_lows = recent_lows[-1] > recent_lows[0]
    if flat_top and rising_lows:
        return PatternResult(
            name="Ascending Triangle",
            description=(
                "Flat resistance with rising lows shows accumulation — buyers are increasingly "
                "willing to buy at higher prices. Breakout above resistance (ideally with volume) "
                "targets the height of the triangle added to the breakout point."
            ),
        )

    # ── Descending Triangle ──────────────────────────────────────────
    flat_bottom = max(recent_lows) - min(recent_lows) < min(recent_lows) * 0.01
    falling_highs = recent_highs[-1] < recent_highs[0]
    if flat_bottom and falling_highs:
        return PatternResult(
            name="Descending Triangle",
            description=(
                "Flat support with falling highs indicates distribution — sellers are increasingly "
                "aggressive. A breakdown below support targets the triangle height below the "
                "breakdown point. Watch for a volume spike on the breakdown."
            ),
        )

    return PatternResult(
        name="No Clear Pattern",
        description=(
            "No textbook chart pattern detected in the current 4H candles. "
            "Price is in a consolidation or transitional phase. Monitor key support/resistance levels."
        ),
    )


# ── Message formatters ────────────────────────────────────────────────────────

# Module-level counter persisted across calls (rotates through lessons)
_lesson_index: int = 0


def get_next_lesson() -> dict[str, str]:
    """Return the next lesson in the rotation, cycling back to start."""
    global _lesson_index
    lesson = LESSONS[_lesson_index % len(LESSONS)]
    _lesson_index = (_lesson_index + 1) % len(LESSONS)
    return lesson


def format_lesson_message(lesson: dict[str, str], lesson_number: Optional[int] = None) -> str:
    """Return a Telegram-formatted lesson message."""
    num = lesson_number if lesson_number is not None else (_lesson_index % len(LESSONS))
    pro_tip = lesson.get("pro_tip", "")
    related = lesson.get("related", "")
    lines = [
        f"📚 TRADING LESSON #{num}",
        f"Category: {lesson['category']}",
        "──────────────────────",
        f"📖 {lesson['title']}",
        "",
        lesson["content"],
    ]
    if pro_tip:
        lines += ["", f"💡 Pro Tip: {pro_tip}"]
    if related:
        lines += [f"🔗 Related: {related}"]
    return "\n".join(lines)


def format_pattern_message(pattern: PatternResult) -> str:
    """Return a Telegram-formatted pattern of the day message."""
    return (
        f"📐 PATTERN OF THE DAY: {pattern.name} on BTC {pattern.timeframe}\n\n"
        f"Description: {pattern.description}"
    )


def lookup_glossary(term: str) -> Optional[str]:
    """Return the glossary definition for *term* (case-insensitive). None if not found."""
    normalised = term.strip().upper()
    return GLOSSARY.get(normalised)


def get_target_channel_id() -> int:
    """Return the CH8 channel ID (0 means disabled)."""
    return TELEGRAM_CHANNEL_ID_EDUCATION
