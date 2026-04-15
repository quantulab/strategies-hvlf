---
noteId: "468a6bb038ec11f1aa17e506bb81f996"
tags: []

---

Read all strategy files from data/strategies/, all lesson files from data/lessons/, and the instruction file data/instructions/scanner_cron_job.md. Follow the instructions exactly through all 8 phases:

PHASE 1: Load lessons, strategies, check positions via get_positions and get_portfolio_pnl, check open orders via get_open_orders.

PHASE 2 (MANDATORY FIRST): Get P&L via get_portfolio_pnl. For any position losing more than 5%, check get_open_orders to avoid duplicates, then place MKT SELL to liquidate. For accidental short positions (quantity < 0), place MKT BUY to close. Reconcile closed trades by calling get_closed_trades(save_to_db=True) and logging any positions that closed since last cycle. Log all exits to the database tables: orders (with strategy_id), strategy_positions (close with exit_reason), lessons (with full trade details). Compute KPIs.

PHASE 3: Call get_scanner_results to analyze scanners. Find tickers trending into top 10. Apply direction logic.

PHASE 4: Match candidates to applicable strategies (01-11). Score conviction per Strategy 9 rules. Apply conflict filter per Strategy 7. Log ALL candidates to scanner_picks (including rejected with reasons).

PHASE 5: Place orders for eligible candidates respecting position limits and quality gate. Log to orders, strategy_positions with strategy_id, conviction_score, scanners_at_entry.

PHASE 6: For each open position, get quote, log price_snapshots, update position extremes.

PHASE 7: Handle any exits — log to strategy_positions, lessons, compute KPIs.

PHASE 8: Log scan_runs and strategy_runs summaries.

All operations MUST be logged to the database with strategy_id, full order details, ticker details, and KPIs.
