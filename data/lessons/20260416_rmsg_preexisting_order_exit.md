---
noteId: "8fe30ca039bd11f19da93711749444a5"
tags: []

---

# Lesson: RMSG Pre-Existing Order Exit

**Date:** 2026-04-16
**Symbol:** RMSG
**Strategy:** multi_scanner (also S37 Elite Accumulation watchlist candidate)
**Entry:** $2.39 at 1:11 PM ET (order 17)
**Exit:** $2.62 at 1:44 PM ET (order 21)
**PnL:** +$0.23 (+9.62% gross, +$0.17 net)
**Hold Duration:** 33 minutes

## What Happened

RMSG was bought at $2.39 by a prior strategy (order 17). The rotation master orchestrator (S31) detected it had no protective stop and placed multiple stop orders (orders 88 at $2.30, then modified to $2.42, then $2.59, $2.64, $2.66 as the position gained).

However, a **pre-existing sell order (order 21)** was already in the system from the original entry strategy. This order filled at $2.62 at 1:44 PM ET — 33 minutes after entry — while we were ratcheting stops that were redundant.

The S31 master orchestrator incorrectly reported this as "stop triggered after-hours" when it was actually a regular-hours exit via a pre-existing order we didn't place.

## Scanner Context

- RMSG was **rank 1 on SmallCap-GainSinceOpen** at time of exit — the strongest possible scanner signal
- RMSG was a **2-day top-5 holder** on SmallCap gain scanners (Apr 13 rank 0, Apr 16 rank 1)
- If held to tomorrow and still top-5, it would have become a **day 3 S37 Elite Accumulation** signal
- The pre-existing sell at $2.62 closed the position before this could be evaluated

## Lessons

### L1: Always inventory existing orders before placing new stops
Before placing protective stops on any position, run `get_open_orders()` and cross-reference every existing order against the position. If a take-profit or bracket exit order already exists, do NOT place additional stops — they create confusion and may trigger unexpected exits.

### L2: Cross-reference execution order IDs to determine exit cause
When a position closes, check `get_executions()` to find the actual order ID that filled. Compare against known order IDs placed by the rotation system. If the exit order ID doesn't match any rotation order, the exit was caused by a different strategy or pre-existing order.

### L3: Rank 1 positions may be worth overriding pre-existing exits
RMSG was rank 1 on GainSinceOpen with a 2-day elite streak forming. The pre-existing sell at $2.62 captured +9.62% — but the position was still strengthening. A rank-1 elite candidate might have run further. Consider cancelling pre-existing take-profit orders when a position qualifies for multi-day rotation hold (S33 streak or S37 elite accumulation).

### L4: The +9.62% was a good outcome despite the process failure
The profit protection ratchet system worked conceptually (we kept raising stops), but the actual exit was via order 21, not our stops. The outcome was positive, but the process was flawed — we didn't know the position already had an exit order.

## Action Items

1. **Add to Phase 1 of ALL rotation strategies:** After loading positions, check `get_open_orders()` and identify any pre-existing exit orders. Log them. If a pre-existing exit conflicts with the rotation hold thesis (e.g., take-profit at +10% when elite accumulation wants to hold for days), consider cancelling it.
2. **Add to Phase 7 exit handling:** When a position disappears, immediately call `get_executions()` to determine the exit order ID and attribute it correctly.
