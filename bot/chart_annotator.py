"""
Chart Annotator
===============
Generates annotated 5-minute candlestick chart images using *mplfinance* for
each trading signal.  The chart shows:

  • Last 50 5m candles with a volume bar subplot.
  • Entry zone as a shaded green (LONG) or red (SHORT) band.
  • TP1/TP2/TP3 as dashed green horizontal lines.
  • Stop-loss as a solid red horizontal line.

The image is saved to a temporary PNG file and the path is returned so it
can be attached as a photo to the Telegram signal message.

Requires ``mplfinance`` and ``matplotlib`` (both listed in *requirements.txt*).
If either library is missing the function returns the output path unchanged
without raising, so the rest of the signal flow degrades gracefully.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def generate_signal_chart(
    symbol: str,
    side: str,
    candles_5m: list[list[float]],
    entry_low: float,
    entry_high: float,
    tp1: float,
    tp2: float,
    tp3: float,
    stop_loss: float,
    output_path: str = "/tmp/360eye_chart.png",
) -> str:
    """
    Generate an annotated 5m candlestick chart and save it to *output_path*.

    Parameters
    ----------
    symbol:
        Base asset ticker, e.g. ``"BTC"``.
    side:
        Trade direction — ``"LONG"`` or ``"SHORT"``.
    candles_5m:
        Raw OHLCV rows as ``[timestamp_ms, open, high, low, close, volume]``.
        Only the last 50 rows are plotted.
    entry_low:
        Lower boundary of the entry zone.
    entry_high:
        Upper boundary of the entry zone.
    tp1:
        First take-profit level.
    tp2:
        Second take-profit level.
    tp3:
        Third take-profit level (final target).
    stop_loss:
        Stop-loss invalidation level.
    output_path:
        Filesystem path where the PNG will be written.
        Defaults to ``"/tmp/360eye_chart.png"``.

    Returns
    -------
    str
        The path of the saved PNG file (*output_path*).  On failure the path
        is returned unchanged even though the file may not have been created,
        so callers should check for file existence before attaching it.
    """
    try:
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.patches as mpatches  # noqa: PLC0415
        import mplfinance as mpf  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "mplfinance / matplotlib not installed — chart annotation disabled."
        )
        return output_path

    try:
        rows = candles_5m[-50:] if len(candles_5m) > 50 else candles_5m
        if len(rows) < 5:
            logger.warning("Insufficient candles for chart (%d rows).", len(rows))
            return output_path

        # Build a DataFrame that mplfinance understands.
        # Columns must be Open, High, Low, Close, Volume with a DatetimeIndex.
        df = pd.DataFrame(
            {
                "Open": [r[1] for r in rows],
                "High": [r[2] for r in rows],
                "Low": [r[3] for r in rows],
                "Close": [r[4] for r in rows],
                "Volume": [r[5] for r in rows],
            },
            index=pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
        )

        # Horizontal lines for TP/SL
        hlines_vals = [tp1, tp2, tp3, stop_loss]
        hlines_colors = ["green", "green", "green", "red"]
        hlines_styles = ["--", "--", "--", "-"]

        # Entry zone: low and high boundaries
        hlines_vals.extend([entry_low, entry_high])
        entry_color = "green" if side.upper() == "LONG" else "red"
        hlines_colors.extend([entry_color, entry_color])
        hlines_styles.extend([":", ":"])

        # Build mplfinance add_plot for entry-zone shading
        shade_color = "rgba(0,200,0,0.15)" if side.upper() == "LONG" else "rgba(200,0,0,0.15)"

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        mpf.plot(
            df,
            type="candle",
            volume=True,
            hlines=dict(
                hlines=hlines_vals,
                colors=hlines_colors,
                linestyle=hlines_styles,
                linewidths=[1.2] * len(hlines_vals),
            ),
            title=f"{symbol}/USDT {side.upper()} | 360 Eye Signal",
            style="charles",
            savefig=dict(fname=output_path, dpi=100, bbox_inches="tight"),
            figsize=(12, 7),
        )
        logger.info("Chart saved to %s", output_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chart generation failed: %s", exc)

    return output_path
