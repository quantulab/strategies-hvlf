---
noteId: "TODO"
tags: [cron, trading, strategies, ml, xgboost, lightgbm]

---

# Strategy 12: ML Rank Velocity Classifier — Operating Instructions

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:50 PM ET) via Claude Code CronCreate.
Model retraining runs weekly on Sundays at 6 PM ET.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Minute bars: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Historical bars via MCP: `get_historical_bars(symbol, duration, bar_size)`
- Model artifacts: `D:\src\ai\mcp\ib\data\models\rank_velocity_classifier.pkl`
- Feature scaler: `D:\src\ai\mcp\ib\data\models\rank_velocity_scaler.pkl`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_12_ml_rank_velocity")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (especially rank-based and scanner-timing lessons)
2. **Load strategy file** from `data/strategies/` — confirm strategy parameters are current
3. **Load model artifacts** — deserialize XGBoost/LightGBM classifier and feature scaler from disk
   - If model file missing or corrupted, call `fail_job_execution(exec_id, "Model artifact not found or corrupted")` and abort
   - Verify model was trained within the last 7 days (check model metadata timestamp)
4. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions with `strategy_id = "ml_rank_velocity"`
   - If already at 4 concurrent positions, skip to Phase 6 (monitoring only)
5. **Check current open orders** via `get_open_orders()` — note any pending orders for this strategy
6. **Verify IB connection** — if disconnected, log error via `fail_job_execution(exec_id, "IB gateway disconnected")` and attempt reconnect
7. **Load recent job executions** via `get_job_executions(job_id="strategy_12_ml_rank_velocity", limit=10)` to check for repeated failures
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

