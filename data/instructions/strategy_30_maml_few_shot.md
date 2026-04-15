---
noteId: "a30f3c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy-30, maml, meta-learning, few-shot, neural-network]

---

# Strategy 30: Meta-Learning MAML — Few-Shot Scanner Adaptation — Operating Instructions

## Schedule

- **Base model training:** Sunday 7 PM ET via Claude Code CronCreate (`job_id = "maml_base_train"`)
- **Morning adaptation:** 9:45 AM ET one-shot run (`job_id = "maml_adapt"`)
- **Live trading:** Every 10 minutes 10:00 AM - 3:30 PM ET (`job_id = "maml_few_shot"`)
- **End-of-day summary:** 4:05 PM ET

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Minute bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="maml_few_shot")` to create a new execution record -- returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - MAML-specific: `morning_accuracy`, `adapted_model_version`, `inner_loop_loss`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` -- apply rules learned
2. **Load adapted model** (from 9:45 AM adaptation run, stored in `strategy_runs`):
   - If before 9:50 AM, model is not yet adapted -- do NOT trade, wait for adaptation
   - If adaptation failed, skip entire day
3. **Check morning accuracy gate:**
   - After the first 2 trading cycles (10:00 AM and 10:10 AM), compute accuracy of adapted model predictions
   - If morning accuracy < 40%, **SKIP THE REST OF THE DAY** -- log via `fail_job_execution(exec_id, "Morning accuracy below 40%: {accuracy}%")`
4. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Confirm no more than 3 open positions for this strategy
5. **Check current open orders** via `get_open_orders()`
6. **Verify IB connection** -- if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

**Before any new trades, enforce stops on ALL strategy-30 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="maml_few_shot", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -4%`:
   a. Check `get_open_orders()` -- skip if SELL order already exists
   b. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   c. Log with `exit_reason = "stop_loss_4pct"`
4. For each position with `pnl_pct >= +3%`:
   a. Take profit: `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   b. Log with `exit_reason = "take_profit_3pct"`
5. Call `get_closed_trades(save_to_db=True)` to reconcile with IB
6. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3A: MAML Base Model Training (Sunday 7 PM -- weekly)

**Architecture: 3-layer MLP with 128 hidden units**

```
Input (feature_dim) -> Linear(128) -> ReLU -> Linear(128) -> ReLU -> Linear(128) -> ReLU -> Linear(1) -> Sigmoid
```

**Meta-training procedure:**

1. Collect 40 trading days of data via `get_scanner_dates()` and `get_scanner_results()`
2. Each trading day = one "task" in MAML terminology
3. Per task, construct examples:
   - Features (per symbol): rank on scanner, scanner type (one-hot), time of day, price change %, volume ratio, RSI, ATR, VWAP distance, spread %, market cap tier
   - Label: 1 if forward 30-min return > 1%, else 0
4. Split each task: 5 examples = support set, 20 examples = query set
5. **MAML outer loop** (across tasks):
   - For each task (day):
     - Clone base model parameters theta
     - **Inner loop:** 3 gradient steps on support set (5 examples) with learning rate alpha=0.01
     - Evaluate adapted model on query set (20 examples)
     - Accumulate meta-gradient
   - Update base model theta with meta learning rate beta=0.001
6. Train for 100 meta-epochs, save best model by query set accuracy
7. Store base model weights in `strategy_runs` with `run_type = "maml_base_train"`
8. Log training metrics: meta-loss, mean task accuracy, best/worst task accuracy

### 3B: Morning Adaptation (9:45 AM -- daily)

1. Collect 5 support examples from 9:30-9:45 AM scanner data:
   - Call `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - Call `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - Call `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)` (all tiers)
2. For each of the 5 selected symbols:
   - Call `get_quote(symbol=SYM)` for current price, volume, bid/ask
   - Call `calculate_indicators(symbol=SYM, indicators=["RSI", "ATR", "VWAP"], duration="1 D", bar_size="1 min", tail=15)`
   - Call `get_historical_bars(symbol=SYM, duration="1 D", bar_size="1 min")` for price action
   - Construct feature vector matching training format
   - Label: 1 if price moved up since scanner appearance, 0 otherwise (using the 15-min window 9:30-9:45)
3. **Inner loop adaptation (3 gradient steps):**
   - Load base model theta from latest weekly training
   - Step 1: forward pass on 5 support examples, compute binary cross-entropy loss, gradient step (alpha=0.01)
   - Step 2: repeat on same support set with updated parameters
   - Step 3: repeat again
   - Result: adapted model theta' for today's market regime
4. Store adapted model in `strategy_runs` with `run_type = "maml_daily_adapt"`, `morning_support_symbols`, `inner_loop_losses`

### 3C: Live Feature Collection (every 10-min run)

1. Pull current scanner results for momentum scanners:
   - `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByPrice", date="YYYY-MM-DD", top_n=20)` (all tiers)
