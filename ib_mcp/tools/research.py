"""Strategy R&D tools: technical indicators, contract details."""

import json
import re

import pandas as pd
from ib_insync import Stock
from mcp.server.fastmcp import Context

from ib_mcp import indicators as ind
from ib_mcp.connection import IBContext
from ib_mcp.server import mcp


def _get_ib(ctx: Context):
    ib_ctx: IBContext = ctx.request_context.lifespan_context
    return ib_ctx.ib


def _make_contract(symbol: str, sec_type: str, exchange: str, currency: str):
    from ib_insync import Contract

    if sec_type.upper() == "STK":
        return Stock(symbol, exchange, currency)
    return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)


def _parse_indicator(spec: str) -> tuple[str, int | None]:
    """Parse indicator spec like 'SMA_20' into ('SMA', 20)."""
    match = re.match(r"^([A-Z]+)(?:_(\d+))?$", spec.upper())
    if not match:
        return spec.upper(), None
    name = match.group(1)
    period = int(match.group(2)) if match.group(2) else None
    return name, period


@mcp.tool()
async def calculate_indicators(
    symbol: str,
    indicators: list[str],
    duration: str = "6 M",
    bar_size: str = "1 day",
    tail: int = 30,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Fetch historical data and compute technical indicators.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        indicators: List of indicators to compute. Format: "NAME" or "NAME_PERIOD".
            Supported: SMA_N, EMA_N, RSI_N, BBANDS_N, MACD, ATR_N.
            Examples: ["SMA_20", "SMA_50", "RSI_14", "BBANDS_20", "MACD", "ATR_14"]
        duration: How far back to fetch data (default "6 M")
        bar_size: Bar size (default "1 day")
        tail: Number of most recent rows to return (default 30)
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"

    contract = qualified[0]
    bars = await ib.reqHistoricalDataAsync(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,
    )

    if not bars:
        return f"No historical data returned for {symbol}"

    df = pd.DataFrame(
        [
            {
                "date": str(b.date),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
    )

    close = df["close"]
    errors = []

    for spec in indicators:
        name, period = _parse_indicator(spec)

        if name == "SMA":
            p = period or 20
            df[f"SMA_{p}"] = ind.compute_sma(close, p)
        elif name == "EMA":
            p = period or 12
            df[f"EMA_{p}"] = ind.compute_ema(close, p)
        elif name == "RSI":
            p = period or 14
            df[f"RSI_{p}"] = ind.compute_rsi(close, p)
        elif name == "BBANDS":
            p = period or 20
            sma, upper, lower = ind.compute_bbands(close, p)
            df[f"BB_mid_{p}"] = sma
            df[f"BB_upper_{p}"] = upper
            df[f"BB_lower_{p}"] = lower
        elif name == "MACD":
            macd_line, signal_line, histogram = ind.compute_macd(close)
            df["MACD"] = macd_line
            df["MACD_signal"] = signal_line
            df["MACD_hist"] = histogram
        elif name == "ATR":
            p = period or 14
            df[f"ATR_{p}"] = ind.compute_atr(df["high"], df["low"], close, p)
        else:
            errors.append(f"Unknown indicator: {spec}")

    result = df.tail(tail).round(4).to_dict(orient="records")
    output = {"symbol": symbol, "bar_size": bar_size, "data": result}
    if errors:
        output["errors"] = errors
    return json.dumps(output, indent=2)


@mcp.tool()
async def get_contract_details(
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get full contract details: name, industry, tick size, trading hours, etc.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"

    contract = qualified[0]
    details_list = await ib.reqContractDetailsAsync(contract)

    if not details_list:
        return f"No contract details found for {symbol}"

    d = details_list[0]
    result = {
        "symbol": d.contract.symbol,
        "secType": d.contract.secType,
        "exchange": d.contract.exchange,
        "currency": d.contract.currency,
        "conId": d.contract.conId,
        "longName": d.longName,
        "industry": d.industry,
        "category": d.category,
        "subcategory": d.subcategory,
        "minTick": d.minTick,
        "priceMagnifier": d.priceMagnifier,
        "tradingHours": d.tradingHours,
        "liquidHours": d.liquidHours,
        "timeZoneId": d.timeZoneId,
        "marketName": d.marketName,
    }

    return json.dumps(result, indent=2)
