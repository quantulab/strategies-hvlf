"""News tools: IB news headlines and article bodies."""

import asyncio
import json
from datetime import datetime

from ib_insync import Stock
from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp


def _get_ib(ctx: Context):
    ib_ctx: IBContext = ctx.request_context.lifespan_context
    return ib_ctx.ib


@mcp.tool()
async def get_news_providers(ctx: Context = None) -> str:
    """List available news providers from IB."""
    ib = _get_ib(ctx)
    providers = await ib.reqNewsProvidersAsync()
    result = [{"code": p.code, "name": p.name} for p in providers]
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_news_headlines(
    symbol: str = "",
    provider_codes: str = "",
    start: str = "",
    end: str = "",
    max_results: int = 30,
    ctx: Context = None,
) -> str:
    """Get recent news headlines, optionally filtered by symbol.

    Args:
        symbol: Ticker symbol to filter news for (e.g. "AAPL"). Empty for broad market news.
        provider_codes: Comma-separated provider codes (e.g. "BRFG,DJNL"). Empty for all.
        start: Start datetime in YYYYMMDD HH:MM:SS format (empty for no start filter)
        end: End datetime in YYYYMMDD HH:MM:SS format (empty for now)
        max_results: Maximum number of headlines to return (default 30)
    """
    ib = _get_ib(ctx)

    con_id = 0
    if symbol:
        contract = Stock(symbol, "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            return f"Could not find contract for {symbol}"
        con_id = qualified[0].conId

    headlines = await ib.reqHistoricalNewsAsync(
        conId=con_id,
        providerCodes=provider_codes or "BRFG+BRFUPDN+DJNL",
        startDateTime=start,
        endDateTime=end,
        totalResults=max_results,
    )

    if not headlines:
        return f"No news headlines found{' for ' + symbol if symbol else ''}"

    result = []
    for h in headlines:
        result.append(
            {
                "time": h.time.strftime("%Y-%m-%d %H:%M:%S") if h.time else "",
                "providerCode": h.providerCode,
                "articleId": h.articleId,
                "headline": h.headline,
            }
        )

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_news_article(
    provider_code: str,
    article_id: str,
    ctx: Context = None,
) -> str:
    """Get the full text of a news article by its provider code and article ID.

    Args:
        provider_code: News provider code (e.g. "BRFG", "DJNL")
        article_id: Article ID from a headlines response
    """
    ib = _get_ib(ctx)
    article = await ib.reqNewsArticleAsync(provider_code, article_id)

    if not article:
        return f"Could not retrieve article {article_id} from {provider_code}"

    return json.dumps(
        {
            "articleType": article.articleType,
            "articleText": article.articleText,
        },
        indent=2,
    )
