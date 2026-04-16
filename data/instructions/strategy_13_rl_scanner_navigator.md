---
noteId: "TODO"
tags: [cron, trading, strategies, rl, ppo, reinforcement-learning]

---

# Strategy 13: RL Scanner Navigator — Operating Instructions

## Schedule
Runs every 30 seconds during market hours (9:35 AM – 3:00 PM ET) via Claude Code CronCreate.
**Hard cutoff at 3:00 PM ET — no new trades after this time.**
Model retraining runs on weekends using replay of historical scanner CSVs + 1-min bars.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Minute bars: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Historical bars via MCP: `get_historical_bars(symbol, duration, bar_size)`
- PPO model weights: `D:\src\ai\mcp\ib\data\models\rl_scanner_navigator.pt`
- Environment config: `D:\src\ai\mcp\ib\data\models\rl_scanner_env_config.json`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_13_rl_scanner_navigator")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - RL-specific: `agent_action`, `agent_confidence`, `shadow_mode` (True/False)
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned
2. **Load strategy file** from `data/strategies/` — confirm parameters
3. **Load PPO model weights** from disk:
   - If model file missing, call `fail_job_execution(exec_id, "PPO model weights not found")` and abort
   - Verify model checkpoint is from the current training epoch
4. **Determine operating mode:**
   - Check deployment counter: if `days_since_deployment < 10`, set `shadow_mode = True`
   - In shadow mode: generate actions but do NOT execute orders — log what WOULD have been done
5. **Check daily trade count** via `get_trading_orders(limit=50)` — filter to today's date and `strategy_id = "rl_scanner_navigator"`
   - If `trades_today >= 3`, skip to Phase 6 (monitoring only) — **hard limit: max 3 trades/day**
6. **Check current time:** If after 3:00 PM ET, skip to Phase 6 — **no new trades after 3 PM**
7. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
8. **Check current open orders** via `get_open_orders()`
9. **Verify IB connection** — if disconnected, log error via `fail_job_execution` and attempt reconnect
10. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY)

**Before any new trades, enforce the 2% risk limit on ALL strategy_13 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="rl_scanner_navigator", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -2%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")` to liquidate
   c. Log to `orders` table with `strategy_id = "rl_scanner_navigator"`
   d. Log to `strategy_positions` — close with `exit_reason = "stop_loss_2pct"`
   e. Log to `lessons` table with full trade details, agent state at entry, and lesson text
   f. Compute and log KPIs via `compute_and_log_kpis`
4. For short positions (quantity < 0) — close immediately with MKT BUY
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. For every position that disappeared: log to `lessons`, `strategy_positions`, and `orders`
6. **Daily loss limit check:** Sum all realized + unrealized P&L for strategy_13 today
   - If `daily_pnl_pct <= -2%`, halt all new trades for the remainder of the day
   - Log: `fail_job_execution(exec_id, "Daily loss limit -2% reached, halting strategy_13")`
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & State Observation Construction

### Scanner Snapshot Collection (every 30 seconds)
1. Call `get_scanner_dates()` to confirm today's date is available
2. For each scanner type in [GainSinceOpen, HotByVolume, HotByPrice, TopGainers, TopLosers, MostActive]:
   - For each cap tier in [SmallCap, MidCap, LargeCap]:
     - Call `get_scanner_results(scanner="{CapTier}-{ScannerType}", date=TODAY, top_n=10)`

### State Observation Vector (input to PPO agent)
Construct the observation as a fixed-size vector:

1. **Top-10 symbols per scanner** (encoded):
   - For each of 6 scanner types x 3 cap tiers = 18 scanner feeds:
     - Top-10 symbol hashes (integer encoding, consistent across runs)
     - Resulting in 180-element symbol identity sub-vector

2. **Target symbol rank** (if currently holding a position):
   - `target_rank`: rank of held symbol on its primary scanner (0 if not ranked)
   - `target_rank_delta`: change in rank since last observation
   - `target_scanner_count`: number of scanners symbol currently appears on

3. **Minutes since market open:**
   - `minutes_since_open`: continuous value, 0 at 9:30 AM, capped at 330

4. **Unrealized P&L state:**
   - `unrealized_pnl_pct`: current P&L percentage of open position (0 if no position)
   - `unrealized_pnl_dollars`: raw dollar P&L

