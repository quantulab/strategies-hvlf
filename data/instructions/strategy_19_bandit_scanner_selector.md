---
noteId: "s19_bandit_scanner_selector"
tags: [strategy, bandit, thompson-sampling, scanner-selection, reinforcement-learning]

---

# Strategy 19: Multi-Armed Bandit — Scanner Type Selector — Operating Instructions

## Schedule
- **Scanner selection** (10:00 AM ET): Bandit selects best scanner, buy top-3 stocks
- **Monitoring** (every 10 minutes, 10:10 AM–1:00 PM ET): Monitor positions
- **Forced exit** (1:00 PM ET): Close all Strategy 19 positions
- **Reward logging** (1:10 PM ET): Compute reward, update bandit posteriors

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types (8 arms): GainSinceOpen, HighOpenGap, HotByVolume, MostActive, TopGainers, TopVolumeRate, HotByPrice, HotByPriceRange
- Cap tiers: LargeCap, MidCap, SmallCap
- Context features: VIX, S&P futures, day of week, earnings count, yesterday's winning scanner
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Bandit state: `D:\src\ai\mcp\ib\models\bandit_state.json` (alpha/beta per arm per context)

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_19_bandit")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules (cut losers, gateway disconnect, accidental shorts)
2. **Load strategy file** from `data/strategies/` — verify Strategy 19 parameters
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged with `strategy_id = "bandit_scanner"`
   - If 3 positions already open (max for this strategy), skip to Phase 6
4. **Check open orders** via `get_open_orders()` — avoid duplicates
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate**: If before 10:00 AM ET, abort — bandit selection happens at 10:00 AM only. If after 10:00 AM and positions already entered today, skip to Phase 6.
7. **Load bandit state** from `D:\src\ai\mcp\ib\models\bandit_state.json` — alpha/beta parameters for each arm
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 5% stop-loss rule on ALL Strategy 19 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each Strategy 19 position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
   c. Log to `orders` table with `strategy_id = "bandit_scanner"`, full order details
   d. Log to `strategy_positions` — close the position with `exit_reason = "stop_loss_5pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, selected scanner arm, lesson text
   f. Compute and log KPIs via `compute_and_log_kpis(strategy_id="bandit_scanner")`
3. For short positions (quantity < 0) created accidentally:
   a. Call `place_order(symbol=SYMBOL, action="BUY", quantity=ABS_SHARES, order_type="MKT")`
   b. Log with `exit_reason = "close_accidental_short"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` to sync IB executions
   b. For every Strategy 19 position that closed externally:
      - Log to `lessons`, `strategy_positions`, and `orders` tables
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 Gather Context Features

1. Call `get_quote(symbol="SPY")` for S&P 500 direction (compare to yesterday's close)
2. Call `calculate_indicators(symbol="SPY", indicators=["SMA", "RSI"], duration="5 D", bar_size="1 day", tail=3)` for trend context
3. Call `get_quote(symbol="VIX")` for current VIX level (proxy via UVXY or VXX if VIX not available)
4. Determine context vector:
   - `vix_regime`: low (<15), medium (15-25), high (>25)
   - `sp_direction`: up (SPY > yesterday close), down, flat (±0.1%)
   - `day_of_week`: Mon=0, Tue=1, ..., Fri=4
   - `earnings_density`: count of major earnings today (low/medium/high)
   - `yesterday_winner`: which scanner arm produced the best return yesterday (query from `strategy_kpis` or `lessons`)

### 3.2 Collect Scanner Data for All 8 Arms

5. For each of the 8 scanner types (arms), call `get_scanner_results(scanner=SCANNER_TYPE, date=TODAY, top_n=10)`:
   - Arm 0: `GainSinceOpen`
   - Arm 1: `HighOpenGap`
   - Arm 2: `HotByVolume`
   - Arm 3: `MostActive`
   - Arm 4: `TopGainers`
   - Arm 5: `TopVolumeRate`
   - Arm 6: `HotByPrice`
   - Arm 7: `HotByPriceRange`
6. For each arm's top-3 stocks, call `get_quote(symbol=SYMBOL)` to get current price/volume

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 Thompson Sampling — Scanner Selection

1. Load bandit state: for each arm `i`, retrieve `alpha_i` and `beta_i` (Beta distribution parameters)
   - Context-dependent: use `(vix_regime, sp_direction)` key to select the right alpha/beta pair
2. For each arm `i` (scanner type):
   a. Sample `theta_i ~ Beta(alpha_i, beta_i)`
3. Select arm with highest sampled `theta`: `selected_arm = argmax(theta_i)`
4. Log selected arm and all sampled theta values to `scanner_picks` table

### 4.2 Extract Candidates from Selected Scanner

5. From the selected scanner arm, take the **top-3 stocks** by rank
6. For each candidate, verify it is NOT on a Loser scanner:
   - Call `get_scanner_results(scanner="TopLosers", date=TODAY, top_n=20)` — if symbol present, veto
   - Call `get_scanner_results(scanner="LossSinceOpen", date=TODAY, top_n=20)` — if symbol present, veto
   - Log vetoed candidates with `reject_reason = "loser_scanner_veto"`
7. Log all candidates to `scanner_picks` table:
   - `symbol`, `scanner` (selected arm), `rank`, `conviction_score` (sampled theta), `action = "BUY"`, `rejected` flag

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, call `get_quote(symbol=SYMBOL)` and verify:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** avg daily volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** `(ask - bid) / last <= 3%` — reject wide-spread stocks
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Scanner data freshness:** Scanner snapshot must be from within the last 20 minutes

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **3** positions for Strategy 19 (top-3 from selected scanner)
- Position size: **1% of account** per position
- Calculate shares: `quantity = floor(account_value * 0.01 / last_price)`
- Check for existing position/order via `get_positions()` and `get_open_orders()` before placing

### Order Structure

For each of the top-3 candidates from the selected scanner arm:

1. **Entry order:** `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
2. **Stop loss (5%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=ENTRY * 0.95)`
3. **Take profit (3%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=ENTRY * 1.03)`

