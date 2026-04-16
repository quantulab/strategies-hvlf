---
noteId: "c9d5e3f159a033g3dd4ah819ee14i229"
tags: [cron, trading, strategies, world-model, dreamer, muzero, mpc, risk-management]

---

# Strategy 39: World Model — Scanner Dynamics Simulator — Operating Instructions

## Schedule
Runs every 5 minutes during market hours (9:35 AM – 3:55 PM ET) via Claude Code CronCreate.
Planning horizon: 50 trajectories × 10 steps × 5 min = 50-minute lookahead per cycle.
Job ID: `strategy_39_world_model`

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_39_world_model")` — returns `exec_id`
2. After each phase, call `update_job_execution(exec_id, ...)` with progress and counts
3. On completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**Additionally log: `trajectories_simulated`, `planning_time_ms`, `prediction_error` as custom fields in the summary.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned
2. **Verify world model components are loaded:**
   - **Representation network** (CNN encoder): Raw scanner/price observation → 128-dimensional latent state
   - **Transition network** (GRU): latent_state(t) + action → latent_state(t+1)
   - **Reward network** (MLP): latent_state → predicted reward (P&L for next 5-min step)
   - **Decoder network** (MLP): latent_state → predicted scanner ranks + price (for validation)
   - If any component missing, call `fail_job_execution(exec_id, "World model component missing")` and halt
3. **Check prediction accuracy buffer:**
   - Maintain a rolling buffer of last 20 predictions vs actual outcomes
   - Compute mean absolute prediction error
   - If error > 50% of actual magnitude → **HALT strategy** (see divergence rule in Phase 6)
4. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
5. **Check open orders** via `get_open_orders()`
6. **Count open strategy-39 positions** via `get_strategy_positions(strategy_id="world_model", status="open")` — enforce max 3 concurrent
7. **Verify IB connection** — halt on disconnect
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Hard Stop Override (MANDATORY, runs FIRST)

**The 3% hard stop ALWAYS overrides the world model's predictions. No exceptions.**

1. Call `get_portfolio_pnl()` for current P&L
2. For each strategy-39 position with `pnl_pct <= -3.0%`:
   a. Check `get_open_orders()` — skip if SELL order already exists
   b. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "world_model"`
   d. Close in `strategy_positions` with `exit_reason = "hard_stop_3pct"`
   e. **Record prediction failure:** The model predicted this position would be profitable — log the discrepancy between predicted trajectory and actual outcome
   f. Log to `lessons` with trade details and model prediction vs reality comparison
3. For accidental short positions:
   a. Call `place_order(symbol, action="BUY", quantity=abs(N), order_type="MKT")`
   b. Close with `exit_reason = "close_accidental_short"`
4. Reconcile: `get_closed_trades(save_to_db=True)`
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Current State Observation
1. **Scanner snapshot:** Call `get_scanner_results(scanner, date, top_n=20)` for all 33 scanner/tier combinations
   - Build a 33-dimensional rank vector (rank per scanner/tier, -1 if absent)
   - Record which symbols appear on which scanners

2. **Price snapshot for all scanner candidates:** Call `get_quote(symbol)` for each unique symbol
   - Last price, bid, ask, spread, volume

3. **Intraday bars:** Call `get_historical_bars(symbol, duration="1d", bar_size="5min")` for top 10 candidates
   - OHLCV bars for the current session

4. **Technical indicators:** Call `calculate_indicators(symbol, indicators=["RSI", "VWAP", "ATR", "EMA9", "EMA21"], duration="1d", bar_size="5min", tail=20)` for top 10 candidates

### Observation Vector Construction
5. For each candidate, construct the observation vector:
   - Scanner ranks across all 33 scanner/tier slots (33 dims)
   - Price features: last, spread%, intraday_return%, volume_ratio (4 dims)
   - Technical: RSI, ATR, VWAP_dist, EMA_ratio (4 dims)
   - Time features: minutes_since_open, minutes_to_close (2 dims)
   - **Total observation: 43 dimensions per candidate**

6. Stack observations for top 10 candidates → observation tensor (10 × 43)

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Step 1: Encode Current State
1. Pass the observation tensor through the **Representation network** (CNN encoder):
   - Input: 10 × 43 observation tensor
   - Output: 128-dimensional latent state vector `z_0`

### Step 2: Trajectory Simulation (MPC — Model Predictive Control)
2. Define the action space for each step:
   - `BUY(symbol_i)` for i in 1..10 candidates
   - `SELL(symbol_j)` for j in currently held positions
   - `HOLD` — no action
3. For each of **50 trajectories**, simulate 10 steps (50 minutes):
   a. Sample a random action sequence (or use CEM/cross-entropy method for directed search)
   b. For each step t = 0..9:
      - Feed `z_t` + `action_t` into the **Transition network** (GRU):
        - `z_{t+1} = GRU(z_t, action_t)`
      - Feed `z_{t+1}` into the **Reward network** (MLP):
        - `r_{t+1} = RewardMLP(z_{t+1})` — predicted P&L for this step
      - Accumulate: `total_reward += γ^t × r_{t+1}` where γ = 0.99 (discount factor)
   c. Record the total discounted reward for this trajectory

### Step 3: Select Best Action (MPC)
4. Rank all 50 trajectories by total discounted reward
5. Select the **first action** from the top-ranked trajectory
6. This is the action to execute NOW — the remaining trajectory steps are discarded (replanning next cycle)

### Step 4: Validation via Decoder
7. Feed `z_1` (predicted next state) through the **Decoder network**:
   - Predicted scanner ranks and prices for the next 5-minute step
   - Compare with actual values from the previous cycle to maintain prediction accuracy buffer
8. Log: best trajectory reward, worst trajectory reward, action selected, decoder prediction, planning time in ms

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
If the selected action is a BUY, verify via `get_quote(symbol)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Position limit:** Current strategy-39 open positions < 3 (max 3 concurrent)
6. **No duplicate:** No existing position or order for this symbol
7. **Model confidence:** Best trajectory reward > 0 (model predicts profit)
8. **Prediction accuracy:** Rolling prediction error < 50% threshold (strategy not halted)

