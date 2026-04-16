---
noteId: "rotation_strategies_cmd_01"
tags: [cron, trading, rotation, scanner-patterns]

---

Run ALL 6 rotation sub-strategies plus the master orchestrator in sequence. Read each instruction file from `data/instructions/` and execute all 8 phases. Use scanner data from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` (33 feeds across 3 cap tiers).

## Pre-Flight

1. Call `ensure_connected()` to verify IB connection
2. Call `get_positions()` and `get_open_orders()` to load current state
3. Check market hours — if market is closed, report status and skip

## Execute Strategies (in order)

### 1. Master Orchestrator (S31)
Read `data/instructions/strategy_31_rotation_scanner_patterns.md`
- Classify market regime (G/L ratio from Station001 gain vs loss scanner counts)
- Determine which sub-strategies are prioritized for current regime
- Risk management on ALL rotation positions (cut losers, reconcile closed trades)
- Monitor all open rotation positions, ratchet trailing stops per profit protection table

### 2. Volume Surge Entry (S32)
Read `data/instructions/strategy_32-rotation-volume_surge.md`
- Scan Station001 volume scanners (HotByVolume, MostActive, TopVolumeRate) across all 3 cap tiers
- Find symbols on volume scanners but NOT on gain or loss scanners
- Cross-reference against known predictable tickers (SOXL, SQQQ, NVDA, TQQQ, PLTR, INTC, RKLB, etc.)
- Score conviction per the table. Tier 1 (5+) = trade. Entry: MKT BUY + STP SELL at -5%
- Time stop: 180 min. If gain scanner appears, switch to trailing stop.
- **Skip if market closed or past 1 PM** (insufficient time for 120-min lead conversion)

### 3. Streak Continuation (S33)
Read `data/instructions/strategy_33-rotation-streak_continuation.md`
- Compare today's gain scanner top-10 against prior days from Station001 to detect multi-day streaks
- Signal fires at day 3+ on same gain scanner with improving rank
- Filter against whipsaw watchlist (Lesson SC-4)
- Entry: MKT BUY on pullback, STP SELL below prior day's low
- **Only enter on pullback, not at parabolic extension**

### 4. Whipsaw Fade (S34)
Read `data/instructions/strategy_34-rotation-whipsaw_fade.md`
- **STOP scanning after 2:00 PM ET**
- Find known EXTREME whipsaw names (30+ days per report) on gain scanners
- Confirm fade setup: up >2% from close, spread <= 2%
- If G/L ratio > 1.5 (trending day), DISABLE all fades
- Entry: SHORT (SELL) at market, STP BUY cover at HOD +2%, target prior close
- Time stop: 60 min. **NEVER hold short overnight.**

### 5. Pre-Market Persistence (S35)
Read `data/instructions/strategy_35-rotation-premarket_persist.md`
- **Entry window: 9:35-10:00 AM only**
- At 9:25 AM: scan for pre-market movers on gain scanners
- At 9:35 AM: confirm persistence (still on gain scanner)
- Filter whipsaw names (EXTREME/HIGH = reject)
- Entry: MKT BUY at 9:35 confirmation, STP SELL at -5% or VWAP
- Time stop: 90 min

### 6. Cap-Size Breakout (S36)
Read `data/instructions/strategy_36-rotation-capsize_breakout.md`
- Compare symbol presence across SmallCap/MidCap/LargeCap scanners from Station001
- Detect UPGRADE crossovers (SmallCap->MidCap or MidCap->LargeCap)
- Signal fires at 2+ consecutive crossover days with volume > 2x avg
- Exclude leveraged ETFs
- Entry: MKT BUY, STP SELL at -7% (wider for multi-day hold)
- **Allow overnight hold** if profitable + crossover active + not whipsaw + stop in place

### 7. Elite Accumulation (S37)
Read `data/instructions/strategy_37-rotation-elite_accumulation.md`
- **Start at 9:45 AM** (let VWAP establish)
- Find top-5 holders on gain scanners for 3+ consecutive days
- Entry ONLY on VWAP pullback (within 0.5% of VWAP)
- LMT BUY at VWAP, STP SELL below prior day's low
- **Allow overnight hold** if profitable + still top-5 + not whipsaw + stop in place

## Post-Run

- Log run summary with candidates found, rejected, orders placed per sub-strategy
- Report portfolio state with all positions, P&L, and stop levels
- Identify tomorrow's watchlist candidates

## Key Rules (Apply to ALL sub-strategies)

- **Station001 data**: Read scanner CSVs from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` — do NOT rely solely on MCP `get_scanner_results` (smaller dataset)
- **1 share per ticker** across all sub-strategies
- **Max 6 concurrent rotation positions** (1 per sub-strategy max)
- **Max 2 new entries per cycle** (batch entry protection)
- **Profit protection ratchet**: +5-10% = breakeven stop, +10-20% = trail 2%, +50-100% = trail 20%, >100% = trail 25%
- **Lessons**: Read `data/lessons/` before every run. Key lessons: don't chase parabolic moves, check for pre-existing orders before placing stops, verify exit order IDs via `get_executions()`
