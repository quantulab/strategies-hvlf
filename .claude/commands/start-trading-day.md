---
noteId: "51432bf038ec11f1aa17e506bb81f996"
tags: []

---

Start the automated trading engine for the day. Follow these steps in order:

## 1. Pre-Market Setup

- Read data/instructions/scanner_cron_job.md for the latest operating instructions
- Read data/instructions/system_architecture.md for system context
- Read ALL files in data/lessons/ to load hard rules from past trades
- Read ALL files in data/strategies/ to load the 11 trading strategies
- Verify IB connection by calling get_account_summary

## 2. Check Overnight State

- Call get_positions to see any positions held overnight
- Call get_portfolio_pnl to assess current P&L
- Call get_open_orders to check for any pending orders
- Review Strategy 10 (Overnight Gap Risk) rules for any positions that moved >20% overnight
- If any position gapped down >10%, place MKT SELL at open

## 3. Start the Cron Job

Set up a recurring job that runs every 10 minutes using:
```
/loop 10m /run-trading-engine
```

This will execute the full 8-phase engine every 10 minutes throughout the trading day.

## 4. Monitor

The cron job handles everything automatically:
- Cuts losers at -5% (Phase 2)
- Reconciles closed trades from IB (Phase 2)
- Scans for new candidates (Phase 3)
- Scores conviction and applies conflict filter (Phase 4)
- Places orders for eligible candidates with quality gate (Phase 5)
- Monitors positions with price snapshots (Phase 6)
- Logs exits and lessons (Phase 7)
- Records all operations to the database (Phase 8)

## 5. End of Day

Near market close (3:30 PM):
- Review Strategy 10 (Overnight Gap Risk) for positions to reduce
- Call get_daily_kpis for the day's performance summary
- Review lessons learned and write significant ones to data/lessons/
- Consider updating strategies in data/strategies/ based on the day's results