Log rejection to `scanner_picks` with `rejected=1` and `reject_reason`.

### Order Placement
If action is BUY and all checks pass:

1. Position sizing:
   - `size_pct = 1.0%` of account value (fixed for world model strategy)
   - `quantity = floor(account_value × 0.01 / ask_price)`
   - `stop_price = entry_price × (1 - 0.03)` — hard 3% stop (overrides model)
   - `target_price` = determined by model's predicted optimal exit from best trajectory
2. Place orders:
   a. `place_order(symbol, action="BUY", quantity=N, order_type="MKT")` — entry
   b. `place_order(symbol, action="SELL", quantity=N, order_type="STP", stop_price=stop_price)` — hard stop
   c. If model predicts target, `place_order(symbol, action="SELL", quantity=N, order_type="LMT", limit_price=target_price)`
3. Log to `orders`, `strategy_positions`, `scanner_picks`:
   - Include `trajectory_reward`, `planned_hold_steps`, `predicted_exit_step`, `planning_time_ms`

If action is SELL (model recommends exit for existing position):
1. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
2. Cancel associated stop/target orders via `cancel_order(order_id)`
3. Close in `strategy_positions` with `exit_reason = "model_planned_exit"`

If action is HOLD:
1. No orders placed — log to `scan_runs` that model chose to wait

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-39 position every 5-minute run:

1. Call `get_quote(symbol)` for current price
2. Log `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct
3. Call `get_position_price_history(position_id)` for trajectory analysis

### Prediction vs Reality Divergence Check (CRITICAL)
4. Compare the model's predicted state (from decoder at entry) with actual current state:
   - Compute divergence: `|predicted_price - actual_price| / actual_price`
   - Compute scanner rank divergence: mean absolute rank difference across scanners
   - **Weighted divergence score** = 0.7 × price_divergence + 0.3 × rank_divergence
5. **Divergence thresholds:**
   - < 20%: Normal — model tracking well, continue
   - 20-50%: Caution — tighten stop to 2%, log warning
   - **> 50%: HALT** — model has diverged from reality
     - Exit ALL strategy-39 positions immediately via `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
     - Set strategy status to HALTED in database
     - Log lesson: "World model prediction diverged >50% from reality — all positions closed"
     - Strategy remains halted until next model retraining and validation

6. Update prediction accuracy buffer (rolling 20 entries)
7. Update position extremes: MFE, MAE, peak, trough, drawdown

### MPC Replanning
8. Re-run the full planning cycle (Phase 4) for held positions:
   - If the replanned best action for a held position is SELL → exit at next cycle
   - If replanned action is HOLD → continue holding
   - Log replanning results

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

### On Exit (hard stop, model exit, divergence halt, or manual)

1. Close position in `strategy_positions`:
   - `exit_reason` options: `"hard_stop_3pct"`, `"model_planned_exit"`, `"divergence_halt"`, `"replan_exit"`, `"eod_close"`, `"manual"`
2. Log to `lessons` table:
   - symbol, strategy_id="world_model"
   - entry_price, exit_price, pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - **Model-specific fields:**
     - trajectory_reward_at_entry, actual_reward
     - prediction_error_at_exit (predicted vs actual)
     - planned_hold_steps vs actual_hold_steps
     - divergence_score_at_exit
   - lesson text (e.g., "Model predicted +2.1% over 30 min, actual was -0.8%. Scanner dynamics shifted faster than GRU transition model could track. Retrain needed.")