### Database Logging (for EVERY order):

1. **`scanner_picks` table:** symbol, scanner (selected arm), rank, conviction_score (sampled theta), bandit_arm_index, context_key, action="BUY", rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, pick_id, strategy_id="bandit_scanner"
3. **`strategy_positions` table:** strategy_id="bandit_scanner", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, target_price, stop/target_order_ids, scanners_at_entry, conviction_score, pick_id, bandit_arm=SELECTED_ARM

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open Strategy 19 position every 10-minute run:

1. Call `get_quote(symbol=SYMBOL)` for current price
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distances to stop/target
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown)
4. Call `get_position_price_history(position_id=POS_ID)` to review trajectory
5. **Time-based forced exit** at 1:00 PM ET:
   a. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")` for each open position
   b. Cancel open stop/target orders via `cancel_order(order_id=STOP_ORDER_ID)` and `cancel_order(order_id=TARGET_ORDER_ID)`
   c. Log exit with `exit_reason = "time_stop_1pm"`

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

1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="bandit_scanner", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - selected_arm (scanner type), sampled_theta, context_key
   - lesson text: did the bandit pick a good scanner today?

### Bandit Reward Update (1:10 PM ET — after all positions closed)

3. Compute **reward** for the selected arm:
   - `avg_return = mean(pnl_pct for all 3 stocks from selected arm over 2-hour hold)`
   - Reward = 1 if `avg_return > 0`, else 0 (binary reward for Beta-Bernoulli bandit)
4. Update bandit posteriors:
   - If reward = 1: `alpha[selected_arm][context_key] += 1`
   - If reward = 0: `beta[selected_arm][context_key] += 1`
5. Save updated bandit state to `D:\src\ai\mcp\ib\models\bandit_state.json`
6. Compute and log KPIs via `compute_and_log_kpis(strategy_id="bandit_scanner")`
7. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: selected_arm, sampled_thetas, context_key, candidates_found, candidates_rejected, orders_placed, avg_return, reward, summary
2. Log `strategy_runs` for strategy_id="bandit_scanner" with this cycle's metrics
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="bandit_scanner")`:
   - Win rate per arm, overall win rate
   - Average return per arm over trailing 20 days
   - Bandit convergence: which arm is being selected most often
   - Regret estimate: difference between best arm's return and selected arm's return
4. Call `complete_job_execution(exec_id, summary)` with full summary including bandit state

---

## Model Training / Retraining Schedule

### Bandit Initialization
- Start with uninformative priors: `alpha=1, beta=1` for all 8 arms × all context combinations
- Context keys: `(vix_regime, sp_direction)` = 3 × 3 = 9 context states
- Total parameters: 8 arms × 9 contexts × 2 (alpha, beta) = 144 values

### Ongoing Learning
- Bandit learns automatically via Bayesian updating after each trading day
- No explicit retraining needed — Thompson Sampling is online
- After 50+ trades, review arm selection distribution:
  - If one arm dominates (>60% of selections), verify it truly outperforms — may indicate under-exploration
  - Consider adding exploration bonus if exploitation is premature

### Monthly Review
- Review per-arm performance via `get_strategy_kpis_report(strategy_id="bandit_scanner")`
- Compare bandit selections against a naive strategy (always use TopGainers)
- Adjust context features if some contexts have too few observations (<10 pulls per context-arm pair)
- Consider upgrading from Beta-Bernoulli to contextual bandit (LinUCB) if context features prove predictive

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with bandit arm, theta, and rejection reasons | Phase 4, 5 |
| `orders` | Every order placed (entry, stop, target, exit) | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle with bandit arm metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with arm selection data | Phase 8 |
| `scan_runs` | Scan cycle summary with bandit context | Phase 8 |
| `lessons` | Exit lessons with arm performance and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate per arm, regret, convergence metrics | Phase 2, 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_dates()` | 3 | Verify available scanner data dates |
| `get_scanner_results(scanner, date, top_n)` | 3, 4 | Fetch data from each of 8 scanner arms + Loser veto check |
| `get_quote(symbol)` | 3, 5, 6 | Context (SPY, VIX), quality gate, position monitoring |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | 3 | SPY trend context for bandit context features |
| `get_positions()` | 1, 5 | Check current positions and slot availability |
| `get_portfolio_pnl()` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders()` | 1, 2, 5 | Prevent duplicate orders and accidental shorts |
| `get_closed_trades(save_to_db=True)` | 2 | Reconcile externally closed trades |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | 2, 5, 6 | Execute entries, stops, targets, time exits |
| `cancel_order(order_id)` | 6 | Cancel orphaned stop/target orders on time exit |
| `get_position_price_history(position_id)` | 6 | Review position trajectory |
| `get_strategy_positions(strategy_id="bandit_scanner", status, limit)` | 1, 6 | Query strategy-specific positions |
| `get_strategy_kpis_report(strategy_id="bandit_scanner")` | 7, 8 | Compute and review strategy KPIs |
| `get_job_executions(job_id="strategy_19_bandit", limit)` | 0 | Query execution history |
| `get_trading_lessons(limit)` | 7 | Review past arm performance lessons |
