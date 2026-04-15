---
noteId: "TODO"
tags: [cron, trading, strategies, ml, hmm, regime-detection]

---

# Strategy 15: Scanner Regime Detector (HMM) — Operating Instructions

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:55 PM ET) via Claude Code CronCreate.
Regime classification uses a 30-minute lookback window (3 consecutive snapshots minimum before acting).
Model retraining runs weekly on Sundays at 7 PM ET.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Minute bars: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Historical bars via MCP: `get_historical_bars(symbol, duration, bar_size)`
- HMM model: `D:\src\ai\mcp\ib\data\models\hmm_regime_detector.pkl`
- Regime history: `D:\src\ai\mcp\ib\data\models\regime_history.json`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_15_hmm_regime_detector")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Regime-specific: `current_regime`, `regime_confidence`, `consecutive_windows`, `sub_strategy_active`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (especially regime-transition lessons)
2. **Load strategy file** from `data/strategies/` — confirm parameters
3. **Load HMM model** from disk:
   - If model file missing or corrupted, call `fail_job_execution(exec_id, "HMM model not found")` and abort
   - Verify model was retrained within the last 7 days
4. **Load regime history** — the last N regime classifications with timestamps
   - Count `consecutive_same_regime` — how many consecutive 10-min windows had the same classification
5. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions with `strategy_id` matching any sub-strategy: "regime_broad_rally", "regime_rotational_chop", "regime_risk_off"
6. **Check current open orders** via `get_open_orders()`
7. **Verify IB connection** — if disconnected, log error via `fail_job_execution` and attempt reconnect
8. **Daily loss limit check:** Sum all realized + unrealized P&L for strategy_15 today
   - If `daily_pnl <= -2%` of account, halt all new trades — log and skip to Phase 6
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY)

