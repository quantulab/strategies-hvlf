---
noteId: "02a1b95039d011f19da93711749444a5"
tags: []

---

# Rotation Strategies Engine — Instruction File

**Engine:** Rotation scanner pattern strategies (S31-S37)
**Database:** `rotation_scanner.db` (separate from trading.db)
**Scanner Path:** `//Station001/DATA/hvlf/rotating` (33 feeds: 11 types x 3 cap tiers)
**Strategy Files:** `data/strategies/rotation/strategy_*.md`
**Schedule:** Every 10 minutes via `/loop 10m /run-rotation-strategies`

---

## Parallel Engine Coordination (MANDATORY)

This engine runs alongside the Core Scanner Engine and ML Engine. These rules prevent overlap:

### Position Limits
- **Max 5 rotation positions** when running in parallel mode (max 1 per sub-strategy)
- Combined with core/ML engine: max 10 total positions across all engines
- Max 2 new entries per 10-minute cycle

### Symbol Lock (BEFORE every BUY)
1. Call `get_positions()` from IB — this returns ALL positions across all engines
2. If the candidate symbol is already held by ANY engine, **SKIP** — do not enter
3. Call `get_open_orders()` — if a BUY order already exists for this symbol, **SKIP**
4. This prevents duplicate positions and accidental double-ups

### Position Ownership
- ALL rotation positions are tracked in `rotation_scanner.db.strategy_positions`
- Strategy IDs: `rotation_volume_surge`, `rotation_streak_continuation`, `rotation_whipsaw_fade`, `rotation_premarket_persist`, `rotation_capsize_breakout`, `rotation_elite_accumulation`
- Phase 2 risk management only acts on positions tracked in rotation_scanner.db
- Do NOT close positions owned by the core engine or ML engine

### IB is Source of Truth
- Always use `get_positions()` for real-time position count before entry decisions
- Database tables may be stale — IB reflects all engines' actions immediately

---

## Sub-Strategies

| Sub-Strategy | ID | File | Time Window | Max Hold |
|---|---|---|---|---|
| S32 Volume Surge | `rotation_volume_surge` | `strategy_32-rotation-volume_surge.md` | 10:30 AM - 2:00 PM | 180 min |
| S33 Streak Continuation | `rotation_streak_continuation` | `strategy_33-rotation-streak_continuation.md` | 10:30 AM - 2:00 PM | Multi-day |
| S34 Whipsaw Fade | `rotation_whipsaw_fade` | `strategy_34-rotation-whipsaw_fade.md` | 10:30 AM - 2:00 PM (stop at 2pm) | Same day |
| S35 Pre-Market Persist | `rotation_premarket_persist` | `strategy_35-rotation-premarket_persist.md` | 9:35 - 10:00 AM only | Same day |
| S36 Cap-Size Breakout | `rotation_capsize_breakout` | `strategy_36-rotation-capsize_breakout.md` | 10:30 AM - 2:00 PM | Multi-day |
| S37 Elite Accumulation | `rotation_elite_accumulation` | `strategy_37-rotation-elite_accumulation.md` | 9:45 AM - 2:00 PM | Multi-day |

---

## 8-Phase Cycle

### PHASE 0: Job Execution Tracking

- Call `start_job_execution(job_id="rotation_strategies_engine")` — log to rotation_scanner.db
- Log phase progress with `update_job_execution()` after each phase

### PHASE 1: HMM Regime Detection (Master S31)

Read `data/strategies/rotation/strategy_31_rotation_scanner_patterns.md`

1. Call `get_scanner_results(scanner="all", path="//Station001/DATA/hvlf/rotating")` to get all 33 feeds
2. Count unique tickers on gain vs loss scanners → compute breadth and G/L ratio
3. Call `classify_market_regime(method="hmm", breadth=N, gl_ratio=X, volume_level=Y)`
4. Route to sub-strategies based on HMM regime:

