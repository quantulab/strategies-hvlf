---
noteId: "stop_rotation_strategies_01"
tags: [cron, trading, rotation, scanner-patterns, shutdown]

---

Stop the rotation strategy engine gracefully. This cancels the recurring cron job but does NOT close positions — stops remain in place for overnight protection.

## 1. Cancel Cron Jobs

List all active cron jobs and cancel any related to rotation strategies:
- Cancel `/run-rotation-strategies` loop
- Cancel any individual strategy cron jobs (S31-S37)

## 2. Final Position Snapshot

Call `get_positions()` and `get_portfolio_pnl()` to record the final state of all rotation positions.

For each rotation position:
- Record current price, P&L%, stop level, scanner presence
- Verify stop orders are still active via `get_open_orders()`
- If any stop is missing or Inactive, re-place it before shutting down

## 3. Reconcile Trades

Call `get_closed_trades(save_to_db=True)` to reconcile any trades that closed during the session.
Call `get_executions()` to verify all exit order IDs match expected stops (Lesson from RMSG: check for pre-existing orders).

## 4. Log Session Summary

Report:
- Total rotation trades opened today
- Total rotation trades closed today
- Rotation P&L (realized + unrealized)
- Positions held overnight (with stop levels)
- Lessons learned this session
- Tomorrow's watchlist and priority actions

## 5. Important Notes

- **DO NOT close positions** — the stop orders provide overnight protection
- **DO NOT cancel stop orders** — they must remain active for pre-market/overnight moves
- For S34 whipsaw fade: verify ALL short positions are closed (NEVER hold short overnight per Lesson WF-3)
- Positions eligible for overnight hold: S36 capsize (if profitable + crossover active) and S37 elite (if profitable + still top-5)