3. **Add (predicted, actual) pair to training buffer** for next retraining cycle
4. Compute KPIs via `get_strategy_kpis_report(strategy_id="world_model")`
5. Write lesson file to `data/lessons/` if significant divergence or insight

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="world_model":
   - Trajectories simulated: 50
   - Planning time (ms)
   - Best/worst/mean trajectory rewards
   - Action taken (BUY/SELL/HOLD)
   - Prediction error (rolling average)
   - Divergence scores for held positions
   - Model status: ACTIVE or HALTED
3. Compute `strategy_kpis` if positions closed:
   - Win rate, avg P&L, Sharpe ratio, max drawdown
   - **World model KPIs:** mean prediction error, divergence frequency, planned vs actual hold ratio, model accuracy (% of predictions within 20%)
4. Call `complete_job_execution(exec_id, summary)`

---

## Model Training / Retraining Schedule

### Architecture Details
| Component | Architecture | Input | Output |
|-----------|-------------|-------|--------|
| Representation | CNN (3 conv layers, 64→128 filters) | Observation tensor (10×43) | Latent state z (128-dim) |
| Transition | GRU (128 hidden, 1 layer) | z_t (128) + action (one-hot) | z_{t+1} (128) |
| Reward | MLP (128→64→1) | z (128) | Scalar reward |
| Decoder | MLP (128→64→43) | z (128) | Predicted observation (43-dim) |

### Training Data
- Source: Historical scanner snapshots + price data + trade outcomes
- Window: Rolling 30 days
- Sampling: 5-minute intervals during market hours → ~4,680 timesteps per day × 30 days = ~140K samples
- Sequence length for GRU: 10 steps (50 minutes)

### Training Procedure
1. **Representation + Transition + Decoder** trained jointly with reconstruction loss:
   - `L_recon = MSE(Decoder(Transition(Repr(obs_t), action_t)), obs_{t+1})`
2. **Reward model** trained separately on (latent_state, actual_pnl) pairs:
   - `L_reward = MSE(RewardMLP(z), actual_pnl)`
3. **Optimizer:** Adam, lr=0.0003, batch_size=64, epochs=100
4. **Validation:** 20% holdout, monitor reconstruction error and reward prediction error

### Retraining Triggers
- **Scheduled:** Every Sunday evening
- **Triggered:** Prediction divergence > 50% (strategy HALTED — retrain required to resume)
- **Triggered:** Win rate drops below 30% over 20 trades
- **Emergency:** 3 consecutive hard stop exits

### Post-Retraining Validation
1. Validate on 5-day holdout: prediction error must be < 25%
2. Run 100 trajectory simulations on holdout data: cumulative reward must be positive
3. If validation passes → deploy and un-HALT strategy
4. If validation fails → keep strategy HALTED, log alert, retry with different hyperparameters

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each 5-min cycle | Phase 0 (start), every phase, Phase 8 (complete) |
| `scanner_picks` | Candidates with model scores and trajectory rewards | Phase 3, 4, 5 |
| `orders` | Entry, stop, target, model-exit orders | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with prediction metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + divergence data each cycle | Phase 6 |
| `strategy_runs` | Per-cycle model diagnostics (planning time, errors) | Phase 8 |
| `scan_runs` | Overall cycle summary | Phase 8 |
| `lessons` | Trade lessons with predicted vs actual analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, prediction accuracy, divergence stats | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — scanner data for observation construction
- `get_scanner_dates()` — available data dates
- `get_quote(symbol)` — real-time price for features and monitoring
- `get_historical_bars(symbol, duration, bar_size)` — OHLCV bars for observation tensor
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — technical indicators
- `get_positions()` — current IB positions
- `get_portfolio_pnl()` — P&L for hard stop enforcement
- `get_open_orders()` — existing order check
- `get_closed_trades(save_to_db)` — reconcile closed positions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — execute trades
- `cancel_order(order_id)` — cancel orders on model-planned exit
- `modify_order(order_id, quantity, limit_price, stop_price)` — adjust stops
- `get_strategy_positions(strategy_id, status, limit)` — query strategy-39 positions
- `get_strategy_kpis_report(strategy_id)` — KPI computation
- `get_trading_lessons(limit)` — prior lessons
- `get_scan_runs(limit)` — scan history
- `get_job_executions(job_id, limit)` — execution history
- `get_daily_kpis()` — daily metrics
- `get_position_price_history(position_id)` — position price trajectory
- `get_contract_details(symbol)` — verify tradability
