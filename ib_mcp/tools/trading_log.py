"""Tools for querying the trading decision log, positions, KPIs, and lessons."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from mcp.server.fastmcp import Context

from ib_mcp.db import (
    DB_PATH, get_closed_positions, get_open_positions, get_price_history,
    get_recent_job_executions, get_recent_lessons, get_recent_orders,
    get_recent_picks, get_recent_runs, get_strategy_kpis,
)
from ib_mcp.server import mcp


@mcp.tool()
async def get_trading_picks(limit: int = 50, ctx: Context = None) -> str:
    """Get recent scanner pick decisions with reasoning."""
    picks = get_recent_picks(limit)
    return json.dumps(picks, indent=2) if picks else "No picks logged yet."


@mcp.tool()
async def get_trading_orders(limit: int = 50, ctx: Context = None) -> str:
    """Get recent order placements from scanner-driven trading."""
    orders = get_recent_orders(limit)
    return json.dumps(orders, indent=2) if orders else "No orders logged yet."


@mcp.tool()
async def get_trading_lessons(limit: int = 50, ctx: Context = None) -> str:
    """Get recent trading lessons logged after position exits."""
    lessons = get_recent_lessons(limit)
    return json.dumps(lessons, indent=2) if lessons else "No lessons logged yet."


@mcp.tool()
async def get_scan_runs(limit: int = 20, ctx: Context = None) -> str:
    """Get recent scan run summaries."""
    runs = get_recent_runs(limit)
    return json.dumps(runs, indent=2) if runs else "No scan runs logged yet."


@mcp.tool()
async def get_strategy_positions(
    strategy_id: str = "", status: str = "open", limit: int = 50, ctx: Context = None,
) -> str:
    """Get positions tracked per strategy.

    Args:
        strategy_id: Filter by strategy (e.g. "S01"). Empty for all.
        status: "open" or "closed" (default open)
        limit: Max results for closed positions (default 50)
    """
    if status == "open":
        positions = get_open_positions(strategy_id)
    else:
        positions = get_closed_positions(strategy_id, limit)
    return json.dumps(positions, indent=2) if positions else f"No {status} positions."


@mcp.tool()
async def get_strategy_kpis_report(strategy_id: str = "", ctx: Context = None) -> str:
    """Get KPI report for a strategy: win rate, P&L, drawdown, expectancy, etc.

    Args:
        strategy_id: Strategy ID (e.g. "S01"). Empty for all strategies.
    """
    kpis = get_strategy_kpis(strategy_id)
    return json.dumps(kpis, indent=2) if kpis else "No KPIs computed yet."


@mcp.tool()
async def get_position_price_history(position_id: int, ctx: Context = None) -> str:
    """Get price snapshot history for a tracked position.

    Args:
        position_id: The position ID from strategy_positions table
    """
    history = get_price_history(position_id)
    return json.dumps(history, indent=2) if history else "No price history for this position."


@mcp.tool()
async def get_job_executions(job_id: str = "", limit: int = 20, ctx: Context = None) -> str:
    """Get recent cron job execution history with operations completed.

    Args:
        job_id: Filter by job ID. Empty for all jobs.
        limit: Max results (default 20)
    """
    executions = get_recent_job_executions(job_id, limit)
    return json.dumps(executions, indent=2) if executions else "No job executions logged yet."


@mcp.tool()
async def get_closed_pnl(date: str = "", ctx: Context = None) -> str:
    """Get closed trade P&L for a given date (default today).

    Returns each round-trip trade with buy/sell prices, times, P&L, and
    exit type, plus a summary with totals, win rate, and avg win/loss.

    Args:
        date: Date in YYYY-MM-DD format. Empty for today.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if not date:
        date = __import__("datetime").date.today().isoformat()

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM closed_trades WHERE date(buy_time) = ? ORDER BY net_pnl",
        (date,),
    ).fetchall()]
    conn.close()

    if not rows:
        return f"No closed trades for {date}."

    winners = [t for t in rows if t["net_pnl"] > 0]
    losers = [t for t in rows if t["net_pnl"] <= 0]
    total_pnl = sum(t["net_pnl"] for t in rows)
    win_rate = len(winners) / len(rows) * 100 if rows else 0
    avg_win = sum(t["pnl_pct"] for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t["pnl_pct"] for t in losers) / len(losers) if losers else 0

    result = {
        "date": date,
        "trades": rows,
        "summary": {
            "totalTrades": len(rows),
            "winners": len(winners),
            "losers": len(losers),
            "winRate": round(win_rate, 1),
            "totalNetPnL": round(total_pnl, 4),
            "avgWinPct": round(avg_win, 2),
            "avgLossPct": round(avg_loss, 2),
        },
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_daily_kpis(ctx: Context) -> str:
    """Calculate major KPIs for today's trading session.

    Returns comprehensive metrics from closed trades, open positions,
    scanner activity, and job executions for the current day including:
    win rate, profit factor, expectancy, Sharpe estimate, max drawdown,
    best/worst trades, P&L by strategy, P&L by exit type, and more.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    today = __import__("datetime").date.today().isoformat()

    # --- Closed trades ---
    closed = [dict(r) for r in conn.execute(
        "SELECT * FROM closed_trades WHERE date(buy_time) = ?", (today,)
    ).fetchall()]

    # --- Open positions (from latest portfolio snapshot) ---
    # Use lessons logged today to get strategy breakdown
    lessons_today = [dict(r) for r in conn.execute(
        "SELECT * FROM lessons WHERE date(timestamp) = ?", (today,)
    ).fetchall()]

    # --- Scanner picks today ---
    picks_today = conn.execute(
        "SELECT COUNT(*) as total, SUM(rejected) as rejected FROM scanner_picks WHERE date(timestamp) = ?",
        (today,),
    ).fetchone()

    # --- Orders today ---
    orders_today = conn.execute(
        "SELECT COUNT(*) as total, strategy_id, action FROM orders WHERE date(timestamp) = ? GROUP BY strategy_id, action",
        (today,),
    ).fetchall()

    # --- Job executions today ---
    jobs_today = [dict(r) for r in conn.execute(
        "SELECT * FROM job_executions WHERE date(started_at) = ? ORDER BY id", (today,)
    ).fetchall()]

    conn.close()

    # ---- Compute KPIs from closed trades ----
    if not closed:
        closed_kpis = {"message": "No closed trades today"}
    else:
        winners = [t for t in closed if t["net_pnl"] > 0]
        losers = [t for t in closed if t["net_pnl"] <= 0]
        total_trades = len(closed)
        win_count = len(winners)
        loss_count = len(losers)
        win_rate = win_count / total_trades if total_trades else 0

        gross_wins = sum(t["net_pnl"] for t in winners)
        gross_losses = abs(sum(t["net_pnl"] for t in losers))
        total_pnl = sum(t["net_pnl"] for t in closed)
        total_commission = sum(t["commission"] for t in closed)
        total_gross = sum(t["gross_pnl"] for t in closed)

        avg_win = (sum(t["pnl_pct"] for t in winners) / win_count) if win_count else 0
        avg_loss = (sum(abs(t["pnl_pct"]) for t in losers) / loss_count) if loss_count else 0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Sharpe estimate (annualized from daily returns)
        pnl_values = [t["net_pnl"] for t in closed]
        mean_pnl = sum(pnl_values) / len(pnl_values)
        variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / len(pnl_values)
        std_pnl = variance ** 0.5
        sharpe = (mean_pnl / std_pnl * (252 ** 0.5)) if std_pnl > 0 else 0

        best_trade = max(closed, key=lambda t: t["net_pnl"])
        worst_trade = min(closed, key=lambda t: t["net_pnl"])

        # Max consecutive wins/losses
        sorted_trades = sorted(closed, key=lambda t: t["sell_time"] or "")
        max_consec_w = max_consec_l = cur_w = cur_l = 0
        for t in sorted_trades:
            if t["net_pnl"] > 0:
                cur_w += 1; cur_l = 0
            else:
                cur_l += 1; cur_w = 0
            max_consec_w = max(max_consec_w, cur_w)
            max_consec_l = max(max_consec_l, cur_l)

        # P&L by exit type
        by_exit = defaultdict(lambda: {"count": 0, "pnl": 0.0, "winners": 0})
        for t in closed:
            by_exit[t["exit_type"]]["count"] += 1
            by_exit[t["exit_type"]]["pnl"] += t["net_pnl"]
            if t["net_pnl"] > 0:
                by_exit[t["exit_type"]]["winners"] += 1
        pnl_by_exit = {k: {"count": v["count"], "pnl": round(v["pnl"], 4),
                            "winRate": round(v["winners"] / v["count"] * 100, 1) if v["count"] else 0}
                       for k, v in by_exit.items()}

        # P&L by strategy (from lessons)
        by_strategy = defaultdict(lambda: {"count": 0, "pnl": 0.0, "winners": 0})
        for l in lessons_today:
            sid = l["strategy_id"]
            by_strategy[sid]["count"] += 1
            by_strategy[sid]["pnl"] += (l["pnl"] or 0)
            if (l["pnl"] or 0) > 0:
                by_strategy[sid]["winners"] += 1
        pnl_by_strategy = {k: {"count": v["count"], "pnl": round(v["pnl"], 4),
                                "winRate": round(v["winners"] / v["count"] * 100, 1) if v["count"] else 0}
                           for k, v in by_strategy.items()}

        # Largest winning/losing streaks by symbol
        by_symbol = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
        for t in closed:
            by_symbol[t["symbol"]]["trades"] += 1
            by_symbol[t["symbol"]]["pnl"] += t["net_pnl"]
        pnl_by_symbol = {k: {"trades": v["trades"], "pnl": round(v["pnl"], 4)}
                         for k, v in sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True)}

        closed_kpis = {
            "totalTrades": total_trades,
            "winners": win_count,
            "losers": loss_count,
            "winRate": round(win_rate * 100, 2),
            "avgWinPct": round(avg_win, 2),
            "avgLossPct": round(avg_loss, 2),
            "profitFactor": round(profit_factor, 4),
            "expectancy": round(expectancy, 4),
            "sharpeEstimate": round(sharpe, 4),
            "totalGrossPnL": round(total_gross, 4),
            "totalCommission": round(total_commission, 4),
            "totalNetPnL": round(total_pnl, 4),
            "bestTrade": {"symbol": best_trade["symbol"], "pnl": round(best_trade["net_pnl"], 4), "pnlPct": best_trade["pnl_pct"], "exitType": best_trade["exit_type"]},
            "worstTrade": {"symbol": worst_trade["symbol"], "pnl": round(worst_trade["net_pnl"], 4), "pnlPct": worst_trade["pnl_pct"], "exitType": worst_trade["exit_type"]},
            "maxConsecutiveWins": max_consec_w,
            "maxConsecutiveLosses": max_consec_l,
            "avgTradeNetPnL": round(total_pnl / total_trades, 4),
            "pnlByExitType": pnl_by_exit,
            "pnlByStrategy": pnl_by_strategy,
            "pnlBySymbol": pnl_by_symbol,
        }

    # ---- Scanner activity ----
    scanner_kpis = {
        "totalCandidatesScanned": picks_today["total"] if picks_today else 0,
        "totalRejected": picks_today["rejected"] if picks_today else 0,
        "acceptanceRate": round((1 - (picks_today["rejected"] or 0) / picks_today["total"]) * 100, 1) if picks_today and picks_today["total"] else 0,
    }

    # ---- Orders summary ----
    order_summary = [{"strategy": r["strategy_id"], "action": r["action"], "count": r["total"]} for r in orders_today] if orders_today else []

    # ---- Job execution summary ----
    job_kpis = {
        "totalRuns": len(jobs_today),
        "completedRuns": sum(1 for j in jobs_today if j["status"] == "completed"),
        "failedRuns": sum(1 for j in jobs_today if j["status"] == "failed"),
        "totalOrdersPlaced": sum(j["orders_placed"] or 0 for j in jobs_today),
        "totalLosersClosesd": sum(j["losers_closed"] or 0 for j in jobs_today),
        "totalSnapshotsLogged": sum(j["snapshots_logged"] or 0 for j in jobs_today),
    }

    result = {
        "date": today,
        "closedTradeKPIs": closed_kpis,
        "scannerActivity": scanner_kpis,
        "orderSummary": order_summary,
        "jobExecutions": job_kpis,
    }

    return json.dumps(result, indent=2)
