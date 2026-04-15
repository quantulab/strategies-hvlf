---
noteId: "s33_ensemble_voting_01"
tags: [strategy, cron, ensemble, ml, xgboost, lstm, isolation-forest, granger, monte-carlo, voting]

---

# Strategy 33: Ensemble Voting — Multi-Model Council — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:35 AM – 3:40 PM ET) via Claude Code CronCreate.
Model inference window: 9:40 AM – 2:00 PM ET (avoid first 5 min noise and last-hour volatility).
Max 3 trades per day — once limit reached, strategy enters monitor-only mode for remaining runs.

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Model artifacts: `D:\src\ai\mcp\ib\models\ensemble\` (XGBoost, LSTM, IsolationForest, Granger, MonteCarlo)
- Strategies referenced: S12 (XGBoost rank velocity), S23 (LSTM sequence), S20 (IsolationForest anomaly), S27 (Granger causality), S29 (Monte Carlo simulation)
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_33_ensemble_voting")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1–8)
   - Operation counts: `positions_checked`, `losers_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Model-specific: `models_agreeing`, `veto_triggered`, `consensus_confidence`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply ensemble-specific rules (model disagreement patterns, veto history)
2. **Load strategy files** — this strategy (S33) plus S12, S20, S23, S27, S29 (component models), S04 (cut losers), S07 (conflict filter)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()`
5. **Count S33 trades today** via `get_strategy_positions(strategy_id="ensemble_voting", status="all")` filtered by today's date — enforce max 3/day
6. **Count open S33 positions** — no explicit concurrent limit beyond the 3/day cap, but total account exposure applies
7. **Verify IB connection** — if `get_positions()` fails, call `fail_job_execution(exec_id, "IB disconnected")` and abort
8. **Verify model health:** Check that all 5 model artifact files exist and were updated within the last 7 days. If any model is stale, log warning but continue with remaining models (minimum 4 required).
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs BEFORE any new trades)

1. Call `get_portfolio_pnl()` for current P&L across all positions
2. For each open S33 position, determine stop level:
   - The stop is the **tightest** stop recommended by any of the 5 component models at entry time (stored in `strategy_positions.metadata`)
   - Typically ranges from 1.5% to 3% depending on model consensus
3. For each S33 position at or beyond its stop:
   a. Check `get_open_orders()` — skip if SELL order already exists
   b. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "ensemble_voting"`
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_model_tightest"`
   e. Log to `lessons`: which model's stop was the tightest, whether the other models would have survived
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` — sync IB executions with DB
   b. Cross-check `get_strategy_positions(strategy_id="ensemble_voting", status="open")` against `get_positions()`
   c. Close any DB positions whose symbol is no longer held in IB
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Step 1: Candidate Universe

1. Pull scanner results across all types and cap tiers:
   - Call `get_scanner_results(scanner=type, date="today", top_n=20)` for each of: GainSinceOpen, HotByVolume, HotByPrice, HotByPriceRange, TopGainers, TopVolumeRate, MostActive, HighOpenGap
2. Build unique symbol list — any symbol appearing on 2+ scanners is a candidate
3. For each candidate, record which scanners it appears on, its rank on each, and the cap tier

### Step 2: Per-Candidate Feature Collection

For each candidate symbol, gather the feature set required by all 5 models:

| Feature Group | Source | Tools |
|---------------|--------|-------|
| Scanner ranks (11 scanners × current) | Scanner CSVs | `get_scanner_results` |
| Scanner rank trajectory (last 5 snapshots) | Scanner tracking history | `get_scan_runs` |
| Price & volume bars (1-min, last 60 min) | Bar data | `get_historical_bars(symbol, duration="3600 S", bar_size="1 min")` |
| Technical indicators (RSI, MACD, VWAP, BB) | Calculated | `calculate_indicators(symbol, indicators=["RSI","MACD","VWAP","BollingerBands"], duration="1 D", bar_size="1 min", tail=60)` |
| Current quote (bid, ask, last, volume) | Real-time | `get_quote(symbol)` |
| News sentiment (last 2 hours) | News feed | `get_news_headlines(symbol, start="-2h", max_results=5)` |
| Spread & liquidity | Quote data | Derived from `get_quote` |

### Step 3: Feature Matrix Construction

Build a unified feature matrix per candidate for all 5 models:

- **XGBoost (S12):** rank_delta_5, rank_delta_10, first_appearance_flag, cross_scanner_count, cap_tier_consistency, time_of_day_bucket, rank_stability
- **LSTM (S23):** sequence of last 30 1-min bars (OHLCV) + scanner rank sequence (30 timesteps × 11 scanners)
- **IsolationForest (S20):** volume_ratio, price_change_pct, scanner_count, rank_velocity, spread_pct, sector_relative_strength — looking for anomalous positive outliers
- **Granger (S27):** lagged scanner rank series → price return series — does scanner rank Granger-cause price movement?
- **MonteCarlo (S29):** current price, historical volatility (20-day), drift estimate, 10,000 simulated 30-min paths → probability of +2% move

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Step 1: Run All 5 Models Simultaneously

For each candidate, obtain predictions from all 5 models:

| Model | Output | Confidence Scale |
|-------|--------|-----------------|
| **XGBoost (S12)** | BUY/SKIP + probability | 0.0–1.0 (probability of +2% in 60 min) |
| **LSTM (S23)** | BUY/SKIP + predicted return + confidence | 0.0–1.0 (based on validation accuracy) |
| **IsolationForest (S20)** | ANOMALY/NORMAL + anomaly score | 0.0–1.0 (higher = more anomalous = more interesting) |
| **Granger (S27)** | CAUSAL/NOT + p-value | Confidence = 1 - p_value |
| **MonteCarlo (S29)** | BUY/SKIP + probability of +2% | 0.0–1.0 (fraction of simulated paths hitting +2%) |

Map each model's output to a **vote**: BUY (1) or SKIP (0), plus a **confidence** (0.0–1.0).

### Step 2: Consensus Logic

```
votes_buy = count of models voting BUY
votes_skip = count of models voting SKIP
avg_confidence = mean confidence of BUY-voting models
min_confidence = min confidence of BUY-voting models
dissenter_max_confidence = max confidence among SKIP-voting models
```

**Decision rules:**

| Condition | Action | Rationale |
|-----------|--------|-----------|
| votes_buy >= 4 AND dissenter_max_confidence <= 0.8 | **TRADE** | Strong consensus, no high-conviction dissent |
| votes_buy >= 4 AND dissenter_max_confidence > 0.8 | **VETO — NO TRADE** | One model is screaming danger |
| votes_buy == 5 (unanimous) | **TRADE — FULL SIZE** | Maximum conviction |
| votes_buy == 3 | **NO TRADE** | Insufficient consensus |
| votes_buy <= 2 | **NO TRADE** | Clear rejection |

### Step 3: Size Determination

| Consensus | Avg Confidence | Position Size (% of account) |
|-----------|---------------|------------------------------|
| 4/5 agree | < 0.6 (low) | 0.5% |
| 4/5 agree | >= 0.6 (high) | 1.0% |
| 5/5 unanimous | any | 2.0% |

### Step 4: Stop Determination

- Collect the recommended stop distance from each BUY-voting model
- Use the **tightest (smallest distance)** as the active stop
- Example: XGBoost says 3%, LSTM says 2.5%, Granger says 2%, MonteCarlo says 3.5% → use 2% stop
- Store all model stops in `strategy_positions.metadata` for post-trade analysis

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N, models_agreeing=N, veto_triggered=BOOL, consensus_confidence=AVG)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, run these checks. Reject if any fail:

1. **Minimum price:** `get_quote(symbol)` → last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Daily trade limit:** S33 trades today < 3
6. **No duplicate:** Symbol not in `get_positions()` or `get_open_orders()`
7. **Time window:** Current time between 9:40 AM and 2:00 PM ET
8. **Account exposure:** Total S33 exposure < 4% of account

Log rejections to `scanner_picks` with `rejected = 1`, `reject_reason`, and model vote details.

### Order Placement

For each approved candidate:

1. **Calculate shares:** `floor(account_value * size_pct / ask_price)` where size_pct is from Phase 4 Step 3
2. **Entry order:** `place_order(symbol, action="BUY", quantity=shares, order_type="MKT")`
3. **Stop loss:** `place_order(symbol, action="SELL", quantity=shares, order_type="STP", stop_price=round(entry * (1 - tightest_stop_pct), 2))`
4. **Target:** `place_order(symbol, action="SELL", quantity=shares, order_type="LMT", limit_price=round(entry * 1.03, 2))` — 3% default target, adjusted by MonteCarlo median path

### Database Logging (MANDATORY)

1. **`scanner_picks`**: symbol, scanners_present, score=votes_buy, conviction_tier (4/5-low, 4/5-high, unanimous), action="BUY", rejected=0
2. **`orders`**: symbol, action="BUY", quantity, order_type, order_id, strategy_id="ensemble_voting"
3. **`strategy_positions`**: strategy_id="ensemble_voting", symbol, action="BUY", quantity, entry_price, stop_price (tightest), target_price, metadata={model_votes, model_confidences, model_stops, size_pct, consensus_type}

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open S33 position every run:

1. **Price snapshot:** `get_quote(symbol)` → log to `price_snapshots` (bid, ask, last, volume, unrealized P&L)
2. **Re-run model inference** (lightweight — reuse cached features, update price/volume only):
   - If consensus drops from 4/5 to 3/5 or below → flag for early exit review
   - If a previously dissenting model now votes BUY with high confidence → log "late confirmation"
   - If unanimity breaks → tighten stop to breakeven if position is profitable
3. **Update position extremes:** peak price, trough price, MFE, MAE, current drawdown
4. **Trailing stop logic:** If position is up > 1.5%, move stop to breakeven (entry price)
5. **Model agreement tracking:** Log how many models still agree each cycle — store in `price_snapshots.metadata`

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)
**Lesson: AGAE 2026-04-15 lost +26% gain, exited at -7%. This check runs EVERY cycle for EVERY open position.**

For each position, compute `unrealized_pnl_pct` from entry price, then apply:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
| +20% to +50% | +10% above entry (entry × 1.10) |
| +50% to +100% | MAX(entry × 1.25, peak_price × 0.80) |
| >+100% | Trail at peak_price × 0.75 |

**Implementation (every cycle):**
1. Get quote via `get_quote` — compute unrealized P&L %
2. Determine tier-required stop level from table above
3. Call `get_open_orders` — find existing STP SELL for this symbol
4. If existing stop is BELOW tier-required level → call `modify_order` to RAISE it
5. If NO stop order exists → place new GTC STP SELL at tier-required level
6. Stops only ratchet UP, never down
7. Log adjustment to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=6, positions_monitored=N, snapshots_logged=N)`

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers (in priority order)

