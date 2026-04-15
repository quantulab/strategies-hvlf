"""Order management tools (requires IB_READONLY=false)."""

import json

from ib_insync import LimitOrder, MarketOrder, Order, StopOrder, TagValue
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


@mcp.tool()
async def place_bracket_order(
    symbol: str,
    action: str,
    quantity: float,
    entry_order_type: str = "MKT",
    entry_limit_price: float | None = None,
    take_profit_price: float | None = None,
    stop_loss_price: float | None = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Place a bracket order: entry + take-profit + stop-loss as an atomic unit.

    All three orders are linked so that when the entry fills, the take-profit and
    stop-loss become active. Filling either child cancels the other (OCA).

    Requires IB_READONLY=false.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        action: "BUY" or "SELL" for the entry order
        quantity: Number of shares/contracts
        entry_order_type: "MKT" or "LMT" for the entry leg
        entry_limit_price: Limit price for entry (required if entry_order_type is LMT)
        take_profit_price: Limit price for the take-profit exit
        stop_loss_price: Stop price for the stop-loss exit
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    if err := _check_readonly(ctx):
        return err

    if take_profit_price is None:
        return "take_profit_price is required for bracket orders"
    if stop_loss_price is None:
        return "stop_loss_price is required for bracket orders"

    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"
    contract = qualified[0]

    if entry_order_type.upper() == "LMT" and entry_limit_price is None:
        return "entry_limit_price is required when entry_order_type is LMT"

    bracket = ib.bracketOrder(
        action,
        quantity,
        limitPrice=entry_limit_price if entry_limit_price is not None else 0,
        takeProfitPrice=take_profit_price,
        stopLossPrice=stop_loss_price,
    )

    parent, take_profit, stop_loss = bracket

    # Override parent to market if requested
    if entry_order_type.upper() == "MKT":
        parent.orderType = "MKT"
        parent.lmtPrice = 0

    trades = []
    for order in [parent, take_profit, stop_loss]:
        trade = ib.placeOrder(contract, order)
        trades.append(trade)

    return json.dumps(
        {
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "parentOrderId": trades[0].order.orderId,
            "takeProfitOrderId": trades[1].order.orderId,
            "takeProfitPrice": take_profit_price,
            "stopLossOrderId": trades[2].order.orderId,
            "stopLossPrice": stop_loss_price,
            "status": trades[0].orderStatus.status,
        },
        indent=2,
    )


@mcp.tool()
async def place_trailing_stop_order(
    symbol: str,
    action: str,
    quantity: float,
    trailing_amount: float | None = None,
    trailing_percent: float | None = None,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Place a trailing stop order that follows price by a fixed amount or percentage.

    Requires IB_READONLY=false.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        action: "BUY" or "SELL"
        quantity: Number of shares/contracts
        trailing_amount: Trail by fixed dollar amount (e.g. 1.50)
        trailing_percent: Trail by percentage (e.g. 5.0 for 5%). Use one or the other.
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    if err := _check_readonly(ctx):
        return err

    if trailing_amount is None and trailing_percent is None:
        return "Provide either trailing_amount or trailing_percent"
    if trailing_amount is not None and trailing_percent is not None:
        return "Provide only one of trailing_amount or trailing_percent, not both"

    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"
    contract = qualified[0]

    order = Order(
        action=action,
        totalQuantity=quantity,
        orderType="TRAIL",
    )
    if trailing_amount is not None:
        order.auxPrice = trailing_amount
    else:
        order.trailingPercent = trailing_percent

    trade = ib.placeOrder(contract, order)

    return json.dumps(
        {
            "orderId": trade.order.orderId,
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "orderType": "TRAIL",
            "trailingAmount": trailing_amount,
            "trailingPercent": trailing_percent,
            "status": trade.orderStatus.status,
        },
        indent=2,
    )


@mcp.tool()
async def place_adaptive_order(
    symbol: str,
    action: str,
    quantity: float,
    order_type: str = "MKT",
    limit_price: float | None = None,
    urgency: str = "Normal",
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    ctx: Context = None,
) -> str:
    """Place an adaptive algo order for better fill quality on larger orders.

    IB's adaptive algorithm works to get a better price than a simple market order.
    Requires IB_READONLY=false.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        action: "BUY" or "SELL"
        quantity: Number of shares/contracts
        order_type: "MKT" or "LMT"
        limit_price: Limit price (required for LMT)
        urgency: "Patient", "Normal", or "Urgent" — controls how aggressively it fills
        sec_type: Security type (default STK)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
    """
    if err := _check_readonly(ctx):
        return err

    if urgency not in ("Patient", "Normal", "Urgent"):
        return "urgency must be 'Patient', 'Normal', or 'Urgent'"

    if order_type.upper() == "LMT" and limit_price is None:
        return "limit_price is required for LMT orders"

    ib = _get_ib(ctx)
    contract = _make_contract(symbol, sec_type, exchange, currency)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return f"Could not find contract for {symbol} ({sec_type})"
    contract = qualified[0]

    order = Order(
        action=action,
        totalQuantity=quantity,
        orderType=order_type.upper(),
        algoStrategy="Adaptive",
        algoParams=[TagValue("adaptivePriority", urgency)],
    )
    if limit_price is not None:
        order.lmtPrice = limit_price

    trade = ib.placeOrder(contract, order)

    return json.dumps(
        {
            "orderId": trade.order.orderId,
            "symbol": contract.symbol,
            "action": action,
            "quantity": quantity,
            "orderType": order_type.upper(),
            "algoStrategy": "Adaptive",
            "urgency": urgency,
            "limitPrice": limit_price,
            "status": trade.orderStatus.status,
        },
        indent=2,
    )
