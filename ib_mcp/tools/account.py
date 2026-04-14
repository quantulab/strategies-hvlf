"""Account and portfolio tools."""

import json

from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp


def _get_ib(ctx: Context):
    ib_ctx: IBContext = ctx.request_context.lifespan_context
    return ib_ctx.ib


@mcp.tool()
async def get_account_summary(ctx: Context) -> str:
    """Get account summary: net liquidation, cash, buying power, P&L, and other key metrics."""
    ib = _get_ib(ctx)
    summary = ib.accountSummary()
    if not summary:
        # Request fresh data
        await ib.reqAccountSummaryAsync()
        summary = ib.accountSummary()

    key_tags = {
        "NetLiquidation",
        "TotalCashValue",
        "BuyingPower",
        "GrossPositionValue",
        "UnrealizedPnL",
        "RealizedPnL",
        "AvailableFunds",
        "MaintMarginReq",
        "InitMarginReq",
    }

    result = {}
    for item in summary:
        if item.tag in key_tags:
            result[item.tag] = {"value": item.value, "currency": item.currency}

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_positions(ctx: Context) -> str:
    """Get current portfolio positions with quantity, average cost, and market value."""
    ib = _get_ib(ctx)
    positions = ib.positions()

    result = []
    for pos in positions:
        result.append(
            {
                "account": pos.account,
                "symbol": pos.contract.symbol,
                "secType": pos.contract.secType,
                "exchange": pos.contract.exchange,
                "currency": pos.contract.currency,
                "quantity": pos.position,
                "avgCost": pos.avgCost,
            }
        )

    return json.dumps(result, indent=2) if result else "No open positions."


@mcp.tool()
async def get_open_orders(ctx: Context) -> str:
    """Get all open/pending orders with their current status."""
    ib = _get_ib(ctx)
    trades = ib.openTrades()

    result = []
    for trade in trades:
        order = trade.order
        contract = trade.contract
        status = trade.orderStatus
        result.append(
            {
                "orderId": order.orderId,
                "symbol": contract.symbol,
                "secType": contract.secType,
                "action": order.action,
                "quantity": order.totalQuantity,
                "orderType": order.orderType,
                "limitPrice": order.lmtPrice,
                "stopPrice": order.auxPrice,
                "status": status.status,
                "filled": status.filled,
                "remaining": status.remaining,
                "avgFillPrice": status.avgFillPrice,
            }
        )

    return json.dumps(result, indent=2) if result else "No open orders."