**Before any new trades, enforce the 3% stop-loss rule on ALL strategy_15 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="regime_broad_rally", status="open")` — repeat for "regime_rotational_chop" and "regime_risk_off"
3. For each position with `pnl_pct <= -3%`:
   a. Check `get_open_orders()` — skip if a SELL/COVER order already exists
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")` to liquidate
   c. Log to `orders` table with appropriate `strategy_id` (regime sub-strategy)
   d. Log to `strategy_positions` — close with `exit_reason = "stop_loss_3pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, regime at entry vs current regime
   f. Compute and log KPIs via `compute_and_log_kpis`
4. For short positions (quantity < 0) created accidentally — close with MKT BUY
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. For every position that disappeared: log to `lessons`, `strategy_positions`, and `orders`
6. **Daily loss limit enforcement:** If cumulative daily P&L for all regime sub-strategies <= -2%:
   - Close ALL open positions for strategy_15
   - Set `daily_halted = True` — no new trades for remainder of day
   - Log: "Daily loss limit -2% reached, liquidating all strategy_15 positions"
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Scanner Composition Metrics (HMM Observables)
Collect data from ALL scanner types across ALL cap tiers to compute market-wide metrics:

1. **Scanner data collection:**
   - Call `get_scanner_dates()` to confirm today's date is available
   - For each scanner type in [GainSinceOpen, LossSinceOpen, HotByVolume, TopGainers, TopLosers, MostActive, HotByPrice, TopVolumeRate, HighOpenGap, LowOpenGap]:
     - For each cap tier in [SmallCap, MidCap, LargeCap]:
       - Call `get_scanner_results(scanner="{CapTier}-{ScannerType}", date=TODAY, top_n=20)`

2. **Compute observable vector (6 features):**

   a. **Bull/Bear Ratio (`bull_bear_ratio`):**
      - `bull_count` = unique symbols appearing on GainSinceOpen + TopGainers + HighOpenGap (across all cap tiers)
      - `bear_count` = unique symbols appearing on LossSinceOpen + TopLosers + LowOpenGap (across all cap tiers)
      - `bull_bear_ratio = bull_count / max(bear_count, 1)`
      - Range: typically 0.2 to 5.0

   b. **Market Breadth (`breadth`):**
      - `total_unique_symbols` = count of distinct symbols across ALL scanners
      - `breadth = total_unique_symbols / expected_max` (normalize to 0-1)
      - High breadth = many stocks moving = broad participation
      - Low breadth = narrow leadership = concentrated moves

   c. **Turnover Rate (`turnover_rate`):**
      - Compare current snapshot symbols to prior snapshot (10 min ago)
      - `turnover_rate = symbols_changed / total_symbols` (0 to 1)
      - High turnover = rotational behavior, low turnover = trending

   d. **Cross-Cap Coherence (`cross_cap_coherence`):**
      - For each bullish scanner type, check if SmallCap, MidCap, LargeCap top-5 have overlapping directional bias
      - `coherence = correlation(small_cap_direction, large_cap_direction)` (-1 to +1)
      - High coherence = broad rally/selloff, low = cap-tier divergence

   e. **Volume Concentration (`volume_concentration`):**
      - `top3_volume_share` = volume of top-3 MostActive symbols / total MostActive volume
      - High concentration = narrow volume leadership

   f. **Scanner Velocity (`scanner_velocity`):**
      - `new_entries_rate` = count of symbols appearing on ANY scanner for the first time in this snapshot / total symbols
      - High velocity = rapid rotation of names

3. **Assemble observation vector:** `[bull_bear_ratio, breadth, turnover_rate, cross_cap_coherence, volume_concentration, scanner_velocity]`

4. **Append to rolling observation buffer** — maintain last 20 observations (200 minutes)

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### HMM Regime Classification
1. **Run HMM prediction** on the observation sequence:
   - Feed the rolling buffer (up to 20 observations) into the trained Gaussian HMM
   - `current_regime = model.predict(observation_sequence)[-1]` — most recent regime
   - `regime_probabilities = model.predict_proba(observation_sequence)[-1]` — confidence per regime

2. **Regime definitions:**

   | Regime ID | Name | Characteristics | Observable Signature |
   |-----------|------|-----------------|---------------------|
   | 0 | **Broad Rally** | bull_bear_ratio > 2.0, breadth > 0.6, coherence > 0.5 | Many stocks rising across cap tiers |
   | 1 | **Rotational Chop** | bull_bear_ratio 0.7-1.5, turnover_rate > 0.4, coherence < 0.3 | Names rotating rapidly, no clear direction |
   | 2 | **Risk-Off** | bull_bear_ratio < 0.7, breadth < 0.3, volume_concentration > 0.5 | Few gainers, concentrated selling, flight to safety |

3. **Regime stability check:**
   - Append `current_regime` to regime history
   - Count `consecutive_windows` = number of consecutive 10-min windows with the same regime
   - **Minimum 3 consecutive windows before acting** — prevents whipsawing on regime transitions
   - If `consecutive_windows < 3`, log regime as "transitioning" and skip to Phase 6

4. **Select sub-strategy based on confirmed regime:**

   **Regime 0 — Broad Rally sub-strategy (`regime_broad_rally`):**
   - Trade top-ranked symbols from GainSinceOpen + TopGainers across all cap tiers
   - Favor LargeCap for stability
   - Wider stops (ATR-based), longer hold times
   - Up to 3 concurrent positions, 3% risk each

   **Regime 1 — Rotational Chop sub-strategy (`regime_rotational_chop`):**
   - Trade only on extreme rank velocity (symbols rapidly climbing scanner ranks)
   - Tighter stops (1.5% fixed), shorter hold times (max 30 min)
   - Maximum 1 concurrent position, 2% risk
   - Require symbol on 3+ scanners simultaneously for entry

   **Regime 2 — Risk-Off sub-strategy (`regime_risk_off`):**
   - **Defensive only** — no new long entries
   - If holding positions from prior regime: tighten all stops to 1.5%
   - Consider hedging via inverse ETFs if available (e.g., SH, SDS)
   - Maximum 1 position (hedge only), 1% risk

5. **Generate trade candidates** per the active sub-strategy:
   - Identify symbols meeting the sub-strategy criteria
   - Score and rank candidates

6. **Log all candidates to `scanner_picks` table:**
   - symbol, scanner, rank, conviction_score, conviction_tier, scanners_present, action, rejected flag, reject_reason, regime=current_regime, regime_confidence

7. Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run these checks via `get_quote(symbol=SYMBOL)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Current volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 2%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Not already held:** Check `get_positions()` for existing position in this strategy
6. **Not already ordered:** Check `get_open_orders()` for pending order
7. **Regime confirmed:** Verify `consecutive_windows >= 3` (re-check in case of race condition)
8. **Daily loss limit:** Verify `daily_halted != True`

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits (regime-dependent)
- **Broad Rally:** Max 3 concurrent, 3% risk each
- **Rotational Chop:** Max 1 concurrent, 2% risk
- **Risk-Off:** Max 1 concurrent (hedge only), 1% risk
- Check `get_strategy_positions(strategy_id=SUB_STRATEGY_ID, status="open")` for current count

