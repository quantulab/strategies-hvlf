---
noteId: "e1f7g5h371c255i5ff6cj031gg36k441"
tags: [cron, trading, strategies, multi-agent, reinforcement-learning, ppo, mappo, risk-management]

---

# Strategy 41: Multi-Agent RL — Cooperative Scanner Watchers — Operating Instructions

## Schedule
Runs every 5 minutes during market hours (9:35 AM – 3:55 PM ET) via Claude Code CronCreate.
Each agent evaluates its assigned cap tier independently, then shares signals via learned communication channel.
Job ID: `strategy_41_multi_agent_rl`

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap (Agent 1), MidCap (Agent 2), SmallCap (Agent 3)
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_41_multi_agent_rl")` — returns `exec_id`
2. After each phase, call `update_job_execution(exec_id, ...)` with progress and counts
3. On completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**Additional tracking per agent: `agent_1_action`, `agent_2_action`, `agent_3_action`, `comms_latency_ms`, `risk_off_triggered`.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply learned rules
2. **Verify all 3 agents are loaded and operational:**
   - **Agent 1 (LargeCap):** PPO policy network for LargeCap scanners
   - **Agent 2 (MidCap):** PPO policy network for MidCap scanners
   - **Agent 3 (SmallCap):** PPO policy network for SmallCap scanners
   - Each agent has: actor (MLP: obs→action), critic (MLP: obs→value), communication encoder (MLP: obs→16-dim message)
   - **Centralized critic:** Shared value function V(s_global) used during training only
3. **Test communication channel:**
   - Each agent sends a 16-dimensional test message
   - Measure round-trip latency between all agent pairs
   - If any agent's comms latency > 5 seconds → **fall back to independent mode** (no message passing)
   - Log: `comms_mode = "cooperative"` or `"independent"`
4. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
5. **Check open orders** via `get_open_orders()`
6. **Count open strategy-41 positions** via `get_strategy_positions(strategy_id="multi_agent_rl", status="open")`:
   - Total max: 6 positions (shared portfolio)
   - Per agent max: 2 positions each
   - Count per agent: `agent_1_positions`, `agent_2_positions`, `agent_3_positions`
7. **Check daily loss limits:**
   - Per-agent daily realized P&L: must be > -1% of account per agent
   - Portfolio daily realized P&L: must be > -2% of account total
   - If any limit breached → that agent (or all agents) halted for the day
8. **Verify IB connection** — halt on disconnect
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

### Individual Position Stops
1. Call `get_portfolio_pnl()` for current P&L
2. For each strategy-41 position:
   a. Apply the ATR-based stop computed at entry (or default 4% if no ATR available)
   b. If `pnl_pct <= -stop_pct`:
      - Check `get_open_orders()` — skip if SELL order exists
      - Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
      - Log to `orders` with `strategy_id = "multi_agent_rl"`, include `agent_id`
      - Close in `strategy_positions` with `exit_reason = "stop_loss"`
      - Log to `lessons`

### Risk-Off Protocol (Communication-Based)
3. **Any agent can broadcast a RISK-OFF message.** Triggers:
   - Agent's daily P&L drops below -0.75% (approaching -1% limit)
   - Agent detects its cap tier has > 60% of stocks on loss scanners
   - Agent's last 3 trades were all losses
4. **On RISK-OFF message receipt → ALL agents close ALL positions:**
   a. For each open strategy-41 position across all agents:
      - Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
      - Close with `exit_reason = "risk_off_protocol"`
   b. Log: which agent triggered risk-off, reason, portfolio state at time of trigger
   c. **All agents halted for 30 minutes** (6 cycles) after risk-off
   d. After 30 minutes, agents resume but with half position sizes for the rest of the day

### Daily Loss Limit Enforcement
5. Calculate each agent's daily realized P&L from `strategy_positions` (closed today, strategy_id="multi_agent_rl"):
   - If Agent N daily P&L ≤ -1% → halt Agent N for remainder of day
   - If total portfolio daily P&L ≤ -2% → halt ALL agents for remainder of day
6. Reconcile: `get_closed_trades(save_to_db=True)`
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Per-Agent Observation Construction
Each agent observes only its assigned cap tier's scanners:

