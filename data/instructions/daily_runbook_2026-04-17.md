---
noteId: "89dc8f3039d011f19da93711749444a5"
tags: []

---

# Daily Runbook — Thursday, April 17, 2026

**Account:** DU1918690 (Paper) | **Prior Day P&L:** +$7.02 (closed) | **Week-to-Date:** +$30.23

---

## Pre-Market Checklist (Before 9:30 AM ET)

### 1. Launch Command
```
/start-ml-trading-day
```
This starts both engines in parallel. If you only want the core engine:
```
/start-trading-day
```

### 2. What Gets Loaded Automatically
- `data/instructions/scanner_cron_job.md` — core engine (11 strategies)
- `data/instructions/ml_strategies_engine.md` — ML strategies (S12-S30)
- `data/instructions/rotation_strategies_engine.md` — rotation strategies (S31-S37)
- All files in `data/lessons/` — hard rules from past trades
- All strategy files from `data/strategies/`, `data/strategies/ml/`, `data/strategies/rotation/`

### 3. Pre-Market Verification
The startup will automatically:
- Verify IB connection via `ensure_connected()`
- Check overnight positions and P&L
- Verify stop orders survived overnight (re-place any missing at -5%)
- Check Station001 scanner data folders exist
- Run HMM regime detection for market open
- Run sentiment gate on any held positions
- Report all findings before starting cron jobs

---

## Engine Architecture

```
/start-ml-trading-day
         |
         +---> /loop 10m /run-trading-engine        (Core + ML)
         |       - scanner_cron_job.md
         |       - ml_strategies_engine.md
         |       - DB: trading.db
         |       - Scanners: scanner-monitor (10 feeds)
         |       - Max 5 positions
         |
         +---> /loop 10m /run-rotation-strategies   (Rotation)
                 - rotation_strategies_engine.md
                 - DB: rotation_scanner.db
                 - Scanners: rotating (33 feeds)
                 - Max 5 positions

         Combined: Max 10 positions, symbol lock via IB
```

---

## Today's Changes (NEW for Apr 17)

### Conviction Scoring Changes
| Change | Old | New | Why |
|--------|-----|-----|-----|
| MIN_SCORE | 5 (Tier 1 only) | 3 (Tier 2 tradeable) | Score 3 had 60% WR vs 29% at score 5 |
| Scanner combo bonus | None | +3 for GainSinceOpenLarge + PctGainLarge | 85.7% WR combo |
| $10-$20 bracket | Allowed | Rejected (unless catalyst) | 0% WR in Apr 15-16 data |
| $2-$5 bracket | No preference | Priority when multiple candidates | 71.4% WR, 109% avg return |

### Exit Strategy Changes
| Change | Old | New | Why |
|--------|-----|-----|-----|
| Take profit | Fixed 10% LMT order | Trailing stop ratchet (no LMT) | ASTI captured +145.6% vs old 10% cap |
| Profit protection +5-10% | Move stop to +10% above entry | Move stop to breakeven | Earlier protection |
| Profit protection +10-20% | Breakeven | Trail 2% below current price | Lets winners run |
| Max hold (S15,S17,S19,S30) | 120 min | 240 min | 2-4 hour holds are optimal ($4.15 avg) |

### Time-of-Day Windows
| Window | Time (ET) | Rule |
|--------|-----------|------|
| A: Open | 9:30-10:30 | OBSERVE ONLY. No entries unless catalyst confirmed. |
| B: Prime | 10:30-12:00 | PRIMARY ENTRY WINDOW. Max 2 entries per cycle. |
| C: Midday | 12:00-14:00 | REDUCED. Only fresh Tier 1 candidates. |
| D: Late | 14:00-15:30 | NO NEW ENTRIES. Monitor + protect only. |
| E: Close | 15:30-16:00 | Auto-triggers `/end-trading-day`. |

---

## Quality Gates (Applied to Every Entry)

1. Price >= $2.00
2. Volume >= 50,000 shares
3. Spread <= 3%
4. No warrants/units (R, W, WS, U suffixes)
5. $5-$10: require 2+ consecutive scanner runs
6. $10-$20: REJECT unless catalyst confirmed (6-condition check)
7. Extended move: REJECT if >100% from prior close
8. Volume confirmation: volume > 2x avg OR HotByVolume rank <= 4
9. Price action: `(last - low) / (high - low)` >= 0.50
10. $2-$5 priority: prefer this bracket when slots are limited