### Order Structure (regime-dependent)

**Broad Rally orders:**
1. Entry: `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
2. Stop: `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY - 1.5*ATR)`
3. Target: `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="LMT", limit_price=ENTRY + 2.5*ATR)`

**Rotational Chop orders:**
1. Entry: `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
2. Stop: `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY * 0.985)` — tight 1.5% stop
3. Target: `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="LMT", limit_price=ENTRY * 1.02)` — quick 2% target

**Risk-Off orders (hedge):**
1. Entry: `place_order(symbol="SH", action="BUY", quantity=QTY, order_type="MKT")` — inverse S&P ETF
2. Stop: `place_order(symbol="SH", action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY * 0.985)`
3. No target — close when regime transitions away from Risk-Off

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, conviction_score, scanners_present, action, rejected=0, regime, regime_confidence
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, strategy_id=SUB_STRATEGY_ID, regime, regime_confidence
3. **`strategy_positions` table:** strategy_id=SUB_STRATEGY_ID, symbol, action, quantity, entry_price, entry_order_id, stop_price, target_price, stop_order_id, target_order_id, scanners_at_entry, conviction_score, regime_at_entry, regime_confidence_at_entry, observable_snapshot (JSON)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position under ANY strategy_15 sub-strategy:

1. Call `get_quote(symbol=SYMBOL)` to get current price data
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance_to_stop, distance_to_target, current_regime
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown_pct)
4. **Regime transition monitoring:**
   - If regime has changed since position was opened:
     - **Broad Rally → Rotational Chop:** Tighten stops to 1.5%, reduce target to 2%
     - **Broad Rally → Risk-Off:** Close all Broad Rally positions immediately at market
     - **Rotational Chop → Risk-Off:** Close all Rotational Chop positions immediately
     - **Risk-Off → Broad Rally:** Close hedge positions, prepare for long entries
     - Log regime transition event in `lessons` table
5. **Rotational Chop time stop:** If position held > 30 minutes in chop regime, prepare for exit in Phase 7

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

### On Exit (stop hit, target hit, regime transition, time stop, or daily limit)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: "stop_loss_3pct", "stop_loss_1.5pct", "take_profit_atr", "take_profit_2pct", "regime_transition", "time_stop_30min", "daily_loss_limit", "eod_close", "manual"
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id=SUB_STRATEGY_ID, action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - regime_at_entry, regime_at_exit, regime_transitions_during_hold
   - observable_vector_at_entry, observable_vector_at_exit
   - lesson text: analyze whether regime classification was correct and whether sub-strategy was appropriate
3. Compute and log KPIs for the specific sub-strategy via `compute_and_log_kpis`
4. **Regime accuracy tracking:**
   - `regime_correct = 1 if the regime-appropriate sub-strategy produced a profit, else 0`
   - Track per-regime win rates to evaluate HMM calibration
