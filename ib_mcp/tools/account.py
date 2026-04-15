"""Account and portfolio tools."""

import asyncio
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from ib_insync import ExecutionFilter, Stock
from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp

DB_PATH = Path(__file__).resolve().parent.parent.parent / "trading.db"


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
async def get_portfolio_pnl(ctx: Context) -> str:
    """Get a P&L summary for all open positions with current market prices.

    Returns a table with symbol, quantity, avg cost, current price,
    market value, unrealized P&L, and P&L percentage for each position,
    plus portfolio totals.
    """
    ib = _get_ib(ctx)
    positions = ib.positions()

    if not positions:
        return "No open positions."

    # Build contracts and request market data for all positions
    contracts = []
    for pos in positions:
        contract = Stock(pos.contract.symbol, "SMART", pos.contract.currency)
        contracts.append((pos, contract))

    # Qualify all contracts concurrently
    qualified_map = {}
    for pos, contract in contracts:
        qualified = await ib.qualifyContractsAsync(contract)
        if qualified:
            qualified_map[pos.contract.symbol] = (pos, qualified[0])

    # Request snapshots for all qualified contracts
    for symbol, (pos, contract) in qualified_map.items():
        ib.reqMktData(contract, snapshot=True)

    await asyncio.sleep(2)

    rows = []
    total_cost = 0.0
    total_market_value = 0.0
    total_pnl = 0.0

    for symbol, (pos, contract) in qualified_map.items():
        ticker = ib.ticker(contract)
        # Use last price, fall back to close, then to bid/ask midpoint
        price = None
        if ticker.last == ticker.last and ticker.last > 0:
            price = ticker.last
        elif ticker.close == ticker.close and ticker.close > 0:
            price = ticker.close
        elif (ticker.bid == ticker.bid and ticker.ask == ticker.ask
              and ticker.bid > 0 and ticker.ask > 0):
            price = (ticker.bid + ticker.ask) / 2

        qty = pos.position
        avg_cost = pos.avgCost
        cost_basis = avg_cost * qty
        market_value = price * qty if price else None
        unrealized_pnl = (market_value - cost_basis) if market_value is not None else None
        pnl_pct = (unrealized_pnl / cost_basis * 100) if unrealized_pnl is not None and cost_basis != 0 else None

        total_cost += cost_basis
        if market_value is not None:
            total_market_value += market_value
            total_pnl += unrealized_pnl

        rows.append({
            "symbol": symbol,
            "quantity": qty,
            "avgCost": round(avg_cost, 4),
            "currentPrice": round(price, 4) if price else None,
            "costBasis": round(cost_basis, 2),
            "marketValue": round(market_value, 2) if market_value is not None else None,
            "unrealizedPnL": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
            "pnlPercent": round(pnl_pct, 2) if pnl_pct is not None else None,
        })

        ib.cancelMktData(contract)

    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost != 0 else None

    result = {
        "positions": rows,
        "totals": {
            "totalCostBasis": round(total_cost, 2),
            "totalMarketValue": round(total_market_value, 2),
            "totalUnrealizedPnL": round(total_pnl, 2),
            "totalPnLPercent": round(total_pnl_pct, 2) if total_pnl_pct is not None else None,
        },
    }

    return json.dumps(result, indent=2)


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


