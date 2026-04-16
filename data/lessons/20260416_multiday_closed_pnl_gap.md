---
noteId: "multiday_closed_pnl_20260416"
tags: [lesson, system, database, closed-pnl, multi-day]
---

# Lesson: Multi-Day Trades Missing from Closed P&L

## Date: 2026-04-16
## Context: ASTI bought on 2026-04-15 at $2.50, sold on 2026-04-16 at $6.14 (+$3.64, +145.6%). Trade did not appear in get_closed_pnl or get_daily_kpis.

---

## What Happened

ASTI was the biggest winner of the session (+$3.64, +145.6%) but was invisible in:
1. `get_closed_pnl` — filtered by `date(buy_time) = today`, missed because buy was yesterday
2. `get_closed_trades` — only matches IB executions from today; IB doesn't return yesterday's buy fill, so no round-trip match
3. `get_daily_kpis` — same `date(buy_time)` filter as get_closed_pnl

This means any trade held overnight or longer would vanish from daily P&L reporting.

## Root Cause

The `closed_trades` table and all query tools assumed same-day round trips. Multi-day holds were never accounted for because the original system only did intraday bracket trades.

## Fix Applied

1. **`get_closed_pnl`**: Changed query to `WHERE date(buy_time) = ? OR date(sell_time) = ?` — any trade sold today appears in today's P&L. Also added fallback to `strategy_positions` table for trades not in `closed_trades`.
2. **`get_closed_trades`**: Added fallback that checks `strategy_positions` closed today and appends any multi-day trades not already matched from IB fills.
3. **`get_daily_kpis`**: Same fix as get_closed_pnl — query by sell_time too, plus strategy_positions fallback.

## Rule

Any position **sold** on a given day MUST appear in that day's closed P&L, regardless of when it was bought. The sell date is the P&L realization date.

## How to Apply

- `strategy_positions` is the authoritative record for all trades (entry, exit, P&L, strategy)
- `closed_trades` from IB is supplementary — it only covers same-day round trips
- Always cross-reference both tables when computing daily P&L
- When the cron job closes a position via trailing stop ratchet, the exit is logged in `strategy_positions` immediately — this is the record that matters