| Trigger | Action | Exit Reason |
|---------|--------|-------------|
| Stop price hit (tightest model stop) | Automatic (STP order fills) | `stop_loss_model_tightest` |
| Target price hit | Automatic (LMT order fills) | `take_profit_target` |
| Model consensus drops to <= 2/5 during monitoring | MKT SELL | `model_consensus_lost` |
| Veto model flips to SKIP with confidence > 0.8 | MKT SELL | `high_confidence_veto_during_hold` |
| End of day (3:45 PM) | MKT SELL | `eod_close` |

### For Each Exit

1. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")` if not already filled
2. Cancel remaining open orders for this symbol via `cancel_order(order_id)`
3. Close position in `strategy_positions`:
   - exit_price, exit_reason, pnl, pnl_pct, hold_duration_minutes
4. Log to `lessons` table with full ensemble detail:
   - Which models voted BUY at entry, their confidences
   - Which model's stop was used
   - How model consensus evolved during the hold
   - Whether the veto model (if any) was correct
   - Lesson text examples:
     - "Unanimous consensus on {symbol} yielded {pnl_pct}%. All 5 models confirmed."
     - "4/5 consensus on {symbol} with IsolationForest dissenting at 0.85 confidence. Veto was correct — lost {pnl_pct}%."
     - "XGBoost and Granger agreed, LSTM dissented. LSTM was right — sequence pattern showed reversal."