**Agent 1 (LargeCap):**
1. Call `get_scanner_results(scanner="GainSinceOpen", date="today", top_n=20)` filtered for LargeCap
2. Repeat for all 11 scanner types with LargeCap tier
3. Build observation vector (per candidate):
   - Scanner ranks across 11 scanner types (11 dims, -1 if absent)
   - Call `get_quote(symbol)`: price, spread%, volume (3 dims)
   - Call `calculate_indicators(symbol, indicators=["RSI", "ATR", "VWAP"], duration="1d", bar_size="5min", tail=20)`: RSI, ATR, VWAP_dist (3 dims)
   - Call `get_historical_bars(symbol, duration="1d", bar_size="5min")`: 5-min momentum, 15-min momentum (2 dims)
   - Agent's own position state: num_positions, daily_pnl (2 dims)
   - **Total observation: 21 dimensions per candidate**

**Agent 2 (MidCap):** Same structure, filtered for MidCap tier
**Agent 3 (SmallCap):** Same structure, filtered for SmallCap tier

### Communication Messages (if cooperative mode)
4. Each agent encodes its observation into a **16-dimensional message vector**:
   - `message_i = CommEncoder_i(observation_i)` — learned MLP: 21→16 dims
5. Messages are broadcast to all other agents
6. Each agent augments its observation with received messages:
   - `augmented_obs_i = concat(observation_i, message_j, message_k)` for j,k = other agents
   - Augmented observation: 21 + 16 + 16 = 53 dimensions
7. In **independent mode** (comms fallback), agents use only their 21-dim observation

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Per-Agent Policy Evaluation
For each active agent (not halted):

1. **Feed augmented observation into actor network:**
   - Actor MLP: 53-dim input (or 21-dim in independent mode) → action distribution
   - Actions: {BUY(candidate_1), ..., BUY(candidate_K), SELL(held_1), ..., SELL(held_M), HOLD}
   - Output: probability distribution over actions via softmax
2. **Sample action from policy:**
   - Use the highest-probability action (greedy during live trading, not exploration)
   - Record action probability for logging
