"""MCP tools for quantitative analysis — pure math, no ML models.

Provides statistical tools for strategy enhancement:
- Hurst exponent for persistence/mean-reversion classification
- Return autocorrelation for regime detection
"""

import json
import math

import numpy as np
from mcp.server.fastmcp import Context

from ib_mcp.server import mcp


def _rescaled_range(ts: np.ndarray) -> float:
    """Compute Hurst exponent using the Rescaled Range (R/S) method."""
    n = len(ts)
    if n < 20:
        return 0.5  # insufficient data, assume random walk

    max_k = min(n // 2, 256)
    min_k = 8
    sizes = []
    rs_values = []

    k = min_k
    while k <= max_k:
        num_segments = n // k
        if num_segments < 1:
            break

        rs_seg = []
        for seg_idx in range(num_segments):
            segment = ts[seg_idx * k : (seg_idx + 1) * k]
            mean = np.mean(segment)
            deviations = segment - mean
            cumulative = np.cumsum(deviations)
            r = np.max(cumulative) - np.min(cumulative)
            s = np.std(segment, ddof=1)
            if s > 1e-10:
                rs_seg.append(r / s)

        if rs_seg:
            sizes.append(k)
            rs_values.append(np.mean(rs_seg))

        k = int(k * 1.5)
        if k == sizes[-1] if sizes else 0:
            k += 1

    if len(sizes) < 3:
        return 0.5

    log_sizes = np.log(sizes)
    log_rs = np.log(rs_values)

    # Linear regression: log(R/S) = H * log(n) + c
    coeffs = np.polyfit(log_sizes, log_rs, 1)
    hurst = float(coeffs[0])
    return max(0.0, min(1.0, hurst))


@mcp.tool()
async def compute_hurst_exponent(
    symbol: str,
    duration: str = "20 D",
    bar_size: str = "1 day",
    ctx: Context = None,
) -> str:
    """Compute the Hurst exponent for a stock to measure trend persistence.

    H > 0.55 = persistent (trending), H < 0.45 = anti-persistent (mean-reverting),
    0.45-0.55 = random walk. Used by rotation strategies to validate streak signals
    and distinguish genuine momentum from noise.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        duration: How far back to fetch price history (default "20 D")
        bar_size: Bar size (default "1 day")
    """
    from ib_mcp.connection import IBContext
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    bars = await ib.reqHistoricalDataAsync(
        qualified[0], endDateTime="", durationStr=duration,
        barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True,
    )

    if not bars or len(bars) < 20:
        return json.dumps({
            "error": f"Insufficient price history for {symbol} "
                     f"(got {len(bars) if bars else 0}, need 20+)",
        })

    prices = np.array([b.close for b in bars], dtype=np.float64)
    log_returns = np.diff(np.log(prices))

    hurst = _rescaled_range(log_returns)

    if hurst > 0.55:
        interpretation = "persistent"
    elif hurst < 0.45:
        interpretation = "anti_persistent"
    else:
        interpretation = "random"

    return json.dumps({
        "symbol": symbol,
        "hurst": round(hurst, 4),
        "interpretation": interpretation,
        "duration": duration,
        "bar_size": bar_size,
        "bar_count": len(bars),
    }, indent=2)


@mcp.tool()
async def compute_return_autocorrelation(
    symbol: str,
    duration: str = "5 D",
    bar_size: str = "1 day",
    lag: int = 1,
    ctx: Context = None,
) -> str:
    """Compute return autocorrelation to detect mean-reversion vs trending regime.

    Negative autocorrelation (< -0.1) indicates mean-reversion — fades work.
    Positive autocorrelation (> 0.1) indicates trending — fades fail.
    Used by whipsaw fade strategy to enable/disable fading.

    Args:
        symbol: Ticker symbol (e.g. "UVIX")
        duration: How far back to fetch (default "5 D")
        bar_size: Bar size (default "1 day")
        lag: Autocorrelation lag (default 1)
    """
    from ib_mcp.connection import IBContext
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    bars = await ib.reqHistoricalDataAsync(
        qualified[0], endDateTime="", durationStr=duration,
        barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True,
    )

    if not bars or len(bars) < lag + 5:
        return json.dumps({
            "error": f"Insufficient price history for {symbol} "
                     f"(got {len(bars) if bars else 0}, need {lag + 5}+)",
        })

    prices = np.array([b.close for b in bars], dtype=np.float64)
    log_returns = np.diff(np.log(prices))

    if len(log_returns) < lag + 2:
        return json.dumps({"error": "Not enough returns for autocorrelation"})

    # Compute autocorrelation at given lag
    n = len(log_returns)
    mean = np.mean(log_returns)
    var = np.var(log_returns)

    if var < 1e-12:
        autocorr = 0.0
    else:
        cov = np.mean((log_returns[lag:] - mean) * (log_returns[:-lag] - mean))
        autocorr = float(cov / var)

    if autocorr < -0.1:
        interpretation = "mean_reverting"
    elif autocorr > 0.1:
        interpretation = "trending"
    else:
        interpretation = "neutral"

    return json.dumps({
        "symbol": symbol,
        "autocorrelation": round(autocorr, 4),
        "lag": lag,
        "interpretation": interpretation,
        "duration": duration,
        "bar_size": bar_size,
        "bar_count": len(bars),
    }, indent=2)
