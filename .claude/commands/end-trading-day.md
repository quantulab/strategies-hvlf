---
noteId: "a66b193038ec11f1aa17e506bb81f996"
tags: []

---

End-of-day wrap-up for the trading session. Run this near market close (3:30-4:00 PM).

## 1. Final Risk Check

- Call get_portfolio_pnl — cut any remaining positions below -5%
- Call get_open_orders — cancel any unfilled or inactive orders
- Apply Strategy 10 (Overnight Gap Risk):
  - Any position up >50%: sell 50%, set GTC stop at breakeven
  - Any position up 20-50%: sell 25%, set GTC stop 10% below current
  - Any position down >15%: evaluate Strategy 4 (Cut Losers)

## 2. Reconcile All Closed Trades

- Call get_closed_trades(save_to_db=True)
- For EVERY closed trade not yet in lessons table, log it with:
  - symbol, strategy_id, entry/exit prices, P&L, exit_reason, lesson text
- This is the final reconciliation — nothing should be missed

## 3. Daily KPIs

- Call get_daily_kpis for comprehensive performance metrics
- Present the results including:
  - Win rate, profit factor, expectancy, Sharpe estimate
  - P&L by strategy, by exit type, by symbol
  - Best and worst trades
  - Scanner acceptance rate

## 4. Daily Lesson

Based on today's results, write a lesson to data/lessons/ if any of these apply:
- Win rate below 40% — analyze what went wrong
- A strategy had 0 winners — consider disabling or modifying
- A new pattern was discovered (e.g., time of day, scanner combination)
- A risk rule was violated or needs tightening
- Any accidental shorts occurred — document the cause

Format: `data/lessons/YYYYMMDD_topic.md` with frontmatter, What Happened, Rules, How to Apply.

## 5. Update Instructions

If today revealed issues with the operating instructions:
- Update data/instructions/scanner_cron_job.md with new rules
- Update data/strategies/ if a strategy needs modification
- Update data/instructions/system_architecture.md if architecture changed

## 6. Summary

Present a final end-of-day summary:
- Total trades (closed + still open)
- Day's realized P&L and unrealized P&L
- Positions held overnight (with risk assessment)
- Key lessons learned
- Changes made to strategies/instructions
