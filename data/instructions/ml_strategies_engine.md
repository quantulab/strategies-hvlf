---
noteId: "e28fe29039cf11f19da93711749444a5"
tags: []

---

# ML Strategies Engine — Instruction File

**Engine:** ML-enhanced trading strategies (S12-S30)
**Database:** `trading.db` (shared with core engine)
**Scanner Path:** `//Station001/DATA/hvlf/scanner-monitor` (10 legacy scanners)
**Strategy Files:** `data/strategies/ml/strategy_*.md`
**Schedule:** Every 10 minutes via `/loop 10m /run-ml-strategies`

---

## Parallel Engine Coordination (MANDATORY)

This engine runs alongside the Core Scanner Engine and Rotation Engine. These rules prevent overlap:

### Position Limits
- **Max 5 ML positions** when running in parallel mode
- Combined with core engine: max 10 total positions across all engines
- Max 2 new entries per 10-minute cycle

### Symbol Lock (BEFORE every BUY)
1. Call `get_positions()` from IB — this returns ALL positions across all engines
2. If the candidate symbol is already held by ANY engine, **SKIP** — do not enter
3. Call `get_open_orders()` — if a BUY order already exists for this symbol, **SKIP**
4. This prevents duplicate positions and accidental double-ups

### Position Ownership
- ALL ML positions are tracked in `trading.db.strategy_positions` with `strategy_id` prefixed `ml_` (e.g., `ml_rank_velocity`, `ml_sentiment_proxy`)
- Phase 2 risk management only acts on positions where `strategy_id LIKE 'ml_%'` in trading.db
- Do NOT close positions owned by the core engine or rotation engine

### IB is Source of Truth
- Always use `get_positions()` for real-time position count
- Database tables may be stale — IB reflects all engines' actions immediately

---

## Active Strategies

Read each strategy file from `data/strategies/ml/` for detailed rules. Key strategies:

| Strategy | ID | Stop | Target | Max Hold | Notes |
|----------|-----|------|--------|----------|-------|
| S12 ML Rank Velocity | `ml_rank_velocity` | 3% | 2% | 60 min | XGBoost on rank features |
| S14 News Sentiment | `ml_sentiment_proxy` | 8% | 15% | 390 min | LLM headline scoring |
| S15 HMM Regime | `ml_regime_detector` | 5% | 3% | 240 min | Regime-conditional entries |
| S17 Transformer | `ml_transformer` | 4% | 3% | 240 min | Sequence model on rank trajectory |
| S19 Bandit Scanner | `ml_bandit` | 5% | 3% | 240 min | Multi-armed bandit scanner selection |
| S20 Anomaly Detection | `ml_anomaly` | 4% | 3% | 60 min | Isolation forest on scanner features |
| S23 LSTM Rank Forecast | `ml_lstm` | 5% | 3% | 45 min | LSTM on rank time series |
| S28 Sentiment Composite | `ml_sentiment_composite` | 7% | 5% | 240 min | Multi-source sentiment |
| S29 Monte Carlo | `ml_monte_carlo` | 4% | 2.5% | 60 min | Simulation-based targets |
| S30 MAML Few-Shot | `ml_maml` | 4% | 3% | 240 min | Few-shot adaptation |

---

## 8-Phase Cycle

### PHASE 0: Job Execution Tracking

- Call `start_job_execution(job_id="ml_strategies_engine")` to create execution record
- Log phase progress with `update_job_execution()` after each phase

### PHASE 1: Pre-Trade Checklist

1. Read ALL files in `data/lessons/` — apply hard rules from past trades
2. Read ALL strategy files in `data/strategies/ml/`
3. Call `ensure_connected()` to verify IB connection
4. Call `get_positions()` to load current state (ALL engines)
5. Call `get_open_orders()` to check for pending orders
6. Count ML-owned positions: query `strategy_positions WHERE strategy_id LIKE 'ml_%' AND status='open'`
7. If ML position count >= 5, skip to Phase 6 (monitoring only)

### PHASE 2: Risk Management — Cut ML Losers

**Only act on ML-owned positions** (strategy_id LIKE 'ml_%' in trading.db):

1. Call `get_portfolio_pnl()` — for each ML position losing > -5%, place MKT SELL
2. Check `get_open_orders()` BEFORE placing any SELL (prevent accidental shorts)
3. Call `get_closed_trades(save_to_db=True)` to reconcile any fills since last cycle
4. Update `strategy_positions` for any closed ML positions