---

## Risk Guardrails (DO NOT CHANGE)

| Rule | Value |
|------|-------|
| Hard stop | -5% on ALL positions |
| Max positions (parallel) | 5 core + 5 rotation = 10 total |
| Max entries per cycle | 2 per engine |
| Profit protection | Trailing ratchet: +5%=breakeven, +10%=trail 2%, +20%=trail 2%/+10%, +50%=trail 3% |
| No accidental shorts | Check `get_open_orders()` before EVERY sell |
| Symbol lock | Check `get_positions()` before EVERY buy |

---

## Profit Protection Ratchet (All Engines)

| Unrealized Gain | Stop Level | Action |
|-----------------|-----------|--------|
| +5% to +10% | Breakeven (entry price) | Lock in zero-loss |
| +10% to +20% | Trail 2% below current | Stop = price x 0.98 |
| +20% to +50% | MAX(2% trail, +10% above entry) | Never give back below +10% |
| +50%+ | Trail 3% below peak | Stop = peak x 0.97 |

Stops only ratchet UP, never down. Use `modify_order` to adjust existing stops.

---

## Key Lessons to Apply Today

| # | Lesson | Source | Rule |
|---|--------|--------|------|
| 1 | AGAE: +26% reversed to -7% | Apr 15 | Trailing ratchet prevents this now |
| 2 | BIRD: +626% missed as "stale" | Apr 15 | Catalyst override (6-condition check) catches these |
| 3 | PBM: entered at +178%, stopped in 9s | Apr 16 | Extended move filter rejects >100% |
| 4 | RMSG: pre-existing order conflict | Apr 16 | Always check `get_open_orders()` before placing stops |
| 5 | 10 consecutive losses from batch entry | Apr 15 | Max 2 entries per cycle enforced |
| 6 | Sub-$2 stocks: 33% WR | Apr 15-16 | $2 minimum price gate |
| 7 | ASTI: +145.6% via trailing ratchet | Apr 16 | New exit system working — let winners run |
| 8 | STP orders going Inactive | Apr 16 | After 2 Inactive attempts, switch to trailing stop order |

---

## Rotation Sub-Strategy Schedule

| Sub-Strategy | Active Window | Regime Priority |
|---|---|---|
| S35 Pre-Market Persist | 9:35-10:00 AM | bear, range |
| S37 Elite Accumulation | 9:45 AM - 2:00 PM | bull |
| S32 Volume Surge | 10:30 AM - 2:00 PM | bull, range |
| S33 Streak Continuation | 10:30 AM - 2:00 PM | bull |
| S34 Whipsaw Fade | 10:30 AM - 2:00 PM (stop 2pm) | bear, range |
| S36 Cap-Size Breakout | 10:30 AM - 2:00 PM | bull |

---

## Monitoring Commands

| Command | What It Does |
|---------|-------------|
| `get pnl` | Current portfolio P&L (all engines) |
| `get positions` | All open positions from IB |
| `get closed pnl` | Today's closed trades with P&L |
| `get open orders` | All pending orders |
| `get daily kpis` | Full KPI dashboard for the day |

---

## End-of-Day (3:30-4:00 PM ET)

The cron job auto-triggers `/end-trading-day` which:
1. Final risk check — cut losers, apply overnight gap rules
2. Cancel unfilled/inactive orders
3. Close all S34 whipsaw positions (same-day only)
4. Assess multi-day holds (S33 streaks, S37 elite) for overnight risk
5. Full trade reconciliation
6. Daily KPI computation
7. Lesson generation for significant trades
8. Delete cron jobs (re-created tomorrow)
9. End-of-day summary report

---

## Target Metrics for Today

```
Based on Apr 15-16 data and improvements applied:

Trades:     5-10 (selective, quality over quantity)
Win Rate:   55-65% (up from 35% via better scoring + time windows)
Avg Win:    +20-50% (trailing ratchet lets winners run)
Avg Loss:   -3% to -5% (hard stops unchanged)
Net P&L:    +$10-15 target (realistic with 1-share positions)
```

---

*Generated 2026-04-16. All changes validated against Apr 15-16 performance data (48 trades, +$30.23).*
