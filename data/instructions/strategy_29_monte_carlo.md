---
noteId: "a29f3c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy-29, monte-carlo, simulation, kde, risk-management]

---

# Strategy 29: Monte Carlo Simulation — Scanner Outcome Distributions — Operating Instructions

## Schedule

- **Daily model refresh:** 8:30 AM ET via Claude Code CronCreate (`job_id = "monte_carlo_refresh"`)
- **Live trading:** Every 10 minutes during market hours 9:45 AM - 2:45 PM ET (`job_id = "monte_carlo"`)
- **Hard close:** 3:00 PM ET -- all positions must be closed
- **End-of-day summary:** 4:05 PM ET

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- 40-day historical scanner data: via `get_scanner_dates()` and `get_scanner_results()` for each date
- Minute bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="monte_carlo")` to create a new execution record -- returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` -- apply rules learned
2. **Load KDE model** (built during 8:30 AM daily refresh, stored in `strategy_runs` metadata):
   - Conditional return distributions by: rank bucket (1-5, 6-10, 11-20), scanner type, time-of-day bucket
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Confirm no more than 4 open positions for this strategy
4. **Check current open orders** via `get_open_orders()`
5. **Verify IB connection** -- if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate:** Do not open new positions after 2:45 PM ET (must close by 3:00 PM)
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

**Before any new trades, enforce stops on ALL strategy-29 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="monte_carlo", status="open")` to identify this strategy's positions
3. For each open position:
   a. **Simulation stop (10th percentile):** If price hits the 10th percentile of the original Monte Carlo draw, exit
      - Check `price_snapshots` for current price vs pre-computed 10th percentile stop
      - If triggered: `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
      - Log with `exit_reason = "simulation_stop_p10"`
   b. **Hard stop:** If `pnl_pct <= -4%` (absolute backstop beyond simulation):
      - `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
      - Log with `exit_reason = "hard_stop_4pct"`
   c. **Time stop:** If position held > 60 minutes past original hold estimate, exit
      - `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
      - Log with `exit_reason = "time_stop"`
4. **3:00 PM hard close:** If current time >= 3:00 PM ET, close ALL strategy-29 positions
5. Call `get_closed_trades(save_to_db=True)` to reconcile with IB
6. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3A: Daily KDE Model Build (8:30 AM refresh only)

1. Call `get_scanner_dates()` to get available historical dates
2. For the most recent 40 trading days, for each date:
   - Call `get_scanner_results(scanner=TYPE, date=DATE, top_n=20)` for all scanner types and cap tiers
   - For each symbol that appeared, call `get_historical_bars(symbol=SYM, duration="1 D", bar_size="1 min")` to get intraday returns
3. Build conditional return dataset:
   - For each observation: record `(rank, scanner_type, time_bucket, forward_30min_return)`
   - Time buckets: 9:30-10:00, 10:00-10:30, 10:30-11:00, 11:00-12:00, 12:00-1:00, 1:00-2:00, 2:00-3:00
   - Rank buckets: 1-5 (top), 6-10 (mid), 11-20 (lower)
4. Fit kernel density estimation (KDE) to each conditional group:
   - Gaussian kernel with bandwidth selected via Scott's rule
   - Minimum 50 observations per group required
   - Groups with < 50 obs are merged with adjacent rank bucket
5. Store fitted KDE parameters in `strategy_runs` with `run_type = "kde_model_build"`
6. Log total observations per group, bandwidth, and data quality metrics

### 3B: Live Candidate Collection (every 10-min run)

1. Pull current scanner results for momentum scanners:
   - `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByPrice", date="YYYY-MM-DD", top_n=20)` (all tiers)
2. For each unique symbol in top-20:
   - Record: symbol, scanner_type, rank, current_time_bucket
   - Call `get_quote(symbol=SYM)` for current price, volume, bid/ask
   - Call `calculate_indicators(symbol=SYM, indicators=["RSI", "ATR"], duration="1 D", bar_size="1 min", tail=20)`

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Monte Carlo Simulation (per candidate)

For each candidate from Phase 3B:

1. **Look up conditional KDE** for this candidate's (rank_bucket, scanner_type, time_bucket)
2. **Check minimum observation count:** If the KDE group has < 50 historical observations, REJECT
   - Log to `scanner_picks` with `reject_reason = "insufficient_historical_obs"`, `obs_count = N`