5. **Trade count today:**
   - `trades_completed_today`: integer 0-3
   - `trades_remaining`: 3 - trades_completed_today

6. **Portfolio context:**
   - `total_portfolio_pnl_pct`: overall portfolio P&L today
   - `cash_available_pct`: available margin as percentage of account

7. Total observation vector size: ~190 elements (180 scanner + 10 context)

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### PPO Agent Decision
1. **Normalize observation** using running mean/std from training
2. **Forward pass** through PPO policy network:
   - Output: action probabilities for [BUY, HOLD, SELL]
   - `agent_action = argmax(action_probs)` — selected action
   - `agent_confidence = max(action_probs)` — confidence level

3. **Action interpretation:**
   - **BUY:** Agent wants to enter a new position on the highest-ranked scanner symbol
     - Select the top-ranked symbol from the most bullish scanner (GainSinceOpen preferred)
     - If already holding a position, BUY is interpreted as HOLD (single-position strategy per cycle)
   - **HOLD:** Maintain current position, no action
   - **SELL:** Exit current position immediately

4. **Hard guardrails (override agent if violated):**
   - If `trades_today >= 3` → force HOLD regardless of agent action
   - If current time >= 3:00 PM ET → force SELL if holding, otherwise HOLD
   - If `daily_pnl_pct <= -2%` → force SELL if holding, otherwise HOLD
   - If agent says BUY but no position slots available → force HOLD
   - Log any guardrail overrides with reason

5. **Shadow mode handling:**
   - If `shadow_mode = True`:
     - Log the agent's action, confidence, selected symbol, and what would have been executed
     - Do NOT proceed to Phase 5 for order execution
     - Skip directly to Phase 6 for monitoring existing positions (if any)
     - Track shadow P&L: record the price at signal time, compute hypothetical return at next observation

6. **Log all decisions to `scanner_picks` table:**
   - symbol, scanner, rank, conviction_score (agent_confidence * 100), action (BUY/HOLD/SELL), rejected flag (1 if guardrail overrode), reject_reason, strategy_id="rl_scanner_navigator"

7. Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY, only for BUY actions)
Before placing ANY order, run these checks via `get_quote(symbol=SYMBOL)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Current volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 2%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Not already held:** Check `get_positions()` for existing position
6. **Trade count:** Verify `trades_today < 3`
7. **Time check:** Verify current time < 3:00 PM ET

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **1** concurrent position for this strategy (single-symbol focus)
- **2% of account** per trade — compute quantity from account value and last price
- Max 3 trades per day (hard limit)

### Order Execution by Action Type

**BUY Action:**
1. Call `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
2. Immediately place bracket:
   - Stop loss: Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY * 0.98)` — 2% stop
   - No take-profit limit — agent decides when to SELL

**SELL Action:**
1. Cancel any open stop orders for this symbol via `cancel_order(order_id=STOP_ORDER_ID)`
2. Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")`

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, conviction_score, action, rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, stop_price, entry_price, status, strategy_id="rl_scanner_navigator", agent_action, agent_confidence
3. **`strategy_positions` table:** strategy_id="rl_scanner_navigator", symbol, action, quantity, entry_price, entry_order_id, stop_price, stop_order_id, scanners_at_entry, conviction_score, observation_snapshot (JSON)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position with `strategy_id = "rl_scanner_navigator"` every run:

1. Call `get_quote(symbol=SYMBOL)` to get current price data
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance_to_stop
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown_pct)
4. **Agent re-evaluation:** The observation vector already includes position state — if agent outputs SELL in Phase 4, it will be executed
5. **3:00 PM forced close:** If time >= 3:00 PM and position is still open:
   - Cancel all open orders for the symbol
   - Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")`
   - Log with `exit_reason = "eod_cutoff_3pm"`

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

### On Exit (stop hit, agent SELL, time cutoff, or daily loss limit)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: "stop_loss_2pct", "agent_sell", "eod_cutoff_3pm", "daily_loss_limit", "manual", "guardrail_override"
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="rl_scanner_navigator", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes (in 30-sec increments)
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - agent_action_at_entry, agent_confidence_at_entry
   - agent_action_at_exit, agent_confidence_at_exit
   - observation_snapshot_at_entry (JSON), observation_snapshot_at_exit (JSON)
   - lesson text: describe the market context and agent behavior