5. If regime transition caused a loss, write markdown file to `data/lessons/` analyzing the transition

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, current_regime, regime_confidence, consecutive_windows, summary
2. Log `strategy_runs` for the active sub-strategy with cycle-specific metrics:
   - regime_id, regime_name, regime_confidence, consecutive_windows
   - observable_vector (JSON), regime_transition_flag
   - positions_opened, positions_closed, positions_held
3. Compute `strategy_kpis` for each sub-strategy if positions were closed:
   - win_rate, avg_win, avg_loss, profit_factor, expectancy
   - avg_hold_duration, max_drawdown
   - Per-regime breakdown: win_rate_broad_rally, win_rate_chop, win_rate_risk_off
   - regime_accuracy (% of time regime classification led to profitable trades)
   - regime_stability (avg consecutive windows per regime)
4. Call `complete_job_execution(exec_id, summary)` with a full summary including regime state

---

## Model Training / Retraining Schedule

### HMM Training Protocol
- **Algorithm:** Gaussian Hidden Markov Model with 3 hidden states
- **Observable dimensions:** 6 (bull_bear_ratio, breadth, turnover_rate, cross_cap_coherence, volume_concentration, scanner_velocity)
- **Covariance type:** Full (allows correlated observables)
- **Number of EM iterations:** 100 with convergence threshold 1e-4

### Training Data Preparation
1. Load scanner CSVs from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for all available historical dates
2. For each 10-minute window on each day, compute the 6 observable features
3. Concatenate into observation sequences (one per trading day)
4. Minimum 30 trading days of data for initial training

### Retraining Schedule
- **Weekly** on Sundays at 7 PM ET
- Include all new data from the past week
- Retrain from scratch (HMM EM is fast enough)
- After training, verify regime labels are consistent with prior model:
  - Regime 0 should have highest bull_bear_ratio (Broad Rally)
  - Regime 2 should have lowest bull_bear_ratio (Risk-Off)
  - If labels are swapped (permutation issue), remap accordingly

### Acceptance Criteria
- Log-likelihood improvement over prior model
- Regime labels must map consistently to bull_bear_ratio ordering
- Each regime must appear in at least 10% of historical windows (no degenerate solutions)
- If criteria not met, retain previous model and log warning

### Artifacts to Save
- `hmm_regime_detector.pkl` — trained GaussianHMM model
- `regime_history.json` — rolling history of regime classifications with timestamps
- `hmm_training_report.json` — log-likelihood, regime distributions, transition matrix, emission parameters

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run with regime context | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with regime context (accepted & rejected) | Phase 4, 5 |
| `orders` | Every order with sub-strategy ID and regime info | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with regime at entry/exit and observables | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history with current regime annotation | Phase 6 |
| `strategy_runs` | Per-sub-strategy summary with regime state | Phase 8 |
| `scan_runs` | Overall scan cycle summary with regime classification | Phase 8 |
| `lessons` | Exit lessons with regime transition analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L per sub-strategy, regime accuracy metrics | Phase 2, 8 |

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data is available |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect ALL scanner types for observable computation |
| `get_quote(symbol)` | Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, duration, bar_size)` | Phase 3 — supplementary price data, Phase 5 — ATR for stops |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | Phase 5 — ATR for Broad Rally stop/target calculation |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5 — prevent duplicates |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2 (stop exits), Phase 5 (entries + brackets), Phase 6 (regime transition exits) |
| `cancel_order(order_id)` | Phase 6 — cancel existing stops/targets when regime changes |
| `modify_order(order_id, quantity, limit_price, stop_price)` | Phase 6 — tighten stops on regime transition |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check sub-strategy positions |
| `get_strategy_kpis_report(strategy_id)` | Phase 8 — compute and review KPIs per sub-strategy |
| `get_trading_lessons(limit)` | Phase 1 — load historical lessons |
| `get_scan_runs(limit)` | Phase 8 — log run summary |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_position_price_history(position_id)` | Phase 6 — review price trajectory |
| `get_daily_kpis()` | Phase 1, Phase 2 — check daily loss limit |