3. **Draw 1000 random samples** from the fitted KDE
4. **Compute simulation statistics:**
   - `P_win = count(samples > 0.02) / 1000` -- probability of > 2% gain
   - `P_loss = count(samples < -0.03) / 1000` -- probability of > 3% loss
   - `E_return = mean(samples)` -- expected return
   - `CVaR_5 = mean(samples[samples <= percentile(samples, 5)])` -- conditional value-at-risk at 5th percentile
   - `p10 = percentile(samples, 10)` -- 10th percentile (stop level)
   - `p75 = percentile(samples, 75)` -- 75th percentile (target level)
   - `median_return = median(samples)`

### Entry Criteria (ALL must be met)

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| P(>2%) | >= 0.55 | Majority of simulated outcomes are profitable |
| P(<-3%) | <= 0.15 | Tail risk is contained |
| E[return] | > 0.8% | Positive expected value after costs |
| CVaR (5%) | > -4% | Worst-case 5% scenarios are survivable |
| Historical obs | >= 50 | Statistical reliability of KDE |

### Position Sizing: Half-Kelly

1. Compute Kelly fraction: `f* = (P_win * avg_win - P_loss * avg_loss) / avg_win`
   - `avg_win = mean(samples[samples > 0])`
   - `avg_loss = abs(mean(samples[samples < 0]))`
2. Half-Kelly: `position_pct = min(f* / 2, 0.02)` -- cap at 2% of account
3. Calculate quantity: `qty = floor(account_value * position_pct / last_price)`

### Candidate Ranking

If multiple candidates qualify, rank by E[return] descending. Enter highest expected return first, up to max 4 positions.

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Pre-Order Quality Checks (MANDATORY)

For each qualifying candidate, run via `get_quote(symbol=SYM)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume today >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Max positions:** 4 open positions maximum for this strategy
6. **Time gate:** Current time must be before 2:45 PM ET
7. **Not already held:** Check `get_positions()` for existing position in symbol
8. **RSI filter:** RSI (from Phase 3B) must be between 30-80 (not extremely overbought/oversold)

Log rejection reason to `scanner_picks` if any check fails.

### Order Placement

1. Call `get_quote(symbol=SYM)` for current price
2. Calculate quantity using Half-Kelly sizing (from Phase 4)
3. Entry order: `place_order(symbol=SYM, action="BUY", quantity=qty, order_type="MKT")`
4. Stop loss at 10th percentile: `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="STP", stop_price=round(last_price * (1 + p10), 2))`
   - Example: if p10 = -0.025, stop = last_price * 0.975
5. Take profit at 75th percentile: `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="LMT", limit_price=round(last_price * (1 + p75), 2))`
   - Example: if p75 = 0.04, target = last_price * 1.04

### Database Logging

For EVERY order placed, log to:
1. **`scanner_picks`:** symbol, scanner, rank, P_win, P_loss, E_return, CVaR, kelly_fraction, obs_count, strategy_id="monte_carlo"
2. **`orders`:** symbol, action, quantity, order_type, order_id, limit_price, stop_price, strategy_id="monte_carlo"
3. **`strategy_positions`:** strategy_id="monte_carlo", symbol, entry_price, stop_price (p10), target_price (p75), simulation_stats (P_win, P_loss, E_return, CVaR, median, p10, p75)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-29 position, every 10-min cycle:

1. Call `get_quote(symbol=SYM)` for current bid/ask/last/volume
2. Log to `price_snapshots`: bid, ask, last, volume, unrealized P&L, distance to stop (p10), distance to target (p75)
3. **Track actual return path vs simulation distribution:**
   - Current return = (last - entry_price) / entry_price
   - Record which percentile of the original simulation the actual return corresponds to
   - If actual return is tracking below 25th percentile for 3+ consecutive snapshots, consider early exit
4. **Dynamic stop adjustment:**
   - If unrealized P&L > 1.5%, move stop to breakeven: `modify_order(order_id=STOP_ID, stop_price=entry_price)`
   - If unrealized P&L > 3%, trail stop to +1%: `modify_order(order_id=STOP_ID, stop_price=round(entry_price * 1.01, 2))`
5. **3:00 PM hard close check:** If current time >= 2:55 PM, flag all positions for immediate exit

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

1. **Stop loss hit (10th percentile):** Automatic via STP order
2. **Take profit hit (75th percentile):** Automatic via LMT order
3. **Hard stop (4%):** Manual market sell if STP order missed
4. **Time stop (3:00 PM):** Close all remaining positions
5. **Percentile tracking exit:** If actual return tracks below 25th percentile for 30+ minutes

### Exit Execution

1. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")` (for manual exits)
2. Cancel any remaining open orders: `cancel_order(order_id=STOP_ORDER_ID)`, `cancel_order(order_id=TARGET_ORDER_ID)`
3. Close position in `strategy_positions`:
   - `exit_price`, `exit_reason` (stop_p10 / target_p75 / hard_stop / time_stop / percentile_tracking)
   - `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `actual_return_percentile` (where actual return fell in the original simulation distribution)
4. Log to `lessons` table:
   - Simulation predictions: P_win, P_loss, E_return, CVaR vs actuals
   - Which percentile did the actual outcome fall in?
   - Was the KDE well-calibrated? (actual within 40-60th percentile = well-calibrated)
   - Rank bucket accuracy: did top-5 entries outperform top-10 as expected?
   - Lesson text: calibration quality, model accuracy assessment
5. Compute KPIs via `compute_and_log_kpis(strategy_id="monte_carlo")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="monte_carlo" with:
   - Simulations run, candidates qualifying, fill rate
   - Distribution of P_win scores across candidates
   - Model calibration: predicted E_return vs actual mean return