3. **Compute reward signal** for the training replay buffer:
   - `reward = realized_pnl_dollars - (2 * commission) - (slippage_estimate)`
   - Store reward with entry/exit observations for offline training
4. Compute and log KPIs for `rl_scanner_navigator` via `compute_and_log_kpis`
5. If significant lesson (P&L > 1% or < -1%), write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, agent_action_taken, agent_confidence, shadow_mode, summary
2. Log `strategy_runs` for `rl_scanner_navigator` with cycle-specific metrics:
   - agent_action, agent_confidence, guardrail_overrides
   - trades_today, daily_pnl, daily_pnl_pct
   - shadow_mode flag and shadow P&L if applicable
3. Compute `strategy_kpis` for `rl_scanner_navigator` if any positions were closed:
   - win_rate, avg_win, avg_loss, profit_factor, expectancy
   - avg_hold_duration, max_drawdown
   - agent_accuracy (% of BUY actions that resulted in profit)
   - guardrail_override_rate (% of actions overridden by hard rules)
   - shadow_vs_live_correlation (if in shadow period)
4. Call `complete_job_execution(exec_id, summary)` with a full summary

---

## Model Training / Retraining Schedule

### Training Protocol
- **Environment:** Custom OpenAI Gym environment replaying scanner CSVs + 1-min bars
- **State space:** 190-element observation vector (see Phase 3)
- **Action space:** Discrete(3) — BUY, HOLD, SELL
- **Reward:** Realized P&L minus estimated friction (commission + slippage)
- **Algorithm:** PPO (Proximal Policy Optimization) from Stable-Baselines3

### Training Data
1. Load scanner CSVs from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for all available historical dates
2. Load corresponding 1-min bars from `D:\Data\Strategies\HVLF\MinuteBars_SB`
3. Construct replay episodes: each trading day is one episode (9:30 AM to 3:00 PM, 30-sec steps = ~660 steps per episode)
4. Minimum 60 episodes (trading days) for initial training

### PPO Hyperparameters
- `learning_rate = 3e-4`
- `n_steps = 2048`
- `batch_size = 64`
- `n_epochs = 10`
- `gamma = 0.99`
- `gae_lambda = 0.95`
- `clip_range = 0.2`
- `ent_coef = 0.01`
- Total training steps: 1,000,000

### Retraining Schedule
- **Weekly** on Saturday at 6 PM ET
- Include all new live trading data from the past week in the replay buffer
- Fine-tune from existing weights (do not train from scratch)
- Validate on most recent 5 trading days before deploying

### Deployment Protocol
- After retraining, deploy to **shadow mode for 10 trading days**
- Compare shadow P&L to live P&L of previous model version
- Promote to live only if shadow P&L >= 80% of backtest expectation
- Keep previous model weights as fallback

### Artifacts to Save
- `rl_scanner_navigator.pt` — PPO policy and value network weights
- `rl_scanner_env_config.json` — environment configuration and normalization stats
- `rl_training_report.json` — training curves, episode rewards, validation metrics

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run (30-sec cadence) | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every agent decision (BUY/HOLD/SELL with confidence) | Phase 4, 5 |
| `orders` | Every order placed with agent action context | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with observation snapshots | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle (30-sec) | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with agent state analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, agent accuracy metrics | Phase 2, 8 |

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data is available |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect scanner state every 30 sec |
| `get_quote(symbol)` | Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, duration, bar_size)` | Phase 3 — supplementary bar data for environment state |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5 — prevent duplicates, cancel stops on SELL |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2 (stop exits), Phase 5 (entries + stops), Phase 6 (forced close) |
| `cancel_order(order_id)` | Phase 5 — cancel stop orders when agent issues SELL |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check strategy-specific positions |
| `get_strategy_kpis_report(strategy_id)` | Phase 8 — compute and review KPIs |
| `get_trading_orders(limit)` | Phase 1 — count today's trades for 3/day limit |
| `get_trading_lessons(limit)` | Phase 1 — load historical lessons |
| `get_scan_runs(limit)` | Phase 8 — log run summary |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_position_price_history(position_id)` | Phase 6 — review price trajectory |
