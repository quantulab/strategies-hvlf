"""Strategy R&D tools: technical indicators, contract details, pre-trade analysis."""

import json
import re
import xml.etree.ElementTree as ET

import pandas as pd
from ib_insync import LimitOrder, MarketOrder, Stock
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


@mcp.tool()
async def search_symbols(
    pattern: str,
    ctx: Context = None,
) -> str:
    """Search for contracts by partial ticker or company name (up to 16 results).

    Args:
        pattern: Partial symbol or company name (e.g. "NVID", "Tesla", "AAPL")
    """
    ib = _get_ib(ctx)
    matches = await ib.reqMatchingSymbolsAsync(pattern)

    if not matches:
        return f"No matching symbols found for '{pattern}'"

    results = []
    for desc in matches:
        c = desc.contract
        results.append(
            {
                "conId": c.conId,
                "symbol": c.symbol,
                "secType": c.secType,
                "currency": c.currency,
                "exchange": c.primaryExchange or c.exchange,
                "description": desc.derivativeSecTypes
                if hasattr(desc, "derivativeSecTypes")
                else None,
            }
        )

    return json.dumps(results, indent=2)


@mcp.tool()
async def check_margin_impact(
    symbol: str,
    action: str,
    quantity: float,
    order_type: str = "MKT",
    limit_price: float | None = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Simulate an order to check margin impact and commission WITHOUT placing it.

    This is a read-only operation safe to use in any mode.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        action: "BUY" or "SELL"
        quantity: Number of shares/contracts
        order_type: "MKT" (market) or "LMT" (limit)
        limit_price: Limit price (required for LMT orders)
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

    if order_type.upper() == "LMT":
        if limit_price is None:
            return "limit_price is required for LMT orders"
        order = LimitOrder(action, quantity, limit_price)
    else:
        order = MarketOrder(action, quantity)

    order.whatIf = True
    trade = ib.placeOrder(contract, order)
    # Wait for the what-if response
    await ib.sleep(1)

    status = trade.orderStatus
    result = {
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "orderType": order_type.upper(),
        "initMarginBefore": status.initMarginBefore,
        "initMarginAfter": status.initMarginAfter,
        "initMarginChange": status.initMarginChange,
        "maintMarginBefore": status.maintMarginBefore,
        "maintMarginAfter": status.maintMarginAfter,
        "maintMarginChange": status.maintMarginChange,
        "equityWithLoanBefore": status.equityWithLoanBefore,
        "equityWithLoanAfter": status.equityWithLoanAfter,
        "commission": status.commission,
        "minCommission": status.minCommission,
        "maxCommission": status.maxCommission,
    }

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_fundamental_events(
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get upcoming fundamental events: earnings, dividends, splits, and conferences.

    Critical for avoiding holding through binary events or timing catalyst-driven trades.

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

    try:
        xml_data = await ib.reqFundamentalDataAsync(contract, reportType="CalendarReport")
    except Exception as e:
        return f"Fundamental data not available for {symbol}: {e}"

    if not xml_data:
        return f"No fundamental calendar data returned for {symbol}"

    result = {"symbol": symbol, "events": []}

    try:
        root = ET.fromstring(xml_data)
        # Parse calendar events from XML
        for event in root.iter():
            if event.tag in ("Event", "EarningsDate", "DividendDate", "SplitDate"):
                entry = {"type": event.tag}
                for child in event:
                    entry[child.tag] = child.text
                # Also grab attributes
                entry.update(event.attrib)
                result["events"].append(entry)

        # If no structured events found, try to extract any text content
        if not result["events"]:
            result["rawXml"] = xml_data[:2000]
    except ET.ParseError:
        result["rawData"] = xml_data[:2000]

    return json.dumps(result, indent=2)