3. Compute `strategy_kpis` for any closed positions:
   - Win rate, avg P&L, max drawdown, Sharpe ratio, avg hold time
   - **Simulation-specific KPIs:**
     - Calibration score: mean absolute difference between predicted and actual return percentile
     - P_win accuracy: correlation between predicted P_win and actual win rate
     - CVaR violation rate: % of trades where actual loss exceeded CVaR
     - Kelly efficiency: actual return vs Kelly-predicted optimal return
     - KDE group performance: which (rank, scanner, time) groups are best/worst calibrated
4. Call `complete_job_execution(exec_id, summary)` with full run summary
5. Call `get_daily_kpis()` to compare against other strategies

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| KDE model rebuild | Daily (8:30 AM) | Refit KDE on rolling 40-day window |
| Bandwidth optimization | Daily | Scott's rule re-estimation per group |
| Observation count audit | Daily | Flag groups dropping below 50 obs, merge if needed |
| Calibration backtest | Weekly | Compare last week's predictions vs actual outcomes |
| Distribution shape review | Weekly | Check for multi-modality, fat tails, skew changes |
| Full 40-day backtest | Monthly | Re-simulate all historical candidates, compute walk-forward Sharpe |

### KDE Model Build Details (8:30 AM daily)

1. Call `get_scanner_dates()` -- collect last 40 trading dates
2. For each date, pull all scanner results and match to intraday returns
3. Build dataset: `{rank_bucket, scanner_type, time_bucket, forward_30min_return}`
4. Fit Gaussian KDE per group (minimum 50 observations)
5. Validate: split into 30-day train / 10-day test, check calibration
6. Store model parameters and validation metrics in `strategy_runs`
7. Total expected observations: ~40 days x 6 scanner types x 3 tiers x 20 ranks = ~14,400 samples

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Candidates with simulation stats (P_win, CVaR, etc.) | Phase 4, 5 |
| `orders` | Entry/exit orders with simulation-derived stop/target | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle with full simulation metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + percentile tracking each cycle | Phase 6 |
| `strategy_runs` | KDE model parameters, calibration metrics | Phase 8, daily rebuild |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with simulation vs actual analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, calibration, CVaR violation rate | Phase 2, 8 |

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` -- collect scanner data for KDE fitting and live candidates
- `get_scanner_dates()` -- enumerate available historical dates for 40-day lookback
- `get_quote(symbol)` -- current price for quality gate and monitoring
- `get_historical_bars(symbol, duration, bar_size)` -- intraday returns for KDE training data
- `calculate_indicators(symbol, indicators=["RSI", "ATR"], duration="1 D", bar_size="1 min", tail=20)` -- RSI filter, ATR for context
- `get_positions()` -- check current portfolio
- `get_portfolio_pnl()` -- P&L monitoring and stop enforcement
- `get_open_orders()` -- prevent duplicates, verify stops/targets in place
- `get_closed_trades(save_to_db=True)` -- reconcile IB executions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` -- entry with STP and LMT brackets
- `cancel_order(order_id)` -- cancel stops/targets on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` -- trail stops dynamically
- `get_strategy_positions(strategy_id="monte_carlo", status, limit)` -- query positions
- `get_strategy_kpis_report(strategy_id="monte_carlo")` -- performance review
- `get_job_executions(job_id="monte_carlo", limit)` -- execution history
- `get_daily_kpis()` -- cross-strategy comparison
- `get_position_price_history(position_id)` -- detailed price path for calibration analysis