5. Compute KPIs via `get_strategy_kpis_report(strategy_id="ensemble_voting")`

### Per-Model Tracking (for retraining)

For each closed trade, log individual model accuracy:
- model_name, voted_buy (bool), confidence, would_have_been_right (bool based on actual P&L)
- This feeds the model retraining pipeline to identify which models are degrading

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

1. Log `scan_runs`: candidates_found, candidates_rejected (by consensus), candidates_rejected (by veto), orders_placed, positions_held
2. Log `strategy_runs` for strategy_id="ensemble_voting"
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="ensemble_voting")`:
   - Overall win rate (target: >60%)
   - Win rate by consensus type: 4/5-low, 4/5-high, 5/5-unanimous
   - Veto accuracy: % of vetoes that would have been losers
   - Per-model accuracy: which model is most often correct
   - Avg P&L by size tier (0.5%, 1%, 2%)
   - Avg hold duration
4. Call `complete_job_execution(exec_id, summary)` with:
   - Models run, candidates screened, consensus results
   - Trades entered/exited this cycle
   - Current open S33 positions and unrealized P&L
   - Daily S33 trade count (of max 3)

---

## Model Training / Retraining Schedule

### Component Model Retraining

| Model | Retrain Frequency | Data Window | Method |
|-------|-------------------|-------------|--------|
| XGBoost (S12) | Weekly (Sunday) | Rolling 40 trading days | Walk-forward, Optuna hyperparameter search (200 trials) |
| LSTM (S23) | Bi-weekly (Sunday) | Rolling 60 trading days | Walk-forward, early stopping on validation loss |
| IsolationForest (S20) | Weekly (Sunday) | Rolling 30 trading days | Refit contamination parameter based on recent anomaly rate |
| Granger (S27) | Weekly (Sunday) | Rolling 20 trading days | Re-estimate VAR lag order, recompute p-values |
| MonteCarlo (S29) | Daily (pre-market) | Rolling 20 trading days | Update drift and volatility parameters from recent bars |

### Ensemble Weight Calibration

- Every 2 weeks, review per-model accuracy from `lessons` table
- If any model's accuracy drops below 45% over 20+ trades, reduce its vote weight (or temporarily exclude)
- If any model's accuracy exceeds 65%, consider giving it 1.5x vote weight
- Log weight changes to `strategy_runs.metadata`

### Shadow Mode Protocol

When adding a new component model or after retraining:
1. Run the updated model in shadow mode for 5 trading days
2. Log shadow predictions alongside live predictions in `strategy_runs.metadata`
3. Compare shadow model accuracy to live model
4. Only promote to live if shadow accuracy >= live accuracy - 5%

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with model votes (accepted & rejected) | Phase 4, 5 |
| `orders` | Every entry/exit order | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle + model metadata | Phase 5, 6, 7 |
| `price_snapshots` | Price + model agreement history per position per cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with model stats | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with per-model analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, per-model accuracy, consensus-type breakdown | Phase 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_results` | 3 | Pull all scanner types for candidate universe |
| `get_scanner_dates` | 3 | Verify scanner data available for today |
| `get_quote` | 3, 5, 6, 7 | Real-time price for features, execution, monitoring |
| `get_historical_bars` | 3 | 1-min bars for LSTM sequence, volatility estimation |
| `calculate_indicators` | 3 | RSI, MACD, VWAP, Bollinger Bands for feature matrix |
| `get_news_headlines` | 3 | News sentiment feature for model input |
| `get_news_article` | 3 | Full article text when headline is ambiguous |
| `get_contract_details` | 5 | Validate security type |
| `get_positions` | 1, 5 | Current portfolio positions |
| `get_portfolio_pnl` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders` | 1, 2, 5 | Duplicate/existing order check |
| `get_closed_trades` | 2 | Reconcile IB executions with DB |
| `place_order` | 2, 5, 7 | Entry, stop, target, and exit orders |
| `cancel_order` | 7 | Cancel remaining orders after exit |
| `modify_order` | 6 | Move stop to breakeven on trailing stop |
| `get_strategy_positions` | 1, 2, 7 | Count open/daily S33 positions |
| `get_strategy_kpis_report` | 2, 8 | Compute and review strategy KPIs |
| `get_trading_picks` | 1 | Review recent picks for dedup |
| `get_trading_orders` | 1 | Review recent orders |
| `get_trading_lessons` | 1 | Load lessons for rule application |
| `get_scan_runs` | 8 | Log scan cycle summary |
| `get_job_executions` | 0 | Track job execution lifecycle |
| `get_daily_kpis` | 8 | Daily aggregate performance |
| `get_position_price_history` | 6 | Review price trajectory for model re-inference |