| Regime | Priority Sub-Strategies | Deprioritize |
|--------|------------------------|--------------|
| `bull_momentum` | streak_continuation, volume_surge, elite_accumulation | whipsaw_fade |
| `bear_mean_reversion` | whipsaw_fade, premarket_persist | streak_continuation, elite_accumulation |
| `range_bound` | whipsaw_fade, premarket_persist, volume_surge | streak_continuation |

### PHASE 2: Risk Management — Cut Rotation Losers

**Only act on rotation-owned positions** (tracked in rotation_scanner.db):

1. Call `get_portfolio_pnl()` — for each rotation position losing > -5%, place MKT SELL
2. Check `get_open_orders()` BEFORE placing any SELL (prevent accidental shorts)
3. Call `get_closed_trades(save_to_db=True)` to reconcile fills
4. For each open rotation position, check scanner presence:
   - If disappeared from ALL gain scanners for 2+ cycles → tighten stop
5. Special checks:
   - S34 whipsaw shorts: should have been closed EOD — if any remain, close immediately
   - S33 streaks: check if streak is still active on today's scanners
   - S36 capsize: check if still on upgraded cap tier
   - S37 elite: check if still top-5 on gain scanners

### PHASE 3: Scanner Data Collection

1. Call `get_scanner_results(scanner="all", path="//Station001/DATA/hvlf/rotating")`
2. Parse all 33 feeds (11 scanner types x 3 cap tiers: Small, Mid, Large)
3. Build symbol profiles: which scanners, rank, cap tier, trend
4. Cross-reference with rotation_scanner.db tracking tables:
   - `whipsaw_watchlist` — known whipsaw tickers
   - `volume_lead_signals` — volume-before-price events
   - `streak_tracker` — multi-day streak counts
   - `capsize_crossovers` — cap-tier transition history

### PHASE 4: Execute Sub-Strategies with ML Enhancements

Execute each sub-strategy per its file in `data/strategies/rotation/`. For EACH, apply ML enhancements:

#### S32 Volume Surge
- Scan volume scanners for symbols NOT yet on gain/loss scanners
- `forecast_volume_trajectory(symbol)` — skip if volume_trend="falling"
- `get_sentiment_gate(symbol)` — +1 conviction if approve
- `classify_catalyst_topic(headline)` — +1 if fundamental catalyst

#### S33 Streak Continuation
- Detect multi-day streaks (day 3+ on same gain scanner)
- `compute_hurst_exponent(symbol, duration="20 D")` — skip if H < 0.45
- `forecast_scanner_rank(symbol, scanner, multi_day=True)` — skip if rank predicted to worsen
- Hurst > 0.55 = +2 conviction

#### S34 Whipsaw Fade
- **Stop accepting new entries after 2:00 PM ET**
- `compute_return_autocorrelation(symbol, duration="5 D")` — if ALL > 0.1, disable fades
- `classify_catalyst_topic(headline)` — if fundamental catalyst, -3 conviction
- Autocorrelation < -0.1 = +2 conviction

#### S35 Pre-Market Persistence
- **Entry window: 9:35-10:00 AM ET ONLY**
- `classify_catalyst_topic(headline)` — earnings/upgrade = +2, no news + whipsaw = -2
- `get_sentiment_gate(symbol)` — +1 if approve

#### S36 Cap-Size Breakout
- Detect cap-tier upgrades (Small→Mid, Mid→Large)
- `classify_catalyst_topic(headline)` — fundamental catalyst = +2
- `forecast_volume_trajectory(symbol)` — volume rising = +1
- ETF rebalancing/structural crossover (no catalyst) = -2

#### S37 Elite Accumulation
- **Start at 9:45 AM** (VWAP needs time)
- `forecast_scanner_rank(symbol, scanner, multi_day=True)` — skip if rank predicted to exit top-5
- `get_sentiment_gate(symbol)` — +2 if approve
- `classify_catalyst_topic(headline)` — analyst upgrade/13F = +1

