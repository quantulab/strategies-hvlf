---
noteId: "run_ml_strategies_01"
tags: [cron, trading, ml, rotation, scanner-patterns, enhanced]

---

Run the ML-enhanced rotation strategies engine. This executes all 6 rotation sub-strategies (S32-S37) with ML conviction modifiers, plus the master orchestrator (S31) with HMM regime detection. Uses the new ML tools: sentiment gate, Hurst exponent, autocorrelation, volume trajectory forecasting, catalyst topic classification, and HMM regime detection.

## Pre-Flight

1. Call `ensure_connected()` to verify IB connection
2. Call `get_positions()` and `get_open_orders()` to load current state
3. Check market hours — if all quotes return null, report status and skip to monitoring

## Phase 0: ML Schema Migration (first run only)

Run these ALTER TABLE statements against `rotation_scanner.db`. Ignore "duplicate column name" errors:
```sql
ALTER TABLE scanner_picks ADD COLUMN hurst_exponent REAL;
ALTER TABLE scanner_picks ADD COLUMN autocorrelation REAL;
ALTER TABLE scanner_picks ADD COLUMN sentiment_score REAL;
ALTER TABLE scanner_picks ADD COLUMN sentiment_gate TEXT;
ALTER TABLE scanner_picks ADD COLUMN catalyst_topic TEXT;
ALTER TABLE scanner_picks ADD COLUMN volume_forecast_trend TEXT;
ALTER TABLE rotation_state ADD COLUMN regime_hmm TEXT;
ALTER TABLE rotation_state ADD COLUMN regime_hmm_confidence REAL;
ALTER TABLE strategy_positions ADD COLUMN ml_signals TEXT;
```

## Phase 1: HMM Regime Detection (Master S31)

Read `data/instructions/strategy_31_rotation_scanner_patterns.md`

1. Call `get_scanner_results(scanner="all", path="//Station001/DATA/hvlf/rotating")` to get all 33 feeds
2. Count unique tickers on gain vs loss scanners to compute breadth and G/L ratio
3. Call `classify_market_regime(method="hmm", breadth=N, gl_ratio=X, volume_level=Y)` for HMM regime
4. Also call `classify_market_regime()` (zero-shot) as secondary signal
5. Route to sub-strategies based on HMM regime:
   - `bull_momentum` -> prioritize: streak_continuation, volume_surge, elite_accumulation
   - `bear_mean_reversion` -> prioritize: whipsaw_fade, premarket_persist
   - `range_bound` -> all eligible, prioritize: whipsaw_fade, premarket_persist, volume_surge

## Phase 2: Risk Management (ALL positions)

1. Call `get_portfolio_pnl()` — cut any rotation position at -5%
2. Check `get_open_orders()` before placing any SELL (prevent accidental shorts)
3. Apply profit protection ratchets: +5-10% = breakeven, +10-20% = trail 2%, +50-100% = trail 20%
4. Call `get_closed_trades(save_to_db=True)` to reconcile
5. For each open position, check scanner presence — if disappeared from ALL gain scanners for 2+ cycles, tighten stop

## Phase 3: Execute Sub-Strategies with ML Enhancements

Execute each sub-strategy per its instruction file in `data/instructions/`. For EACH, apply these ML enhancements:

### S32 Volume Surge (`strategy_32-rotation-volume_surge.md`)
- Scan Station001 volume scanners for symbols NOT on gain/loss scanners
- For candidates: call `forecast_volume_trajectory(symbol)` — skip if volume_trend="falling"
- Call `get_sentiment_gate(symbol)` — +1 conviction if approve
- Call `classify_catalyst_topic(headline)` for news-driven volume — +1 if fundamental catalyst

### S33 Streak Continuation (`strategy_33-rotation-streak_continuation.md`)
- Detect multi-day streaks (day 3+ on same gain scanner)
- Call `compute_hurst_exponent(symbol, duration="20 D")` — **skip if H < 0.45** (anti-persistent)
- Call `forecast_scanner_rank(symbol, scanner, multi_day=True)` — skip if rank predicted to worsen
- Call `get_sentiment_gate(symbol)` — +1 conviction if approve
- Hurst > 0.55 = +2 conviction