**Before any new trades, enforce the 3% stop-loss rule on ALL strategy_12 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="ml_rank_velocity", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -3%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol (prevents accidental shorts)
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")` to liquidate
   c. Log to `orders` table with `strategy_id = "ml_rank_velocity"`, full order details
   d. Log to `strategy_positions` — close the position with `exit_reason = "stop_loss_3pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, scanner, model probability at entry, and lesson text
   f. Compute and log KPIs for `ml_rank_velocity` via `compute_and_log_kpis`
4. For short positions (quantity < 0) that were created accidentally:
   a. Call `place_order(symbol=SYMBOL, action="BUY", quantity=abs(QTY), order_type="MKT")` to close
   b. Log with `exit_reason = "close_accidental_short"`
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. Compare current positions against positions held in the previous cycle
   c. For every position that disappeared (closed externally by stop/limit/manual):
      - Log to `lessons` table with full trade details and exit_reason
      - Log to `strategy_positions` — close with actual exit price and reason from IB
      - Log to `orders` table with exit order details
   d. This ensures NO closed trade goes unrecorded — IB is the source of truth
6. **Check 60-minute time stop**: For each open position, compute `minutes_held = now - entry_time`
   - If `minutes_held >= 60`, close position via MKT SELL
   - Log with `exit_reason = "time_stop_60min"`
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Scanner Data Collection
1. Call `get_scanner_dates()` to confirm today's date is available
2. For each scanner type in [GainSinceOpen, HotByVolume, HotByPrice, TopGainers, MostActive, TopVolumeRate]:
   - For each cap tier in [SmallCap, MidCap, LargeCap]:
     - Call `get_scanner_results(scanner="{CapTier}-{ScannerType}", date=TODAY, top_n=20)`
     - Store results with timestamp as a snapshot record
3. Maintain a rolling buffer of the last 20 snapshots (approximately 200 minutes of data at 10-min intervals)

### Feature Computation (per symbol appearing in any scanner)
For each unique symbol found across all scanners:

1. **Rank Delta Features:**
   - `rank_delta_5`: rank change over last 5 snapshots (50 min)
   - `rank_delta_10`: rank change over last 10 snapshots (100 min)
   - `rank_delta_20`: rank change over last 20 snapshots (200 min)
   - Computed as: `current_rank - rank_N_snapshots_ago` (negative = improving)

2. **First-Appearance Flag:**
   - `is_first_appearance`: 1 if symbol was NOT in any scanner in the prior snapshot, 0 otherwise
   - `minutes_since_first_seen`: time elapsed since first scanner appearance today

3. **Cross-Scanner Count:**
   - `cross_scanner_count`: number of distinct scanner types the symbol currently appears on (1-11)
   - `cross_scanner_count_delta`: change in scanner count vs prior snapshot

4. **Cap-Tier Consistency:**
   - `cap_tier_consistent`: 1 if symbol appears only in its expected cap tier, 0 if appearing across tiers
   - `primary_cap_tier`: encoded as SmallCap=0, MidCap=1, LargeCap=2

5. **Time-of-Day Bucket:**
   - `time_bucket`: categorical — "open_rush" (9:30-10:00), "morning" (10:00-11:30), "midday" (11:30-1:00), "afternoon" (1:00-3:00), "close_rush" (3:00-4:00)
   - One-hot encoded for model input

6. **Rank Stability:**
   - `rank_std_10`: standard deviation of rank over last 10 snapshots
   - `rank_mean_10`: mean rank over last 10 snapshots
   - `rank_cv_10`: coefficient of variation (std/mean)

7. **Price/Volume Features (from MCP):**
   - Call `get_quote(symbol=SYMBOL)` for current bid/ask/last/volume
   - Call `calculate_indicators(symbol=SYMBOL, indicators=["RSI","MACD","ATR"], duration="1 D", bar_size="1 min", tail=5)` for technical context
   - `spread_pct`: (ask - bid) / last
   - `volume_ratio`: current volume / avg volume

8. Assemble feature vector: `[rank_delta_5, rank_delta_10, rank_delta_20, is_first_appearance, minutes_since_first_seen, cross_scanner_count, cross_scanner_count_delta, cap_tier_consistent, primary_cap_tier, time_bucket_encoded, rank_std_10, rank_mean_10, rank_cv_10, spread_pct, volume_ratio, rsi, macd_histogram, atr]`

9. Apply saved scaler transform to normalize features

10. Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

1. **Run model prediction** on all feature vectors:
   - `probabilities = model.predict_proba(feature_matrix)[:, 1]` — probability of >2% intraday return
   - Record `predicted_probability` for each symbol

2. **Apply signal thresholds:**
   - **TRADE signal**: `predicted_probability >= 0.70`
   - **WATCH signal**: `0.50 <= predicted_probability < 0.70` — log but do not trade
   - **SKIP**: `predicted_probability < 0.50` — discard

3. **Apply mandatory filters on TRADE signals:**
   - Symbol must appear on **2+ scanners** simultaneously (`cross_scanner_count >= 2`)
   - Spread must be **< 1.5%** (`spread_pct < 0.015`)
   - If either fails, downgrade to WATCH and log rejection reason

4. **Rank candidates** by predicted probability descending

5. **Log all candidates to `scanner_picks` table:**
   - symbol, scanner (primary scanner), rank, rank_trend (rank_delta_5), conviction_score (probability * 100), conviction_tier ("tier1" if TRADE else "rejected"), scanners_present (comma-separated list), action ("BUY"), rejected flag (1 if not TRADE), reject_reason

6. Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run these checks via `get_quote(symbol=SYMBOL)`. Reject if any fail:

1. **Minimum price:** Last price >= $2.00 — reject sub-$2 stocks
2. **Minimum volume:** Current volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** (ask - bid) / last <= 1.5% — tighter than base strategy (spread < 1.5% is required by model)
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Not already held:** Check `get_positions()` — skip if already in portfolio
6. **Not already ordered:** Check `get_open_orders()` — skip if pending order exists

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **4** concurrent positions for this strategy
- **1% of account** per trade (calculate quantity from account value and current price)
- Re-entry allowed if ticker exits and reappears with fresh signal (probability >= 0.70)
- Check `get_strategy_positions(strategy_id="ml_rank_velocity", status="open")` for current count

### Order Structure
For each approved TRADE signal (in probability-descending order, up to position limit):

1. **Entry order:** Call `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
2. **Stop loss:** Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY * 0.97)` — 3% stop
3. **Take profit:** Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="LMT", limit_price=ENTRY * 1.02)` — 2% target

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, rank_trend, conviction_score (model probability), conviction_tier="tier1", scanners_present, action="BUY", rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, pick_id, strategy_id="ml_rank_velocity"
3. **`strategy_positions` table:** strategy_id="ml_rank_velocity", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, target_price, stop_order_id, target_order_id, scanners_at_entry, conviction_score, pick_id, model_probability, feature_snapshot (JSON of feature vector)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position with `strategy_id = "ml_rank_velocity"` every run:

1. Call `get_quote(symbol=SYMBOL)` to get current price data
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance_to_stop, distance_to_target
3. Update position extremes via `update_position_extremes` (peak price, trough price, MFE, MAE, drawdown_pct)
4. **Re-score with model:** Re-compute features and run inference
   - If probability drops below 0.30 while still in position, log warning (potential early exit signal)