2. For each unique symbol on a momentum scanner (GainSinceOpen, TopGainers, HotByPrice):
   - Call `get_quote(symbol=SYM)` for current price, bid, ask, volume
   - Call `calculate_indicators(symbol=SYM, indicators=["RSI", "ATR", "VWAP"], duration="1 D", bar_size="1 min", tail=20)`
   - Construct feature vector: rank, scanner_type_onehot, time_of_day, price_change_pct, volume_ratio, RSI, ATR, vwap_distance, spread_pct, cap_tier

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Adapted Model Scoring

For each candidate from Phase 3C:

1. **Forward pass** through adapted model theta':
   - Input: feature vector (constructed in Phase 3C)
   - Output: `prob` (sigmoid output, 0.0 to 1.0) -- predicted probability of > 1% forward return
2. **Entry criteria (ALL must be met):**

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Model probability | >= 0.65 | High confidence from adapted model |
| On momentum scanner | Required | Must be on GainSinceOpen, TopGainers, or HotByPrice |
| Volume confirmed | Required | Must also appear on HotByVolume or volume > 1.5x average |
| Morning accuracy | >= 40% | Day-level gate (checked in Phase 1) |
| RSI | 30-75 | Not extremely overbought |

3. **Reject if:**
   - `prob < 0.65` -- insufficient model confidence
   - Not on a momentum scanner -- strategy requires momentum context
   - No volume confirmation -- momentum without volume is unreliable
   - On any loss scanner (LossSinceOpen, TopLosers) -- contradictory signal

### Morning Accuracy Tracking

- After cycles at 10:00 AM and 10:10 AM, check predictions made in first 2 cycles:
  - For each prediction with `prob >= 0.65` made at 10:00 AM, check actual 10-min return by 10:10 AM
  - `morning_accuracy = correct_predictions / total_predictions`
  - If `morning_accuracy < 0.40`, log to `strategy_runs` and STOP TRADING for the day
  - This is the few-shot validation: if the adapted model is wrong on early signals, today's regime doesn't match

### Candidate Ranking

Rank by `prob` descending. Enter highest probability first, up to max 3 positions.

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Pre-Order Quality Checks (MANDATORY)