3. **Value estimation (for monitoring only, not used for action selection):**
   - Feed global state (all 3 agents' observations concatenated) into centralized critic
   - V(s_global) estimates expected portfolio Sharpe ratio from this state
   - Log value estimate for tracking model confidence

### Cross-Agent Coordination
4. If Agent 1 wants to BUY symbol X and Agent 3 also wants to BUY symbol X:
   - Priority: agent with higher action probability gets the trade
   - Other agent must pick next-best action
   - Log conflict resolution
5. If all 3 agents choose HOLD → no trades this cycle
6. **Position allocation check:**
   - Agent can only BUY if it has < 2 open positions
   - Total portfolio must have < 6 open positions
   - If agent is at limit, force action to HOLD or SELL

### Signal Summary
7. For each BUY action selected:
   - Record: agent_id, symbol, cap_tier, action_probability, value_estimate, scanners_present
   - Log to `scanner_picks` with `strategy_id = "multi_agent_rl"`, `agent_id`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
For each agent's BUY action, verify via `get_quote(symbol)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Agent position limit:** Agent has < 2 open positions
6. **Portfolio position limit:** Total strategy-41 positions < 6
7. **No duplicate:** No existing position or order for this symbol across any agent
8. **Daily loss check:** Agent not halted, portfolio not halted
9. **Action probability:** Must be > 0.3 (agent must be reasonably confident)

Log rejection to `scanner_picks` with `rejected=1`, `reject_reason`, `agent_id`.

### Order Placement
For each BUY passing all checks:

1. Position sizing:
   - Base: 1% of account per position (max 2% per agent = 2 positions, max 6% total = 6 positions)
   - In risk-off recovery mode (post 30-min halt): 0.5% per position
   - `quantity = floor(account_value × size_pct / ask_price)`
2. Stop and target computation:
   - Call `calculate_indicators(symbol, indicators=["ATR"], duration="1d", bar_size="5min", tail=20)`
   - `stop_price = entry_price - 1.5 × ATR` (or entry × 0.96 if ATR unavailable)
   - `target_price = entry_price + 2.5 × ATR` (or entry × 1.04 if ATR unavailable)
3. Place orders:
   a. `place_order(symbol, action="BUY", quantity=N, order_type="MKT")` — entry
   b. `place_order(symbol, action="SELL", quantity=N, order_type="STP", stop_price=stop_price)` — stop
   c. `place_order(symbol, action="SELL", quantity=N, order_type="LMT", limit_price=target_price)` — target
4. Log to database:
   - `scanner_picks`: symbol, agent_id, cap_tier, action_probability, scanners_present
   - `orders`: symbol, strategy_id="multi_agent_rl", agent_id, full order details
   - `strategy_positions`: strategy_id="multi_agent_rl", agent_id, symbol, entry_price, stop_price, target_price, action_probability, value_estimate, comms_mode

For each SELL action:
1. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
2. Cancel associated stop/target orders via `cancel_order(order_id)`
3. Close in `strategy_positions` with `exit_reason = "agent_policy_exit"`

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-41 position every 5-minute run:

1. Call `get_quote(symbol)` for current price
2. Log `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct, agent_id
3. Call `get_position_price_history(position_id)` for trajectory

### Per-Agent Monitoring
4. For each agent, compute:
   - Current unrealized P&L across its positions
   - Distance to daily loss limit (-1%)
   - Whether a risk-off broadcast is warranted
5. **Communication health check:**
   - Measure inter-agent message latency
   - If latency > 5 seconds → switch to independent mode
   - Log mode transitions

### Cross-Agent Portfolio View
6. Aggregate across all agents:
   - Total unrealized P&L
   - Total realized P&L today
   - Distance to portfolio daily loss limit (-2%)
   - Portfolio concentration: are all positions in the same sector?
7. **Sector concentration alert:** If > 4 of 6 positions are in the same sector:
   - Flag to agents via communication channel
   - Next BUY must be in a different sector (diversification message)

8. Update position extremes: MFE, MAE, peak, trough, drawdown per position

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

### On Exit (stop, target, policy exit, risk-off, or manual)

1. Close position in `strategy_positions`:
   - `exit_reason` options: `"stop_loss"`, `"take_profit"`, `"agent_policy_exit"`, `"risk_off_protocol"`, `"daily_limit_halt"`, `"eod_close"`, `"manual"`
2. Log to `lessons` table:
   - symbol, strategy_id="multi_agent_rl", agent_id
   - entry_price, exit_price, pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - **Multi-agent-specific fields:**
     - agent_id, cap_tier
     - action_probability_at_entry
     - comms_mode_at_entry: "cooperative" or "independent"
     - messages_received_at_entry: summary of other agents' communications
     - risk_off_triggered: true/false
     - cross_agent_conflict: was there a BUY conflict with another agent?
   - lesson text (e.g., "Agent 3 (SmallCap) exited BIRD at +2.1%. Communication from Agent 1 indicated large-cap rotation into biotech, which confirmed small-cap momentum. Cooperative signal added conviction.")
3. **Store experience tuple for training:**
   - (state, action, reward, next_state, done) for the exiting agent
   - Reward = realized P&L as fraction of account
   - These tuples feed into the next retraining cycle
4. Compute KPIs via `get_strategy_kpis_report(strategy_id="multi_agent_rl")`
5. Write lesson file to `data/lessons/` for significant events (risk-off triggers, agent disagreements, cooperative wins)

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="multi_agent_rl":
   - Per-agent summary: action taken, positions held, daily P&L, status (active/halted)
   - Communication mode: cooperative or independent
   - Comms latency (ms)
   - Risk-off events this session
   - Cross-agent conflicts resolved
   - Portfolio allocation: {agent_1: N positions, agent_2: N, agent_3: N}
3. Compute `strategy_kpis` if positions closed:
   - **Per-agent KPIs:** win rate, avg P&L, Sharpe per agent
   - **Portfolio KPIs:** overall win rate, portfolio Sharpe, max drawdown
   - **Cooperation KPIs:**
     - Cooperative vs independent mode win rate comparison
     - Risk-off trigger frequency
     - Communication value: P&L difference between cooperative and independent periods
     - Agent disagreement rate
4. Call `complete_job_execution(exec_id, summary)`

---

## Model Training / Retraining Schedule

### Architecture Details
| Component | Per Agent | Shared |
|-----------|-----------|--------|
| Actor | MLP: 53→64→32→N_actions (cooperative) or 21→32→16→N_actions (independent) | — |
| Comm Encoder | MLP: 21→16 (produces 16-dim message) | — |
| Critic | — | MLP: 63→128→64→1 (centralized, takes all agents' obs: 21×3=63) |

### Training Procedure — MAPPO (Multi-Agent PPO)

**Phase A: Independent Training (Epochs 1-10)**
1. Train each agent's actor independently using standard PPO:
   - No communication, 21-dim observations only
   - Each agent learns its own cap tier's dynamics
   - Clipping parameter ε = 0.2, GAE λ = 0.95, discount γ = 0.99
2. Reward: individual agent's trade P&L (not portfolio Sharpe yet)
3. Collect 5,000 experience tuples per agent per epoch

**Phase B: Cooperative Training (Epochs 11-30)**
1. Enable communication channel — agents send/receive 16-dim messages
2. Expand actor input to 53 dimensions (obs + 2 received messages)
3. Train communication encoders jointly with actors
4. **Centralized critic** V(s_global) trained on all agents' observations:
   - Input: concatenation of all 3 agents' raw observations (63 dims)
   - Used only for advantage estimation during training (CTDE: Centralized Training, Decentralized Execution)
5. **Reward: Portfolio Sharpe ratio** (shared reward for all agents):
   - Sharpe = mean(daily_returns) / std(daily_returns) computed over the episode
   - This incentivizes cooperation over individual optimization
6. Collect 10,000 experience tuples per epoch (shared across agents)

### Training Data
- Source: Historical scanner data + trade outcomes from all strategies
- Window: 30 days rolling
- Episode: 1 trading day (9:35 AM – 3:55 PM, ~78 steps at 5-min intervals)
- Batch size: 256 transitions, 4 mini-batches per epoch

### Retraining Triggers
- **Scheduled:** Every Sunday evening
- **Triggered:** Portfolio Sharpe drops below 0.5 over rolling 20 trading days
- **Triggered:** Any single agent's win rate drops below 30%
- **Triggered:** Risk-off triggers more than 3 times in a single week
- **Emergency:** Portfolio daily loss limit (-2%) hit on 2 consecutive days

### Retraining Procedure
1. Collect latest 30 days of experience tuples from database
2. Run Phase A (10 epochs independent) + Phase B (20 epochs cooperative)
3. Validate on 5-day holdout:
   - Portfolio Sharpe must be > 0 on holdout
   - No agent's win rate < 35%
   - Cooperative mode must outperform independent mode
4. If validation passes → deploy new policies
5. If validation fails → keep old policies, log alert, retry with adjusted hyperparameters

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each 5-min cycle | Phase 0 (start), every phase, Phase 8 (complete) |
| `scanner_picks` | Candidates per agent with action probabilities | Phase 3, 4, 5 |
| `orders` | Entry, stop, target orders with agent_id | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with agent assignment and comms state | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price data per position per cycle | Phase 6 |
| `strategy_runs` | Per-cycle multi-agent diagnostics | Phase 8 |
| `scan_runs` | Overall cycle summary | Phase 8 |
| `lessons` | Trade lessons with cooperative analysis | Phase 2, 7 |
| `strategy_kpis` | Per-agent and portfolio KPIs, cooperation metrics | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — per-tier scanner data for each agent
- `get_scanner_dates()` — available data dates
- `get_quote(symbol)` — real-time price for quality gate and monitoring
- `get_historical_bars(symbol, duration, bar_size)` — intraday bars for observations
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — RSI, ATR, VWAP for features and stop sizing
- `get_positions()` — current IB positions
- `get_portfolio_pnl()` — P&L for risk management and daily limits
- `get_open_orders()` — existing order check
- `get_closed_trades(save_to_db)` — reconcile closed positions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — execute trades
- `cancel_order(order_id)` — cancel orders on agent exit
- `modify_order(order_id, quantity, limit_price, stop_price)` — adjust stops
- `get_strategy_positions(strategy_id, status, limit)` — query per-agent positions
- `get_strategy_kpis_report(strategy_id)` — per-agent and portfolio KPIs
- `get_trading_lessons(limit)` — prior lessons
- `get_scan_runs(limit)` — scan history
- `get_job_executions(job_id, limit)` — execution history
- `get_daily_kpis()` — daily performance metrics
- `get_position_price_history(position_id)` — position trajectory
- `get_contract_details(symbol)` — verify tradability