5. **Time stop check:** If `minutes_held >= 60`, prepare exit in Phase 7
6. **Monitor for 2% target hit** — if last >= target_price, verify take-profit order is still active

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)
**Lesson: AGAE 2026-04-15 lost +26% gain, exited at -7%. This check runs EVERY cycle for EVERY open position.**

For each position, compute `unrealized_pnl_pct` from entry price, then apply:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
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

### On Exit (stop hit, target hit, time stop, or manual close)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: "stop_loss_3pct", "take_profit_2pct", "time_stop_60min", "model_degraded", "manual", "eod_close"
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="ml_rank_velocity", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - model_probability_at_entry, model_probability_at_exit
   - feature_snapshot_at_entry (JSON)
   - lesson text: analyze what the model got right/wrong
3. Compute and log KPIs for `ml_rank_velocity` via `compute_and_log_kpis`
4. If P&L < -2% or hold_duration > 55 min without hitting target, write markdown lesson to `data/lessons/`
5. **End-of-day forced close:** At 3:50 PM ET, close all remaining positions with `exit_reason = "eod_close"`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, model_signals_generated, avg_model_probability, summary
2. Log `strategy_runs` for `ml_rank_velocity` with cycle-specific metrics:
   - signals_generated, signals_traded, signals_rejected
   - avg_probability, max_probability, min_probability
   - positions_opened, positions_closed, positions_held
3. Compute `strategy_kpis` for `ml_rank_velocity` if any positions were closed:
   - win_rate, avg_win, avg_loss, profit_factor, expectancy
   - avg_hold_duration, max_drawdown
   - model_accuracy (did probability >= 0.70 actually produce >2% return?)
   - model_calibration (predicted probability vs actual hit rate)
4. Call `complete_job_execution(exec_id, summary)` with a full summary of all operations performed

---

## Model Training / Retraining Schedule

### Walk-Forward Training Protocol
- **Training window:** 30 trading days of scanner snapshots + 1-min bar data
- **Validation window:** 10 trading days (immediately following training window)
- **Test window:** 12 trading days (most recent, used for final evaluation only)
- **Retrain frequency:** Weekly on Sundays at 6 PM ET

### Training Data Preparation
1. Load scanner CSVs from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for all dates in training window
2. Load corresponding minute bars from `D:\Data\Strategies\HVLF\MinuteBars_SB`
3. For each symbol-snapshot pair, compute all 18 features listed in Phase 3
4. Label: 1 if symbol returned > 2% within 60 minutes of snapshot, 0 otherwise
5. Balance classes via SMOTE if positive class < 30%

### Model Configuration
- **Primary model:** XGBoost with `max_depth=6, n_estimators=200, learning_rate=0.05, min_child_weight=3`
- **Secondary model:** LightGBM with `num_leaves=31, n_estimators=200, learning_rate=0.05`
- **Ensemble:** Average probabilities from both models
- **Threshold tuning:** Optimize threshold on validation set to maximize precision at recall >= 0.20

### Acceptance Criteria
- Validation AUC >= 0.65
- Validation precision at threshold 0.70 >= 0.55
- If criteria not met, retain previous model and log warning

### Artifacts to Save
- `rank_velocity_classifier.pkl` — serialized ensemble model
- `rank_velocity_scaler.pkl` — fitted StandardScaler
- `rank_velocity_training_report.json` — metrics, feature importances, training dates

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate scored by model (accepted & rejected) | Phase 4, 5 |
| `orders` | Every order placed with full details | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with model probability and feature snapshot | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with P&L, model analysis, and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, drawdown, model accuracy per strategy | Phase 2, 8 |

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data is available |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect scanner snapshots for feature engineering |
| `get_quote(symbol)` | Phase 3 (features), Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, duration, bar_size)` | Phase 3 — supplementary price data for features |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | Phase 3 — RSI, MACD, ATR for feature vector |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5 — prevent duplicate orders |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2 (stop exits), Phase 5 (new entries + brackets) |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check strategy-specific positions |
| `get_strategy_kpis_report(strategy_id)` | Phase 8 — compute and review KPIs |
| `get_trading_lessons(limit)` | Phase 1 — load historical lessons |
| `get_scan_runs(limit)` | Phase 8 — log run summary |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_position_price_history(position_id)` | Phase 6 — review price trajectory |