### PHASE 3: Scanner Analysis & Feature Engineering

1. Read scanner files from `//Station001/DATA/hvlf/scanner-monitor/{YYYYMMDD}/`
2. Parse all 10 scanner feeds (same as core engine)
3. For each candidate, compute ML features:
   - Rank history (last 20 snapshots)
   - Rank velocity (rate of improvement)
   - Scanner breadth (how many scanners present)
   - Volume ratio vs average
   - Price position in intraday range

### PHASE 4: ML Model Inference & Signal Generation

For each candidate from Phase 3:
1. Run the appropriate ML model per strategy file
2. Apply model probability threshold (typically >= 0.70)
3. Apply conviction scoring (same base as core + ML modifiers)
4. Apply scanner combo bonus: +3 for GainSinceOpenLarge + PctGainLarge
5. Apply ML-specific modifiers per strategy file

### PHASE 5: Order Execution

#### Quality Gates (same as core engine)
1. **Minimum price:** >= $2.00
2. **Minimum volume:** >= 50,000 shares
3. **Maximum spread:** <= 3%
4. **No warrants/units:** R, W, WS, U suffixes
5. **$5-$10 confirmation:** 2+ consecutive scanner runs
6. **Extended move filter:** Reject if >100% gain from prior close
7. **Volume confirmation:** Volume > 2x avg OR HotByVolume rank <= 4
8. **Price action:** `(last - low) / (high - low)` >= 0.50
9. **$10-$20 rejection:** Reject unless catalyst confirmed (6-condition check)
10. **$2-$5 priority:** Prioritize this bracket when multiple candidates qualify

#### Time-of-Day Windows
| Window | ET Time | Action |
|--------|---------|--------|
| A: Open | 9:30-10:30 | OBSERVE ONLY. No entries unless catalyst confirmed. |
| B: Prime | 10:30-12:00 | PRIMARY ENTRY WINDOW. Max 2 entries per cycle. |
| C: Midday | 12:00-14:00 | REDUCED. Only fresh Tier 1 candidates. |
| D: Late | 14:00-15:30 | NO NEW ENTRIES. Monitor only. |
| E: Close | 15:30-16:00 | EOD wrap-up. |

#### Symbol Lock Check (MANDATORY)
Before placing ANY order:
1. `get_positions()` — if symbol already held, SKIP
2. `get_open_orders()` — if BUY already pending for symbol, SKIP

#### Order Structure
- Entry: MKT BUY
- Stop: Strategy-specific % (STP order, GTC)
- Take Profit: **NO fixed LMT** — use trailing stop ratchet in Phase 6

### PHASE 6: Position Monitoring & Trailing Stop Ratchet

For each open ML position every cycle:
1. Get current quote via `get_quote`
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L
3. Update position extremes via `update_position_extremes`

#### Profit Protection Tiers (MANDATORY)

| Unrealized Gain | Required Stop Level | Action |
|-----------------|---------------------|--------|
| +5% to +10% | Breakeven (entry price) | Move stop to entry. Lock in zero-loss. |
| +10% to +20% | Trail 2% below current price | Stop = current_price x 0.98. Tight trail. |
| +20% to +50% | MAX(trail 2% below current, +10% above entry) | Never give back below +10%. |
| +50%+ | Trail 3% below peak | Stop = peak_price x 0.97. |

- Stops only ratchet UP, never down
- Use `modify_order` to raise existing stop orders
- Log adjustments with `strategy_id = "ml_profit_protection"`

### PHASE 7: Exit Handling & Lessons

On exit (stop hit, target hit, or manual close):
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details + ML signals used
3. Compute and log KPIs via `compute_and_log_kpis`

### PHASE 8: Run Summary

1. Log `strategy_runs` for each ML strategy active this cycle
2. Call `complete_job_execution(exec_id, summary)` with full summary
3. Report: candidates scored, ML models used, orders placed, positions monitored, P&L

---

## Lesson Application Rules

Before each run, read ALL lessons from `data/lessons/` and apply:

| Lesson | Rule | How to Apply |
|--------|------|-------------|
| Cut Losers Early | Hard stop at -5% | Phase 2 — mandatory |
| Scanners Show Past | Signal freshness <10 min | Reject if first seen >10 min ago |
| Protect Profits | Trailing stop ratchet | Phase 6 — all positions |
| Volume Without Direction | Never buy if on volume + loss scanner | Phase 4 veto |
| Quality Over Quantity | Max 5 positions | Phase 5 position limit |
