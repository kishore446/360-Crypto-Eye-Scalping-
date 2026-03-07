"""
Chart Generator
===============
Generates annotated candlestick charts using mplfinance for signal broadcast.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_signal_chart(
    candles_5m: list,
    signal,
    candles_15m: list | None = None,
) -> Optional[bytes]:
    """
    Generate annotated candlestick chart as PNG bytes.
    Returns None if mplfinance is not available or on any error.
    """
    try:
        import matplotlib
        import mplfinance as mpf
        import pandas as pd
        matplotlib.use("Agg")
    except ImportError:
        logger.warning("mplfinance or matplotlib not installed — chart generation disabled.")
        return None

    try:
        if not candles_5m or len(candles_5m) < 5:
            return None

        data = {
            "Open": [c.open for c in candles_5m],
            "High": [c.high for c in candles_5m],
            "Low": [c.low for c in candles_5m],
            "Close": [c.close for c in candles_5m],
            "Volume": [c.volume for c in candles_5m],
        }
        idx = pd.date_range(
            end=pd.Timestamp.now(),
            periods=len(candles_5m),
            freq="5min",
        )
        df = pd.DataFrame(data, index=idx)

        hlines = []
        hline_colors = []
        hline_styles = []

        hlines.extend([signal.entry_low, signal.entry_high])
        hline_colors.extend(["blue", "blue"])
        hline_styles.extend(["--", "--"])

        hlines.extend([signal.tp1, signal.tp2, signal.tp3])
        hline_colors.extend(["green", "green", "green"])
        hline_styles.extend(["-", "-", "-"])

        hlines.append(signal.stop_loss)
        hline_colors.append("red")
        hline_styles.append("-")

        buf = io.BytesIO()
        mpf.plot(
            df,
            type="candle",
            volume=True,
            hlines=dict(
                hlines=hlines,
                colors=hline_colors,
                linestyle=hline_styles,
                linewidths=[1.0] * len(hlines),
            ),
            title=f"{signal.symbol}/USDT {signal.side.value} | 360 Eye Signal",
            style="charles",
            savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
        )
        buf.seek(0)
        return buf.read()

    except Exception as exc:
        logger.warning("Chart generation failed: %s", exc)
        return None