For each qualifying candidate, run via `get_quote(symbol=SYM)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume today >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Max positions:** 3 open positions maximum for this strategy
6. **Not already held:** Check `get_positions()` for existing position
7. **Time gate:** Current time before 3:15 PM ET
8. **Morning gate passed:** Confirm morning accuracy >= 40% (or not yet evaluated if before 10:20 AM)

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

- **Fixed allocation:** 1% of account per position
- No scaling by probability -- all qualifying trades get equal size
- Calculate quantity: `qty = floor(account_value * 0.01 / last_price)`

### Order Placement

1. Call `get_quote(symbol=SYM)` for current price
2. Entry order: `place_order(symbol=SYM, action="BUY", quantity=qty, order_type="MKT")`
3. Stop loss (4% below entry): `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="STP", stop_price=round(last_price * 0.96, 2))`
4. Take profit (3% above entry): `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="LMT", limit_price=round(last_price * 1.03, 2))`

### Database Logging

For EVERY order placed, log to:
1. **`scanner_picks`:** symbol, scanner, rank, model_probability, morning_accuracy, volume_confirmed, strategy_id="maml_few_shot"
2. **`orders`:** symbol, action, quantity, order_type, order_id, limit_price, stop_price, strategy_id="maml_few_shot"
3. **`strategy_positions`:** strategy_id="maml_few_shot", symbol, entry_price, stop_price, target_price, model_probability, adapted_model_version, scanners_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-30 position, every 10-min cycle:

1. Call `get_quote(symbol=SYM)` for current bid/ask/last/volume
2. Log to `price_snapshots`: bid, ask, last, volume, unrealized P&L, distance to stop, distance to target
3. **Re-score with adapted model:**
   - Reconstruct current feature vector
   - Forward pass through theta' to get updated `prob`
   - Store in `price_snapshots` metadata
   - If `prob` drops below 0.40, consider early exit (model no longer confident)
4. **Dynamic stop management:**
   - If unrealized P&L > 1.5%, trail stop to breakeven: `modify_order(order_id=STOP_ID, stop_price=entry_price)`
   - If unrealized P&L > 2.5%, trail stop to +1%: `modify_order(order_id=STOP_ID, stop_price=round(entry_price * 1.01, 2))`
5. **Volume fade detection:**
   - Call `get_historical_bars(symbol=SYM, duration="1 D", bar_size="1 min")` -- check last 5 bars
   - If volume declining for 3+ consecutive bars while price flat, flag for potential exit
6. **Running accuracy update:**
   - Track all predictions made today, update morning_accuracy continuously
   - If cumulative accuracy drops below 35%, close all positions and stop trading

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

1. **Stop loss hit (4%):** Automatic via STP order
2. **Take profit hit (3%):** Automatic via LMT order
3. **Model confidence collapse:** If re-scored `prob` drops below 0.35, market sell
4. **Cumulative accuracy gate:** If day accuracy drops below 35%, close all positions
5. **End of day (3:30 PM):** Close all remaining positions

### Exit Execution

1. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")` (for manual exits)
2. Cancel remaining orders: `cancel_order(order_id=STOP_ORDER_ID)`, `cancel_order(order_id=TARGET_ORDER_ID)`
3. Close position in `strategy_positions`:
   - `exit_price`, `exit_reason` (stop_loss / take_profit / model_collapse / accuracy_gate / eod_close)
   - `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `entry_prob`, `exit_prob`, `morning_accuracy`
4. Log to `lessons` table:
   - Model probability at entry vs exit
   - Was the adapted model correct? (return > 1% = yes)
   - Feature importance: which features contributed most to the prediction
   - Morning accuracy at time of trade
   - Comparison: base model theta prediction vs adapted theta' prediction
   - Lesson text: what the few-shot adaptation captured or missed about today's regime
5. Compute KPIs via `compute_and_log_kpis(strategy_id="maml_few_shot")`
6. **Update morning accuracy log** in `strategy_runs` with final day accuracy

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="maml_few_shot" with:
   - Morning accuracy, cumulative accuracy, day skipped (Y/N)
   - Inner loop losses (3 steps)
   - Support set symbols and their outcomes
   - Adapted model predictions vs actuals
3. Compute `strategy_kpis` for any closed positions:
   - Win rate, avg P&L, max drawdown, Sharpe ratio, avg hold time
   - **MAML-specific KPIs:**
     - Morning accuracy distribution (histogram over past 20 days)
     - Adaptation improvement: accuracy of adapted theta' vs base theta on today's data
     - Day skip rate: % of days where morning accuracy < 40%
     - Few-shot efficiency: how much accuracy improves from 5 support examples
     - Regime detection accuracy: does skipping bad days actually improve overall performance?
4. Call `complete_job_execution(exec_id, summary)` with full run summary
5. Call `get_daily_kpis()` to compare against other strategies

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| MAML base model training | Weekly (Sunday 7 PM) | 100 meta-epochs over 40 days of tasks, 3-layer MLP (128 hidden) |
| Morning adaptation | Daily (9:45 AM) | 3 inner-loop gradient steps on 5 support examples |
| Architecture review | Monthly | Evaluate if hidden size, depth, or activation changes improve meta-learning |
| Learning rate sweep | Monthly | Grid search over alpha (inner) and beta (outer) learning rates |
| Support set size experiment | Monthly | Test 3, 5, 7, 10 support examples to find optimal few-shot size |
| Morning accuracy threshold review | Bi-weekly | Analyze if 40% threshold is too aggressive or lenient |

### MAML Base Model Training Details (Sunday)

1. Collect 40 trading days via `get_scanner_dates()`
2. For each day, build feature matrix from scanner + indicator data
3. Split: 30 days meta-train, 10 days meta-test (validation)
4. Hyperparameters:
   - Inner learning rate (alpha): 0.01
   - Outer learning rate (beta): 0.001
   - Inner steps: 3
   - Support set size: 5
   - Query set size: 20
   - Meta-batch size: 4 tasks per outer step
   - Feature dimension: ~25 (after one-hot encoding scanner types)
5. Early stopping: if meta-test accuracy does not improve for 10 epochs
6. Save model with best meta-test accuracy
7. Store in `strategy_runs` with full hyperparameters and training metrics

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Candidates with model probability and accuracy | Phase 4, 5 |
| `orders` | Entry/exit orders with full details | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle with MAML metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + re-scored probability each cycle | Phase 6 |
| `strategy_runs` | Base model weights, daily adaptation, accuracy logs | Phase 8, weekly train, daily adapt |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with model accuracy analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, adaptation improvement, day skip rate | Phase 2, 8 |

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` -- collect scanner data for training, adaptation, and live candidates
- `get_scanner_dates()` -- enumerate available dates for 40-day training window
- `get_quote(symbol)` -- current price for features, quality gate, monitoring
- `get_historical_bars(symbol, duration="1 D", bar_size="1 min")` -- intraday bars for feature engineering and volume analysis
- `calculate_indicators(symbol, indicators=["RSI", "ATR", "VWAP"], duration="1 D", bar_size="1 min", tail=20)` -- technical features for model input
- `get_positions()` -- check current portfolio
- `get_portfolio_pnl()` -- P&L monitoring and stop enforcement
- `get_open_orders()` -- prevent duplicates, verify bracket orders
- `get_closed_trades(save_to_db=True)` -- reconcile IB executions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` -- entry with bracket orders
- `cancel_order(order_id)` -- cancel stops/targets on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` -- trail stops dynamically
- `get_strategy_positions(strategy_id="maml_few_shot", status, limit)` -- query positions
- `get_strategy_kpis_report(strategy_id="maml_few_shot")` -- performance review
- `get_job_executions(job_id="maml_few_shot", limit)` -- execution history
- `get_daily_kpis()` -- cross-strategy comparison