def _ensure_closed_trades_table():
    """Create closed_trades table if it doesn't exist (round-trip format)."""
    conn = sqlite3.connect(str(DB_PATH))
    # Drop the old raw-execution schema if it exists
    info = conn.execute("PRAGMA table_info(closed_trades)").fetchall()
    col_names = [row[1] for row in info]
    if info and "buy_price" not in col_names:
        conn.execute("DROP TABLE closed_trades")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            buy_price REAL NOT NULL,
            sell_price REAL NOT NULL,
            buy_time TEXT NOT NULL,
            sell_time TEXT NOT NULL,
            gross_pnl REAL NOT NULL,
            net_pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            commission REAL DEFAULT 0,
            exit_type TEXT DEFAULT 'unknown',
            UNIQUE(symbol, buy_time, sell_time)
        )
    """)
    conn.commit()
    conn.close()


@mcp.tool()
async def get_closed_trades(ctx: Context, save_to_db: bool = True) -> str:
    """Get today's completed executions (fills), match buys with sells to find
    closed round-trip trades, compute P&L, and optionally save to the database.

    Args:
        save_to_db: Whether to save executions to the trading.db closed_trades table (default True)
    """
    ib = _get_ib(ctx)

    # Request today's executions
    fills = await ib.reqExecutionsAsync(ExecutionFilter())

    if not fills:
        return "No executions found for today."

    # Group executions by symbol to match round trips
    by_symbol = defaultdict(list)
    for fill in fills:
        ex = fill.execution
        by_symbol[fill.contract.symbol].append({
            "side": ex.side,
            "shares": ex.shares,
            "price": ex.price,
            "time": ex.time.isoformat() if hasattr(ex.time, 'isoformat') else str(ex.time),
            "commission": fill.commissionReport.commission if fill.commissionReport else 0,
            "orderId": ex.orderId,
        })

    # Build round-trip P&L
    trades = []
    for symbol, execs in by_symbol.items():
        buys = [e for e in execs if e["side"] == "BOT"]
        sells = [e for e in execs if e["side"] == "SLD"]

        total_buy_cost = sum(e["price"] * e["shares"] for e in buys)
        total_buy_shares = sum(e["shares"] for e in buys)
        total_sell_proceeds = sum(e["price"] * e["shares"] for e in sells)
        total_sell_shares = sum(e["shares"] for e in sells)
        total_commission = sum(e["commission"] for e in execs)

        avg_buy = total_buy_cost / total_buy_shares if total_buy_shares else 0
        avg_sell = total_sell_proceeds / total_sell_shares if total_sell_shares else 0
        closed_shares = min(total_buy_shares, total_sell_shares)

        if closed_shares > 0:
            gross_pnl = (avg_sell - avg_buy) * closed_shares
            net_pnl = gross_pnl - total_commission
            pnl_pct = ((avg_sell - avg_buy) / avg_buy * 100) if avg_buy else 0

            exit_type = "unknown"
            if sells:
                # Determine if exit was stop or limit based on price
                sell_price = sells[0]["price"]
                # Check against orders table
                try:
                    conn = sqlite3.connect(str(DB_PATH))
                    row = conn.execute(
                        "SELECT stop_price, limit_price FROM orders WHERE symbol=? AND action='SELL' AND order_type='STP'",
                        (symbol,),
                    ).fetchone()
                    if row and row[0]:
                        stop_price = row[0]
                        limit_row = conn.execute(
                            "SELECT limit_price FROM orders WHERE symbol=? AND action='SELL' AND order_type='LMT'",
                            (symbol,),
                        ).fetchone()
                        limit_price = limit_row[0] if limit_row else None

                        if sell_price <= stop_price * 1.02:
                            exit_type = "stop_loss"
                        elif limit_price and sell_price >= limit_price * 0.98:
                            exit_type = "take_profit"
                        else:
                            exit_type = "manual"
                    conn.close()
                except Exception:
                    pass

            trades.append({
                "symbol": symbol,
                "avgBuyPrice": round(avg_buy, 4),
                "avgSellPrice": round(avg_sell, 4),
                "closedShares": closed_shares,
                "remainingShares": total_buy_shares - total_sell_shares,
                "grossPnL": round(gross_pnl, 4),
                "commission": round(total_commission, 4),
                "netPnL": round(net_pnl, 4),
                "pnlPercent": round(pnl_pct, 2),
                "exitType": exit_type,
                "buyTime": buys[0]["time"] if buys else None,
                "sellTime": sells[0]["time"] if sells else None,
            })
        else:
            # Open-only (bought but not sold yet)
            trades.append({
                "symbol": symbol,
                "avgBuyPrice": round(avg_buy, 4) if buys else None,
                "avgSellPrice": round(avg_sell, 4) if sells else None,
                "closedShares": 0,
                "remainingShares": total_buy_shares - total_sell_shares,
                "grossPnL": 0,
                "commission": round(total_commission, 4),
                "netPnL": round(-total_commission, 4),
                "pnlPercent": 0,
                "exitType": "still_open",
                "buyTime": buys[0]["time"] if buys else None,
                "sellTime": None,
            })

    # Save round-trip trades to DB
    if save_to_db:
        _ensure_closed_trades_table()
        conn = sqlite3.connect(str(DB_PATH))
        for t in trades:
            if t["closedShares"] > 0 and t["buyTime"] and t["sellTime"]:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO closed_trades
                           (symbol, quantity, buy_price, sell_price, buy_time, sell_time,
                            gross_pnl, net_pnl, pnl_pct, commission, exit_type)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            t["symbol"], t["closedShares"],
                            t["avgBuyPrice"], t["avgSellPrice"],
                            t["buyTime"], t["sellTime"],
                            t["grossPnL"], t["netPnL"],
                            t["pnlPercent"], t["commission"],
                            t["exitType"],
                        ),
                    )
                except Exception:
                    pass
        conn.commit()
        conn.close()

    # Sort by P&L
    trades.sort(key=lambda t: t["netPnL"])

    total_net = sum(t["netPnL"] for t in trades)
    total_commission = sum(t["commission"] for t in trades)
    winners = sum(1 for t in trades if t["netPnL"] > 0)
    losers = sum(1 for t in trades if t["netPnL"] < 0)

    result = {
        "trades": trades,
        "summary": {
            "totalTrades": len(trades),
            "winners": winners,
            "losers": losers,
            "winRate": round(winners / len(trades) * 100, 1) if trades else 0,
            "totalNetPnL": round(total_net, 4),
            "totalCommission": round(total_commission, 4),
        },
    }

    return json.dumps(result, indent=2)


@mcp.tool()
async def get_executions(
    symbol: str = "",
    sec_type: str = "",
    side: str = "",
    ctx: Context = None,
) -> str:
    """Get raw fill-by-fill execution reports with commissions.

    More granular than get_closed_trades — returns individual fills rather than
    aggregated round-trips. Useful for analyzing fill quality and slippage.

    Args:
        symbol: Filter by symbol (empty for all)
        sec_type: Filter by security type (empty for all)
        side: Filter by side - "BUY" or "SELL" (empty for all)
    """
    ib = _get_ib(ctx)

    exec_filter = ExecutionFilter()
    if symbol:
        exec_filter.symbol = symbol
    if sec_type:
        exec_filter.secType = sec_type
    if side:
        exec_filter.side = side

    fills = await ib.reqExecutionsAsync(exec_filter)

    if not fills:
        return "No executions found."

    result = []
    for fill in fills:
        ex = fill.execution
        cr = fill.commissionReport
        result.append(
            {
                "execId": ex.execId,
                "orderId": ex.orderId,
                "symbol": fill.contract.symbol,
                "secType": fill.contract.secType,
                "side": ex.side,
                "shares": ex.shares,
                "price": ex.price,
                "time": ex.time.isoformat() if hasattr(ex.time, "isoformat") else str(ex.time),
                "exchange": ex.exchange,
                "commission": cr.commission if cr else None,
                "realizedPnL": cr.realizedPNL if cr else None,
            }
        )

    return json.dumps(result, indent=2)
