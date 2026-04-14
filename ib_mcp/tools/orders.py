"""Order management tools (requires IB_READONLY=false)."""

import json

from ib_insync import LimitOrder, MarketOrder, Order, StopOrder
from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp


def _get_ctx(ctx: Context) -> IBContext:
    return ctx.request_context.lifespan_context


def _get_ib(ctx: Context):
    return _get_ctx(ctx).ib


def _check_readonly(ctx: Context) -> str | None:
    ib_ctx = _get_ctx(ctx)
    if ib_ctx.config.readonly:
        return (
            "Order placement is disabled (readonly mode). "
            "Set environment variable IB_READONLY=false to enable trading."
        )
    return None


def _make_contract(symbol: str, sec_type: str, exchange: str, currency: str):
    from ib_insync import Contract, Stock

    if sec_type.upper() == "STK":
        return Stock(symbol, exchange, currency)
    return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)


@mcp.tool()
async def place_order(
    symbol: str,
    action: str,
    quantity: float,
    order_type: str = "LMT",
    limit_price: float | None = None,
    stop_price: float | None = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Place an order (market, limit, or stop). Requires IB_READONLY=false.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        action: "BUY" or "SELL"
        quantity: Number of shares/contracts
        order_type: "MKT" (market), "LMT" (limit), or "STP" (stop)
        limit_price: Limit price (required for LMT orders)
        stop_price: Stop price (required for STP orders)
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    if err := _check_readonly(ctx):
        return err

    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"
    contract = qualified[0]

    order_type = order_type.upper()
    order: Order
    if order_type == "MKT":
        order = MarketOrder(action, quantity)
    elif order_type == "LMT":
        if limit_price is None:
            return "limit_price is required for LMT orders"
        order = LimitOrder(action, quantity, limit_price)
    elif order_type == "STP":
        if stop_price is None:
            return "stop_price is required for STP orders"
        order = StopOrder(action, quantity, stop_price)
    else:
        return f"Unsupported order type: {order_type}. Use MKT, LMT, or STP."

    trade = ib.placeOrder(contract, order)

    return json.dumps(
        {
            "orderId": trade.order.orderId,
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "orderType": order_type,
            "limitPrice": limit_price,
            "stopPrice": stop_price,
            "status": trade.orderStatus.status,
        },
        indent=2,
    )


@mcp.tool()
async def cancel_order(order_id: int, ctx: Context = None) -> str:
    """Cancel an open order by its order ID. Requires IB_READONLY=false.

    Args:
        order_id: The order ID to cancel
    """
    if err := _check_readonly(ctx):
        return err

    ib = _get_ib(ctx)
    for trade in ib.openTrades():
        if trade.order.orderId == order_id:
            ib.cancelOrder(trade.order)
            return json.dumps(
                {"orderId": order_id, "status": "cancel_requested"}, indent=2
            )

    return f"No open order found with ID {order_id}"


@mcp.tool()
async def modify_order(
    order_id: int,
    quantity: float | None = None,
    limit_price: float | None = None,
    stop_price: float | None = None,
    ctx: Context = None,
) -> str:
    """Modify an existing open order's quantity or price. Requires IB_READONLY=false.

    Args:
        order_id: The order ID to modify
        quantity: New quantity (None to keep current)
        limit_price: New limit price (None to keep current)
        stop_price: New stop price (None to keep current)
    """
    if err := _check_readonly(ctx):
        return err

    ib = _get_ib(ctx)
    for trade in ib.openTrades():
        if trade.order.orderId == order_id:
            order = trade.order
            contract = trade.contract

            if quantity is not None:
                order.totalQuantity = quantity
            if limit_price is not None:
                order.lmtPrice = limit_price
            if stop_price is not None:
                order.auxPrice = stop_price

            ib.placeOrder(contract, order)
            return json.dumps(
                {
                    "orderId": order_id,
                    "status": "modified",
                    "quantity": order.totalQuantity,
                    "limitPrice": order.lmtPrice,
                    "stopPrice": order.auxPrice,
                },
                indent=2,
            )

    return f"No open order found with ID {order_id}"