### S34 Whipsaw Fade (`strategy_34-rotation-whipsaw_fade.md`)
- **Stop after 2:00 PM ET**
- Call `compute_return_autocorrelation(symbol, duration="5 D")` on top whipsaw names
  - If ALL autocorrelation > 0.1 → DISABLE fades this cycle (trending market)
- Call `classify_catalyst_topic(headline)` — if fundamental catalyst (earnings/FDA), -3 conviction (don't fade real catalysts)
- Call `get_sentiment_gate(symbol)` — if strongly positive (avg > 0.5), -2 conviction
- Autocorrelation < -0.1 = +2 conviction

### S35 Pre-Market Persistence (`strategy_35-rotation-premarket_persist.md`)
- **Entry window: 9:35-10:00 AM only**
- Call `classify_catalyst_topic(headline)` to type the pre-market catalyst
  - Earnings/upgrade = +2 conviction (high persistence)
  - No news catalyst + MODERATE whipsaw = -2 conviction
- Call `get_sentiment_gate(symbol)` — +1 conviction if approve

### S36 Cap-Size Breakout (`strategy_36-rotation-capsize_breakout.md`)
- Detect cap-tier upgrades (Small->Mid, Mid->Large)
- Call `classify_catalyst_topic(headline)` — fundamental catalyst driving crossover = +2
- Call `get_sentiment_gate(symbol)` — +1 if approve
- Call `forecast_volume_trajectory(symbol)` — volume rising = +1
- ETF rebalancing/structural crossover (no fundamental catalyst) = -2

### S37 Elite Accumulation (`strategy_37-rotation-elite_accumulation.md`)
- **Start at 9:45 AM** (VWAP needs time)
- Call `forecast_scanner_rank(symbol, scanner, multi_day=True)` — skip if rank predicted to exit top-5
- Call `get_sentiment_gate(symbol)` — +2 conviction if approve (sustained positive sentiment)
- Call `classify_catalyst_topic(headline)` — analyst upgrade/13F topic = +1

## Phase 4: Universal ML Conviction Modifiers

Apply these to EVERY candidate across all sub-strategies before final scoring:

| Factor | Points | Tool |
|--------|--------|------|
| Sentiment gate approves | +2 | `get_sentiment_gate(symbol)` |
| Sentiment gate rejects (avg < -0.3) | -1 | `get_sentiment_gate(symbol)` |
| Catalyst is fundamental | +1 | `classify_catalyst_topic(headline)` |
| HMM regime matches sub-strategy priority | +1 | Sub-strategy in HMM `prioritize` list |
| HMM regime deprioritizes sub-strategy | -2 | Sub-strategy in HMM `deprioritize` list |

Only trade Tier 1 (score 5+). Log all ML signals to `scanner_picks` with ML columns populated.

## Phase 5: Order Execution

- Max 6 concurrent rotation positions (1 per sub-strategy)
- Max 2 new entries per cycle
- 1 share per ticker
- Quality gate: price >= $2, volume >= 50K, spread <= 3%, no warrants
- Place MKT BUY + immediate STP SELL protection
- Log `ml_signals` JSON blob to `strategy_positions`

## Phase 6: Position Monitoring

- Quote all open positions, log price_snapshots
- Apply profit protection ratchets (stops only ratchet UP)
- Sub-strategy-specific monitoring (streak breaks, rank drops, cap-tier reversion, etc.)

## Phase 7-8: Exit Handling + Summary

- Log exits to strategy_positions, lessons with full ML signal details
- Report: regime, sub-strategies active, candidates scored, ML modifiers applied, orders placed, P&L

## Key Rules

- **Scanner path**: `//Station001/DATA/hvlf/rotating` (33 feeds, pass as `path` param)
- **ML tools are modifiers, not gates**: If any ML tool fails, score unchanged — no ML failure blocks a trade
- **Graceful degradation**: If model not loaded or IB disconnected, skip ML modifiers and fall back to rule-based scoring
- **Read lessons**: Load `data/lessons/` before every run
