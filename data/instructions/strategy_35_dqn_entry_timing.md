---
noteId: "s35_dqn_entry_timing_01"
tags: [strategy, cron, ml, reinforcement-learning, dqn, entry-timing, epsilon-greedy]

---

# Strategy 35: DQN — Optimal Entry Timing — Operating Instructions

## Schedule

Runs every 30 seconds during market hours (9:35 AM – 3:40 PM ET) via Claude Code CronCreate.
**Critical:** This strategy runs at 30-second intervals (not 10 minutes) because the DQN agent makes ENTER/WAIT/ABORT decisions in real-time after a scanner signal fires.
Each decision cycle takes <5 seconds of inference time.
Max 4 trades per day.

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Model artifacts: `D:\src\ai\mcp\ib\models\dqn\entry_timing_dqn.pt` (weights), `D:\src\ai\mcp\ib\models\dqn\replay_buffer.pkl` (experience replay)
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every 30-second cycle MUST be tracked. To avoid log bloat, use lightweight tracking:

1. Call `start_job_execution(job_id="strategy_35_dqn_entry")` — returns `exec_id`
2. Only call `update_job_execution` on phase transitions where actions occur (skip phases with no activity)
3. On successful completion, call `complete_job_execution(exec_id, summary)` — keep summary compact for 30-sec cycles
4. On error, call `fail_job_execution(exec_id, error_message)`

**Batch logging:** Aggregate 30-second cycles into 10-minute summary records in `strategy_runs` to avoid table bloat.

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` — focus on timing-related lessons (entry too early, entry too late patterns)
2. **Check current state:**
   - `get_positions()` — current portfolio
   - `get_open_orders()` — pending orders
   - `get_portfolio_pnl()` — account health
3. **Count S35 trades today** via `get_strategy_positions(strategy_id="dqn_entry_timing", status="all")` filtered by today — enforce max 4/day
4. **Count active signal-tracking sessions** — how many scanner signals are currently being evaluated by the DQN (pending ENTER/WAIT/ABORT)
5. **Check DQN model artifact:** Verify `entry_timing_dqn.pt` exists and is loaded in memory
6. **Current epsilon value:** Read from training state — determines explore vs exploit ratio
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for current P&L
2. For each open S35 position with `pnl_pct <= -3.0%`:
   a. Check `get_open_orders()` — skip if SELL order exists
   b. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "dqn_entry_timing"`
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_3pct"`
   e. Log to `lessons`: include DQN state at entry, action taken, how many WAIT cycles preceded ENTER
   f. **Store transition in replay buffer:** (state, ENTER, negative_reward, terminal=True) — the DQN learns from losses
3. For S35 positions up >= 2.0% (target):
   a. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
   b. Close with `exit_reason = "take_profit_2pct"`
   c. **Store transition in replay buffer:** (state, ENTER, positive_reward, terminal=True) — the DQN learns from wins
4. **Reconcile:** `get_closed_trades(save_to_db=True)` and cross-check DB vs IB positions
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Step 1: Detect New Scanner Signals

1. Call `get_scanner_results(scanner=type, date="today", top_n=15)` for key scanners: GainSinceOpen, HotByVolume, TopGainers, HotByPrice, TopVolumeRate
2. Identify **new signals** — symbols that appeared on a scanner for the first time within the last 60 seconds
3. For each new signal, create a **signal-tracking session**:
   - `signal_symbol`: the symbol
   - `signal_time`: when first detected
   - `signal_scanner`: which scanner triggered
   - `signal_rank`: rank at detection
   - `signal_price`: price at detection via `get_quote(symbol)`
   - `decision_deadline`: signal_time + 15 minutes (must decide within this window)
   - `dqn_state`: WAITING (the DQN will decide ENTER/WAIT/ABORT every 30 sec)

### Step 2: Build DQN State Vector

For each active signal-tracking session, construct the state vector every 30 seconds:

