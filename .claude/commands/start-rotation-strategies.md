---
noteId: "start_rotation_strategies_01"
tags: [cron, trading, rotation, scanner-patterns, setup]

---

Start the rotation strategy engine with recurring cron jobs for all 6 sub-strategies plus the master orchestrator.

## 1. Pre-Market Setup

- Read `data/instructions/strategy_31_rotation_scanner_patterns.md` for the master orchestrator instructions
- Read ALL files in `data/lessons/` to load hard rules from past trades
- Verify IB connection by calling `ensure_connected()`
- Call `get_positions()` to see any positions held overnight
- Call `get_portfolio_pnl()` to assess current P&L
- Call `get_open_orders()` to check for pending orders — **cross-reference against positions to identify pre-existing exit orders (Lesson from RMSG)**
- Verify Station001 scanner data is available: check `\\Station001\DATA\hvlf\rotating\` for today's date folder

## 2. Overnight Position Check

For each held rotation position:
- Check if stop orders are still active (may have expired overnight)
- If stop missing, re-place immediately
- If position gapped down >7% overnight, place MKT SELL at open
- For S36 capsize positions: check if still on upgraded cap tier
- For S37 elite positions: check if still top-5 on gain scanners

## 3. Start the Rotation Cron Job

Set up a single recurring job that runs all rotation strategies every 10 minutes:

```
/loop 10m /run-rotation-strategies
```

This will execute the master orchestrator (S31) plus all 6 sub-strategies in sequence every 10 minutes during market hours.

## 4. Confirm Startup

Report:
- Connection status
- Overnight positions and P&L
- Stop orders verified
- Station001 data availability
- Cron job scheduled
- Today's priority watchlist from yesterday's analysis
