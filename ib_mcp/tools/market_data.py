"""Market data tools: quotes, historical bars, option chains, depth, histograms."""

import asyncio
import json

from ib_insync import Contract, Option, Stock
from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp


def _get_ib(ctx: Context):
    ib_ctx: IBContext = ctx.request_context.lifespan_context
    return ib_ctx.ib


def _make_contract(symbol: str, sec_type: str, exchange: str, currency: str) -> Contract:
    if sec_type.upper() == "STK":
        return Stock(symbol, exchange, currency)
    return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)


@mcp.tool()
async def get_quote(
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get a real-time price snapshot for a contract (bid, ask, last, volume).

    Args:
        symbol: Ticker symbol (e.g. "AAPL", "MSFT")
        sec_type: Security type - STK, OPT, FUT, CASH, etc.
        exchange: Exchange (default SMART for best routing)
        currency: Currency (default USD)
    """
    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"

    contract = qualified[0]
    ib.reqMktData(contract, snapshot=True)
    await asyncio.sleep(2)  # Wait for snapshot data to arrive
    ticker = ib.ticker(contract)

    result = {
        "symbol": contract.symbol,
        "secType": contract.secType,
        "exchange": contract.exchange,
        "bid": ticker.bid if ticker.bid == ticker.bid else None,  # NaN check
        "ask": ticker.ask if ticker.ask == ticker.ask else None,
        "last": ticker.last if ticker.last == ticker.last else None,
        "volume": ticker.volume if ticker.volume == ticker.volume else None,
        "high": ticker.high if ticker.high == ticker.high else None,
        "low": ticker.low if ticker.low == ticker.low else None,
        "close": ticker.close if ticker.close == ticker.close else None,
    }

    ib.cancelMktData(contract)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_historical_bars(
    symbol: str,
    duration: str = "1 M",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    end_date: str = "",
    ctx: Context = None,
) -> str:
    """Get historical OHLCV bar data for backtesting and analysis.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        duration: How far back to go - "1 D", "1 W", "1 M", "3 M", "1 Y", etc.
        bar_size: Bar size - "1 secs", "5 secs", "1 min", "5 mins", "15 mins", "1 hour", "1 day", etc.
        what_to_show: Data type - TRADES, MIDPOINT, BID, ASK, HISTORICAL_VOLATILITY, OPTION_IMPLIED_VOLATILITY
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
        end_date: End date in YYYYMMDD HH:MM:SS format (empty = now)
    """
    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"

    contract = qualified[0]
    bars = await ib.reqHistoricalDataAsync(
        contract,
        endDateTime=end_date,
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=True,
    )

    if not bars:
        return f"No historical data returned for {symbol}"

    result = []
    for bar in bars:
        result.append(
            {
                "date": str(bar.date),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "barCount": bar.barCount,
                "average": bar.average,
            }
        )

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_option_chain(
    symbol: str,
    exchange: str = "",
    ctx: Context = None,
) -> str:
    """Get available option expirations and strikes for an underlying symbol.

    Args:
        symbol: Underlying ticker symbol (e.g. "AAPL")
        exchange: Exchange filter (empty for all)
    """
    ib = _get_ib(ctx)
    stock = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(stock)
    if not qualified:
        return f"Could not find underlying contract for {symbol}"

    chains = await ib.reqSecDefOptParamsAsync(
        underlyingSymbol=symbol,
        futFopExchange="",
        underlyingSecType="STK",
        underlyingConId=qualified[0].conId,
    )

    if not chains:
        return f"No option chains found for {symbol}"

    result = []
    for chain in chains:
        if exchange and chain.exchange != exchange:
            continue
        result.append(
            {
                "exchange": chain.exchange,
                "underlyingConId": chain.underlyingConId,
                "tradingClass": chain.tradingClass,
                "multiplier": chain.multiplier,
                "expirations": sorted(chain.expirations),
                "strikes": sorted(chain.strikes),
            }
        )

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_option_quotes(
    symbol: str,
    expiration: str,
    strike: float,
    right: str,
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get a price snapshot for a specific option contract.

    Args:
        symbol: Underlying ticker symbol (e.g. "AAPL")
        expiration: Expiration date in YYYYMMDD format
        strike: Strike price
        right: "C" for call, "P" for put
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    ib = _get_ib(ctx)
    contract = Option(symbol, expiration, strike, right, exchange, currency=currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find option {symbol} {expiration} {strike} {right}"

    contract = qualified[0]
    ib.reqMktData(contract, snapshot=True)
    await asyncio.sleep(2)
    ticker = ib.ticker(contract)

    result = {
        "symbol": contract.symbol,
        "expiration": contract.lastTradeDateOrContractMonth,
        "strike": contract.strike,
        "right": contract.right,
        "bid": ticker.bid if ticker.bid == ticker.bid else None,
        "ask": ticker.ask if ticker.ask == ticker.ask else None,
        "last": ticker.last if ticker.last == ticker.last else None,
        "volume": ticker.volume if ticker.volume == ticker.volume else None,
        "openInterest": ticker.callOpenInterest if right == "C" else ticker.putOpenInterest,
    }

    # Greeks if available
    if ticker.modelGreeks:
        g = ticker.modelGreeks
        result["greeks"] = {
            "impliedVol": g.impliedVol,
            "delta": g.delta,
            "gamma": g.gamma,
            "theta": g.theta,
            "vega": g.vega,
        }

    ib.cancelMktData(contract)
    return json.dumps(result, indent=2)


@mcp.tool()
async def set_market_data_type(
    data_type: int = 1,
    ctx: Context = None,
) -> str:
    """Switch between market data types: 1=Live, 2=Frozen, 3=Delayed, 4=Delayed-Frozen.

    Use Delayed (3) if you don't have live market data subscriptions for an exchange.

    Args:
        data_type: 1=Live, 2=Frozen, 3=Delayed, 4=Delayed-Frozen
    """
    ib = _get_ib(ctx)
    labels = {1: "Live", 2: "Frozen", 3: "Delayed", 4: "Delayed-Frozen"}
    if data_type not in labels:
        return f"Invalid data_type {data_type}. Must be 1, 2, 3, or 4."

    ib.reqMarketDataType(data_type)

    return json.dumps(
        {"dataType": data_type, "label": labels[data_type], "status": "set"},
        indent=2,
    )


@mcp.tool()
async def get_market_depth(
    symbol: str,
    num_rows: int = 5,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get Level II order book data showing bid/ask depth at multiple price levels.

    Useful for gauging liquidity and support/resistance before entering a position.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        num_rows: Number of price levels to show (default 5, max 20)
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

    num_rows = min(num_rows, 20)
    ib.reqMktDepth(contract, numRows=num_rows)
    await asyncio.sleep(3)
    ticker = ib.ticker(contract)

    bids = []
    if ticker.domBids:
        for dom in ticker.domBids[:num_rows]:
            bids.append({"price": dom.price, "size": dom.size, "marketMaker": dom.marketMaker})

    asks = []
    if ticker.domAsks:
        for dom in ticker.domAsks[:num_rows]:
            asks.append({"price": dom.price, "size": dom.size, "marketMaker": dom.marketMaker})

    ib.cancelMktDepth(contract)

    return json.dumps(
        {"symbol": symbol, "bids": bids, "asks": asks},
        indent=2,
    )


@mcp.tool()
async def get_head_timestamp(
    symbol: str,
    what_to_show: str = "TRADES",
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get the earliest available date for historical data on a contract.

    Useful to check how far back historical data goes before requesting it.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        what_to_show: Data type - TRADES, BID, ASK, MIDPOINT, etc.
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

    head = await ib.reqHeadTimeStampAsync(contract, whatToShow=what_to_show, useRTH=True)

    return json.dumps(
        {
            "symbol": symbol,
            "whatToShow": what_to_show,
            "earliestTimestamp": str(head) if head else None,
        },
        indent=2,
    )


@mcp.tool()
async def get_histogram(
    symbol: str,
    period: str = "1 month",
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Get price-volume distribution (volume profile) for support/resistance analysis.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        period: Time period - "1 week", "1 month", "3 months", "6 months", "1 year"
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

    data = await ib.reqHistogramDataAsync(contract, useRTH=True, period=period)

    if not data:
        return f"No histogram data returned for {symbol}"

    items = [{"price": item.price, "count": item.count} for item in data]

    return json.dumps(
        {"symbol": symbol, "period": period, "histogram": items},
        indent=2,
    )