| State Feature | Source | Description |
|---------------|--------|-------------|
| `minutes_since_signal` | Derived | Float: (now - signal_time) / 60, range 0.0–15.0 |
| `price_vs_signal_price` | `get_quote(symbol)` | (current_last / signal_price) - 1.0, as percentage |
| `volume_ratio` | `get_historical_bars(symbol, duration="300 S", bar_size="1 min")` | Current 1-min volume / avg 1-min volume today |
| `rank_trajectory` | Scanner tracking | Slope of rank over last 5 snapshots (negative = improving) |
| `scanner_count` | All scanners | Number of distinct scanner types symbol currently appears on |
| `spread_pct` | `get_quote(symbol)` | (ask - bid) / last × 100 |
| `rsi_5` | `calculate_indicators(symbol, indicators=["RSI"], duration="300 S", bar_size="1 min", tail=10)` | 5-period RSI |
| `vwap_distance` | `calculate_indicators(symbol, indicators=["VWAP"], duration="1 D", bar_size="1 min", tail=5)` | (last - vwap) / vwap × 100 |
| `time_of_day` | Derived | Minutes since market open / 390, range 0.0–1.0 |
| `positions_held` | `get_positions()` | Count of current S35 positions |
| `trades_today` | Strategy tracking | Count of S35 trades completed today |
| `bid_ask_momentum` | `get_quote(symbol)` | Change in (ask-bid) over last 3 quotes (widening = bad) |

**State vector dimension: 12**

### Step 3: State Normalization

- All features normalized to [-1, 1] range using running mean/std from replay buffer
- Clip extreme values at ±3 std to prevent outlier sensitivity

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### DQN Architecture (Reference)

```
Architecture:
- Input: 12-dim state vector
- Hidden: FC(12, 64) → ReLU → FC(64, 64) → ReLU → FC(64, 3)
- Output: Q-values for 3 actions: [ENTER, WAIT, ABORT]
- Target network: soft-update with τ = 0.005 every 100 steps
- Double DQN: use online network to select action, target network to evaluate
```

### Action Space

| Action | Index | Effect |
|--------|-------|--------|
| **ENTER** | 0 | Place BUY order immediately, end tracking session |
| **WAIT** | 1 | Do nothing, re-evaluate in 30 seconds |
| **ABORT** | 2 | Cancel tracking session, do not enter, end session |

### Decision Logic (per active session, every 30 seconds)

1. Construct state vector s_t from Step 2 above
2. Forward pass through DQN: Q(s_t) → [Q_enter, Q_wait, Q_abort]
3. **Epsilon-greedy action selection:**
   - With probability ε: random action (explore)
   - With probability 1-ε: argmax Q(s_t) (exploit)
   - ε schedule: starts at 1.0, decays to 0.05 over 200 training episodes (approx 40 trading days at 5 signals/day)
4. **Hard constraints override DQN:**
   - If `minutes_since_signal > 15`: force ABORT (deadline exceeded)
   - If `spread_pct > 5%`: force ABORT (too illiquid)
   - If symbol appears on LossSinceOpen or TopLosers: force ABORT (thesis broken)
   - If S35 trades today >= 4: force ABORT (daily limit)
   - If S35 open positions >= 4: force WAIT (can't enter, but don't abort — may free up)

### Reward Function (used during training, computed retroactively)

```
reward = 30_min_forward_return - transaction_cost

where:
- 30_min_forward_return = (price_at_t+30min / entry_price) - 1.0
- transaction_cost = 0.001 (10 bps for spread + commission)

Special cases:
- WAIT action: reward = 0.0 (no cost, no gain)
- ABORT action: reward = 0.0 (neutral — neither penalized nor rewarded)
- ENTER when price drops > 3% in 30 min: reward = -0.03 (capped loss)
```

### Transition Storage

After each decision, store transition in replay buffer:
- `(state, action, reward, next_state, done)`
- Reward for WAIT/ABORT is 0.0 immediately; for ENTER, reward is computed after 30 minutes
- `done = True` when: ENTER (entered trade), ABORT (cancelled), or deadline exceeded

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

**This phase runs ONLY when the DQN selects ENTER.**

### Quality Gate — Pre-Order Checks (MANDATORY)

1. **Minimum price:** `get_quote(symbol)` → last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Daily trade limit:** S35 trades today < 4
6. **No duplicate:** Symbol not already in `get_positions()` or `get_open_orders()`
7. **Account exposure:** Total S35 exposure < 4% of account

If quality gate fails, override DQN action to ABORT and store negative reward transition.

### Position Sizing

- **Size:** 1% of account value per position
- Calculate shares: `floor(account_value * 0.01 / ask_price)`

### Order Placement

1. **Entry order:** `place_order(symbol, action="BUY", quantity=shares, order_type="MKT")`
2. **Stop loss:** `place_order(symbol, action="SELL", quantity=shares, order_type="STP", stop_price=round(ask * 0.97, 2))` — 3% stop
3. **Take profit:** `place_order(symbol, action="SELL", quantity=shares, order_type="LMT", limit_price=round(ask * 1.02, 2))` — 2% target