### Universal ML Conviction Modifiers

Apply to EVERY candidate across all sub-strategies:

| Factor | Points | Tool |
|--------|--------|------|
| Sentiment gate approves | +2 | `get_sentiment_gate(symbol)` |
| Sentiment gate rejects (avg < -0.3) | -1 | `get_sentiment_gate(symbol)` |
| Catalyst is fundamental | +1 | `classify_catalyst_topic(headline)` |
| HMM regime matches sub-strategy | +1 | Sub-strategy in HMM priority list |
| HMM regime deprioritizes sub-strategy | -2 | Sub-strategy NOT in priority list |

Only trade **Tier 1 (score 5+)**. Log all ML signals to `scanner_picks` with ML columns.

**ML tools are modifiers, not gates**: If any ML tool fails, score unchanged. No ML failure blocks a trade.

### PHASE 5: Order Execution

#### Quality Gates (same as core engine)
1. **Minimum price:** >= $2.00
2. **Minimum volume:** >= 50,000 shares
3. **Maximum spread:** <= 3%
4. **No warrants/units:** R, W, WS, U suffixes
5. **Extended move filter:** Reject if >100% gain from prior close
6. **Volume confirmation:** Volume > 2x avg OR HotByVolume rank <= 4
7. **Price action:** `(last - low) / (high - low)` >= 0.50
8. **$10-$20 rejection:** Reject unless catalyst confirmed
9. **$2-$5 priority:** Prioritize when multiple candidates qualify

#### Symbol Lock Check (MANDATORY)
Before placing ANY order:
1. `get_positions()` — if symbol already held by ANY engine, SKIP
2. `get_open_orders()` — if BUY already pending for symbol, SKIP

#### Order Structure
- Entry: MKT BUY (or sub-strategy-specific entry type)
- Stop: Sub-strategy-specific % (STP order, GTC)
- Take Profit: **NO fixed LMT** — use trailing stop ratchet in Phase 6
- Log to rotation_scanner.db with `sub_strategy` and `ml_signals` fields

### PHASE 6: Position Monitoring & Trailing Stop Ratchet

For each open rotation position every cycle:
1. Get current quote via `get_quote`
2. Log `price_snapshots` to rotation_scanner.db
3. Update position extremes via `update_position_extremes`
4. Sub-strategy-specific monitoring:
   - S33: Check streak still active — if broken, exit at market
   - S36: Check cap tier — if reverted, tighten stop
   - S37: Check top-5 rank — if dropped, tighten stop

#### Profit Protection Tiers (MANDATORY — same as all engines)

| Unrealized Gain | Required Stop Level | Action |
|-----------------|---------------------|--------|
| +5% to +10% | Breakeven (entry price) | Move stop to entry. Lock in zero-loss. |
| +10% to +20% | Trail 2% below current price | Stop = current_price x 0.98. |
| +20% to +50% | MAX(trail 2% below current, +10% above entry) | Never give back below +10%. |
| +50%+ | Trail 3% below peak | Stop = peak_price x 0.97. |

### PHASE 7: Exit Handling & Lessons

On exit:
1. Close position in rotation_scanner.db `strategy_positions`
2. Log to `lessons` table with full trade details + ML signals + sub-strategy
3. Compute KPIs per sub-strategy

### PHASE 8: Run Summary

1. Log `scan_runs` and `strategy_runs` to rotation_scanner.db
2. Call `complete_job_execution(exec_id, summary)`
3. Report: regime, sub-strategies active, candidates scored, ML modifiers applied, orders placed, P&L

---

## End-of-Day Rules

At 3:30 PM ET:
- Close ALL S34 whipsaw fade positions (same-day only)
- Assess S33/S36/S37 multi-day positions for overnight gap risk
- Tighten stops on any position up >20% intraday
- Close leveraged ETF positions (decay risk)
- Run lesson generation for significant trades
- Delete the cron job (re-created next day by `/start-ml-trading-day`)
