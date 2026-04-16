---
noteId: "eod_20260416_system"
tags: [lesson, eod, system, stop-orders, penny-stocks, extended-moves]
---

# End-of-Day Lesson: Day 2 System Observations

## Date: 2026-04-16
## Context: 29 cron cycles, 4 closed trades (3W/1L), +$3.50 realized, 2 positions held overnight

---

## What Happened

### 1. Penny Stock Domination of Tier 1
The scanner universe was dominated by sub-$2 names all day (ONFO, MAMO, ZSPC, CIRX). Only 3 large-cap names consistently reached Tier 1 (ONFO, WNW, PBM), and all had issues:
- ONFO: Traded twice early, 1W/1L, then exhausted
- WNW: STP orders went Inactive on every attempt (trading restriction)
- PBM: Entered after +178% run, stopped out in 9 seconds

### 2. STP Orders Going Inactive
RMSG and WNW both had persistent Inactive STP orders. RMSG's stop was replaced 4+ times. This is a critical safety gap — positions can exist without functioning stops.

### 3. Late Volume Confirmation = Chasing
PBM dominated gain scanners for 4 cycles before appearing on HotByVolume. By the time volume confirmed, the stock had already run +178% from open. Entry at the top resulted in immediate stop-out.

### 4. Manual Positions Outperformed Scanner System
ACHV, RMSG, and NVTS (manually entered) all performed well. The scanner system's multi_scanner strategy went 1W/3L (-$0.18). The momentum_surfing carry from yesterday (ASTI +$3.64) was the real winner.

## Rules

1. **Inactive STP workaround**: If a STP order goes Inactive on a symbol 2+ times, use a trailing stop order (`place_trailing_stop_order`) instead. If that also fails, the position must be manually monitored every cycle with a market sell if it breaches the stop level.

2. **Extended move filter**: If a stock has already gained >100% from open before reaching Tier 1, treat it as "extended" and require a pullback to VWAP or 50% of range before entry. Do not chase at the highs.

3. **Penny stock ceiling**: Today 3 of 4 Tier 1 candidates were sub-$2. The $2 quality gate correctly filtered them. No change needed — the gate is working as designed.

4. **EOD auto-trigger**: Added automatic `/end-trading-day` trigger at 3:30 PM ET to the cron job instructions. Prevents empty cycles after close.

## How to Apply

- Phase 2: After 2 Inactive STP attempts on a symbol, switch to `place_trailing_stop_order` or manual monitoring
- Phase 5: Add extended move filter — reject Tier 1 if intraday gain >100% from open at time of entry
- Phase 8: Check time and trigger EOD if 15:30-16:00 ET
- Scanner cron: Already updated with EOD auto-trigger rule