### Database Logging (MANDATORY)

1. **`scanner_picks`**: symbol, scanner=signal_scanner, rank=signal_rank, action="BUY", rejected=0, metadata={dqn_q_values, action_selected, epsilon, minutes_waited, wait_count}
2. **`orders`**: symbol, action="BUY", quantity, order_type, order_id, strategy_id="dqn_entry_timing"
3. **`strategy_positions`**: strategy_id="dqn_entry_timing", symbol, action="BUY", quantity, entry_price, stop_price, target_price, metadata={signal_time, signal_price, signal_scanner, wait_cycles, dqn_state_at_entry, q_values_at_entry, epsilon_at_entry}

### For ABORT actions, also log:

- `scanner_picks`: symbol, rejected=1, reject_reason="dqn_abort" or "deadline_exceeded" or "hard_constraint", metadata={q_values, state_at_abort, minutes_since_signal}

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open S35 position every 30-second cycle:

1. **Price snapshot:** `get_quote(symbol)` → log to `price_snapshots` (bid, ask, last, volume, unrealized P&L)
   - **Throttle snapshots:** Only log to DB every 5th cycle (every 2.5 min) to avoid table bloat
   - Always check price in memory for stop/target evaluation
2. **Update position extremes:** peak, trough, MFE, MAE
3. **30-min reward computation:**
   - Once 30 min has elapsed since entry, compute the actual reward
   - Store completed transition in replay buffer with actual reward
   - This is critical for DQN learning — delayed reward assignment
4. **Scanner persistence check:**
   - If symbol drops off all scanners and has been held > 10 min, flag for exit
   - If symbol appears on Loser scanner, flag for immediate exit

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

Call `update_job_execution(exec_id, phase_completed=6, positions_monitored=N, snapshots_logged=N)` — only when snapshots were actually logged

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers (in priority order)

| Trigger | Action | Exit Reason |
|---------|--------|-------------|
| P&L <= -3.0% (stop hit) | Automatic (STP fills) | `stop_loss_3pct` |
| P&L >= +2.0% (target hit) | Automatic (LMT fills) | `take_profit_2pct` |
| Symbol on Loser scanner | MKT SELL | `thesis_broken_loser` |
| Off all scanners > 10 min | MKT SELL | `scanner_dropout` |
| End of day (3:45 PM) | MKT SELL | `eod_close` |

### For Each Exit

1. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")` if not already filled
2. Cancel remaining open orders via `cancel_order(order_id)`
3. Close position in `strategy_positions`: exit_price, exit_reason, pnl, pnl_pct, hold_duration_minutes
4. **Compute and store final reward** in replay buffer:
   - reward = pnl_pct / 100 (actual return, not the 30-min estimate)
   - Store as a correction to the earlier 30-min reward estimate
5. Log to `lessons` table with DQN-specific analysis:
   - How many WAIT cycles before ENTER
   - DQN Q-values at entry time
   - Epsilon at entry (was this an explore or exploit action?)
   - Price trajectory: signal_price → entry_price → exit_price
   - "Timing delta": (entry_price / signal_price - 1) — did waiting help?
   - Lesson text examples:
     - "DQN waited {wait_count} cycles ({minutes:.1f} min) before entering {symbol}. Signal price was ${signal_price}, entry at ${entry_price} ({timing_delta:+.2f}%). Final P&L: {pnl_pct}%. Waiting {'helped' if entry < signal else 'hurt'}."
     - "DQN entered {symbol} immediately (0 waits) at ε={epsilon:.2f}. This was an {'explore' if random else 'exploit'} action. P&L: {pnl_pct}%."
     - "DQN aborted {symbol} after {wait_count} waits. Price moved {price_move}% during observation window — abort was {'correct' if price_move < 0 else 'incorrect'}."
6. Compute KPIs via `get_strategy_kpis_report(strategy_id="dqn_entry_timing")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

**Note:** For 30-second cycles, Phase 8 runs fully only at end of day. During the day, log lightweight summaries.

### End-of-Day Summary

1. Log `scan_runs`: total signals detected, sessions tracked, enters, waits, aborts, trades_closed
2. Log `strategy_runs` for strategy_id="dqn_entry_timing" with:
   - Signals detected today, avg wait time before enter, abort rate
   - DQN action distribution: % ENTER / % WAIT / % ABORT
   - Current epsilon value
   - Replay buffer size
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="dqn_entry_timing")`:
   - Win rate (target: >55%)
   - Avg wait time before entry (in 30-sec cycles)
   - Timing effectiveness: avg (entry_price / signal_price - 1) — negative is good (bought lower)
   - Win rate by wait duration bucket: 0 waits, 1-5 waits, 6-10 waits, >10 waits
   - Explore vs exploit comparison: win rate on random actions vs greedy actions
   - Abort accuracy: % of aborts where price subsequently fell (correct abort)
   - Q-value calibration: avg Q_enter for winning vs losing trades
4. Call `complete_job_execution(exec_id, summary)`

---

## Model Training / Retraining Schedule

### Online Learning (Continuous)

The DQN trains continuously from its replay buffer:

| Parameter | Value |
|-----------|-------|
| Replay buffer size | 50,000 transitions |
| Mini-batch size | 32 |
| Training frequency | Every 10th decision cycle (every ~5 min) |
| Target network update | Soft update τ=0.005 every 100 steps |
| Discount factor γ | 0.99 |
| Learning rate | 1e-4 (AdamW) |
| Double DQN | Yes — online network selects, target evaluates |

### Epsilon Schedule

```
Episode 1–50:   ε = 1.0 (pure exploration — learning market dynamics)
Episode 51–100: ε = 0.5 (balanced)
Episode 101–150: ε = 0.2 (mostly exploitation)
Episode 151–200: ε = 0.1 (fine-tuning)
Episode 200+:   ε = 0.05 (maintenance exploration)
```

One "episode" = one signal-tracking session (from signal detection to ENTER or ABORT).
At ~5 signals/day, 200 episodes takes ~40 trading days.

### Offline Replay Training (Weekly)

Every Sunday:
1. Load full replay buffer (50,000 transitions)
2. Train for 1,000 gradient steps with mini-batch size 64
3. Evaluate on held-out 10% of buffer
4. Update model weights if validation loss improves
5. Save checkpoint to `entry_timing_dqn.pt`

### Experience Prioritization

- Use Prioritized Experience Replay (PER):
  - Transitions with large TD-error (surprising outcomes) are sampled more frequently
  - Priority = |TD_error| + 0.01 (small constant to ensure all transitions are sampled)
  - Importance sampling correction with β annealed from 0.4 to 1.0

### Catastrophic Forgetting Prevention

- Keep a "golden buffer" of the 1,000 most informative transitions (highest |reward|)
- Mix 20% golden buffer samples into each training batch
- Prevents the model from forgetting rare but important market events

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each 30-sec cycle | Phase 0 (start), Phases with activity (update), completion |
| `scanner_picks` | Every signal detected + DQN decisions (enter/abort) | Phase 4, 5 |
| `orders` | Every entry/exit order | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle + DQN metadata | Phase 5, 6, 7 |
| `price_snapshots` | Price history (throttled to every 2.5 min) | Phase 6 |
| `strategy_runs` | Daily summary with DQN stats | Phase 8 |
| `scan_runs` | Overall daily scan summary | Phase 8 |
| `lessons` | Exit lessons with timing analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, timing effectiveness, epsilon tracking | Phase 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_results` | 3 | Detect new signals, check scanner persistence |
| `get_scanner_dates` | 1 | Verify scanner data available |
| `get_quote` | 3, 5, 6 | Real-time price for state vector, execution, monitoring |
| `get_historical_bars` | 3 | Volume ratio, 1-min bars for state features |
| `calculate_indicators` | 3 | RSI, VWAP for state vector |
| `get_contract_details` | 5 | Validate security type |
| `get_positions` | 1, 3, 5 | Current positions for state vector and dedup |
| `get_portfolio_pnl` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders` | 1, 2, 5 | Duplicate/existing order check |
| `get_closed_trades` | 2 | Reconcile IB executions with DB |
| `place_order` | 2, 5, 7 | Entry, stop, target, and exit orders |
| `cancel_order` | 7 | Cancel remaining orders after exit |
| `get_strategy_positions` | 1, 2 | Count open/daily S35 positions |
| `get_strategy_kpis_report` | 7, 8 | Compute strategy KPIs |
| `get_trading_lessons` | 1 | Load lessons for rule application |
| `get_scan_runs` | 8 | Log daily summary |
| `get_job_executions` | 0 | Track job execution lifecycle |
| `get_daily_kpis` | 8 | Daily aggregate performance |
| `get_position_price_history` | 6 | Review price trajectory during hold |
