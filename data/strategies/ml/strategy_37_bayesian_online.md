---
noteId: "a7b3c1d037e811f1bb28f607cc92g007"
tags: [cron, trading, strategies, bayesian, adaptive, risk-management]

---

# Strategy 37: Bayesian Online Learning — Adaptive Scanner Thresholds — Operating Instructions

## Schedule
Runs every 5 minutes during market hours (9:35 AM – 3:55 PM ET) via Claude Code CronCreate.
Job ID: `strategy_37_bayesian_online`

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_37_bayesian_online")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned from prior strategies
2. **Load prior state** — retrieve the Beta distribution parameters for each (scanner_type, cap_tier) pair from `strategy_kpis` or the strategy's persisted state in the database:
   - Initialize as Beta(α=5, β=5) if no prior exists (uniform-ish prior centered at rank 5 out of 10)
   - Each pair has its own α, β parameters: e.g., `(HotByVolume, SmallCap) → Beta(7, 4)`
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check current open orders** via `get_open_orders()`
5. **Count open strategy-37 positions** via `get_strategy_positions(strategy_id="bayesian_online", status="open")` — enforce max 3 concurrent
6. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, error_message)` and halt
7. **Load trade counter** — count total trades since last prior reset from `strategy_positions` where `strategy_id="bayesian_online"`. If counter ≥ 20, check variance convergence (see Model Training section).
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 4% stop-loss rule on ALL strategy-37 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each strategy-37 position with `pnl_pct <= -4.0%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")` to liquidate
   c. Log to `orders` table with `strategy_id = "bayesian_online"`
   d. Close position in `strategy_positions` with `exit_reason = "stop_loss_4pct"`
   e. **Bayesian update (loss):** For each scanner that triggered this entry, update the Beta posterior:
      - β_new = β_old + 1 (discourage the rank that was used for entry)
   f. Log to `lessons` table with full trade details including the scanner ranks at entry
3. For short positions (quantity < 0) created accidentally:
   a. Call `place_order(symbol, action="BUY", quantity=abs(N), order_type="MKT")` to close
   b. Log with `exit_reason = "close_accidental_short"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. For positions closed by stop/limit orders in IB, update `strategy_positions` and log lessons
   c. Apply Bayesian updates for any closed positions not yet processed
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Scanner Ingestion (every 5 minutes)
1. Call `get_scanner_results(scanner="all", date="today", top_n=20)` for each scanner type × cap tier combination (11 types × 3 tiers = 33 scanner calls)
2. For each stock appearing on any scanner, record:
   - `symbol`, `scanner_type`, `cap_tier`, `rank` (1-based position in scanner)
   - `timestamp` of this scanner snapshot
3. Build the **rank feature vector** per symbol:
   - For each (scanner_type, cap_tier) the stock appears on, record its rank
   - Stocks not appearing on a scanner get rank = ∞ (excluded from that scanner's analysis)

### Cross-Scanner Aggregation
4. Identify symbols appearing on **≥ 2 different scanner types** (not just different tiers of the same scanner):
   - These are the candidates for this strategy
   - Log all candidates to `scanner_picks` with `strategy_id = "bayesian_online"`
5. For each candidate, call `get_quote(symbol)` to get:
   - Last price, bid, ask, spread, volume
6. For each candidate, call `calculate_indicators(symbol, indicators=["RSI", "VWAP", "ATR"], duration="1d", bar_size="5min", tail=20)` to get:
   - RSI(14), VWAP distance, ATR(14) for stop/target sizing
7. Call `get_historical_bars(symbol, duration="1d", bar_size="1min")` for intraday price action context

### Feature Summary per Candidate
- Scanner ranks across all scanner types where present
- Number of distinct scanner types (must be ≥ 2)
- RSI, VWAP distance, ATR, spread, volume
- Price relative to day's high/low

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Bayesian Credible Interval Check
For each candidate symbol and each (scanner_type, cap_tier) where it appears:

1. **Retrieve current posterior** Beta(α, β) for that (scanner_type, cap_tier)
2. **Compute the 80% credible interval** for the "optimal entry rank":
   - Lower bound = Beta.ppf(0.10, α, β) × max_rank
   - Upper bound = Beta.ppf(0.90, α, β) × max_rank
   - Where max_rank = 20 (top_n from scanner)
3. **Check if stock's observed rank falls within the 80% credible interval:**
   - If rank is within [lower, upper] → this scanner "votes" for entry
   - If rank is outside → this scanner does not vote

### Candidate Scoring
4. For each candidate, count the number of scanners that "vote" for entry
5. **Entry condition:** A candidate qualifies if:
   - ≥ 2 scanners vote for entry (rank within credible interval on ≥ 2 scanner types)
   - The candidate is the **top-ranked** among all qualifying candidates (by total vote count, then by average rank)
6. If multiple candidates tie, prefer the one with the lowest posterior variance (more certain signal)

### Position Sizing — Inverse Variance
7. For the selected candidate, compute position size:
   - `avg_variance` = mean of Beta variance across all voting scanners
   - Beta variance = (α × β) / ((α + β)² × (α + β + 1))
   - `size_pct` = min(2.0%, 0.5% / avg_variance)
   - This means higher certainty (lower variance) → larger position, capped at 2% of account
8. Log signal details to `scanner_picks`: symbol, scanners_present, conviction_score = vote_count, position_size_pct

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** Last price >= $2.00 — reject sub-$2 stocks
2. **Minimum volume:** Volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** (ask - bid) / last <= 3% — reject wide spreads
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Position limit:** Current strategy-37 open positions < 3 (max 3 concurrent)
6. **No duplicate:** No existing position or open order for this symbol across any strategy
7. **Account exposure:** Total strategy-37 exposure < 6% of account (3 positions × 2% max each)

Log rejection reason to `scanner_picks` table if any check fails (`rejected=1`, `reject_reason="..."`).

### Order Placement
If all checks pass:

1. Compute entry, stop, and target prices:
   - `entry_price` = current ask (market order will fill near ask)
   - `stop_price` = entry_price × (1 - 0.04) — 4% stop loss
   - `target_price` = entry_price × (1 + 0.03) — 3% take profit
2. Calculate quantity from position size:
   - `quantity` = floor(account_value × size_pct / entry_price)
   - Minimum 1 share
3. Place orders:
   a. `place_order(symbol, action="BUY", quantity=N, order_type="MKT")` — entry
   b. `place_order(symbol, action="SELL", quantity=N, order_type="STP", stop_price=stop_price)` — stop loss
   c. `place_order(symbol, action="SELL", quantity=N, order_type="LMT", limit_price=target_price)` — take profit
4. Log to database:
   - `scanner_picks`: symbol, scanner, rank, conviction_score, action="BUY", rejected=0
   - `orders`: symbol, strategy_id="bayesian_online", action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status
   - `strategy_positions`: strategy_id="bayesian_online", symbol, entry_price, stop_price, target_price, entry_order_id, stop_order_id, target_order_id, scanners_at_entry (JSON list), conviction_score, posterior_params (JSON: {scanner: {alpha, beta}})

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-37 position every 5-minute run:

1. Call `get_quote(symbol)` for current price data
2. Log to `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct, distance_to_stop, distance_to_target
3. Call `get_position_price_history(position_id)` to check for trailing stop adjustments
4. **Re-check scanner presence:**
   - If the stock has dropped off ALL scanners for 2 consecutive runs (10 minutes), consider tightening stop to breakeven
   - Log scanner status changes
5. **Re-score Bayesian signal:**
   - If the stock's rank has moved outside the 80% credible interval on all scanners, flag for early exit review
6. Update position extremes: peak price, trough price, max favorable excursion (MFE), max adverse excursion (MAE), current drawdown from peak

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

### On Exit (stop hit, target hit, manual close, or signal loss)

1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: `"stop_loss_4pct"`, `"take_profit_3pct"`, `"signal_lost"`, `"manual"`, `"eod_close"`
2. **Bayesian posterior update:**
   - **Profitable trade (P&L > 0):** For each scanner that voted for entry:
     - α_new = α_old + 1 (reinforce the rank that produced a winner)
   - **Losing trade (P&L ≤ 0):** For each scanner that voted for entry:
     - β_new = β_old + 1 (discourage the rank that produced a loser)
   - Persist updated (α, β) parameters to the database for next cycle
3. Log to `lessons` table:
   - symbol, strategy_id="bayesian_online", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanners_at_entry, exit_reason
   - posterior_before (JSON), posterior_after (JSON)
   - lesson text: describe what the Bayesian update learned (e.g., "Rank 3 on HotByVolume/SmallCap reinforced as profitable entry point")
4. Compute and log KPIs via `get_strategy_kpis_report(strategy_id="bayesian_online")`
5. If significant pattern emerges (e.g., a specific scanner/tier pair converging to a narrow credible interval), write lesson file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="bayesian_online" with:
   - Number of scanner pairs checked
   - Number of candidates passing credible interval filter
   - Current posterior parameters snapshot (top 5 most-traded scanner/tier pairs)
   - Average posterior variance across all pairs
3. Compute `strategy_kpis` if any positions were closed this cycle:
   - Win rate, avg P&L, Sharpe ratio, max drawdown, expectancy
   - **Bayesian-specific KPIs:** average credible interval width, variance trend (decreasing = learning)
4. Call `complete_job_execution(exec_id, summary)` with full summary of all operations

---

## Model Training / Retraining Schedule

### Online Learning (continuous)
- Bayesian updates happen in real-time after every closed trade (Phase 7)
- No batch training required — the Beta-Bernoulli conjugate prior updates analytically

### Prior Reset Conditions
Check after every 20 trades (tracked by trade counter since last reset):

1. **Variance convergence check:** For each (scanner_type, cap_tier) pair:
   - Compute current variance: Var = (α × β) / ((α + β)² × (α + β + 1))
   - Compare to variance from 20 trades ago
   - If variance has NOT decreased for ANY pair with ≥ 5 trades → that pair's prior needs reset
2. **Reset procedure:**
   - Reset the non-converging pair to Beta(α=5, β=5)
   - Log reset event to `lessons` table with reason
   - Preserve converging pairs — do NOT reset everything
3. **Full reset trigger:** If >50% of pairs fail convergence → reset ALL pairs to Beta(5, 5) and log as a major lesson

### End-of-Day Summary (3:55 PM)
- Persist all posterior parameters to database
- Log daily posterior evolution to `strategy_kpis`
- Generate summary of which scanner/tier pairs have tightest credible intervals (most learned)

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each 5-min cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate found with rank, vote count, credible interval check | Phase 3, 4, 5 |
| `orders` | Every order placed (entry, stop, target) | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with posterior params at entry | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-run summary with posterior state | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with Bayesian updates and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, variance trends, credible interval widths | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — fetch scanner rankings per type/tier
- `get_scanner_dates()` — check available scanner data dates
- `get_quote(symbol)` — current price, bid, ask, spread, volume
- `get_historical_bars(symbol, duration, bar_size)` — intraday price action
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — RSI, VWAP, ATR
- `get_positions()` — current IB positions
- `get_portfolio_pnl()` — current P&L across all positions
- `get_open_orders()` — check for existing orders before placing new ones
- `get_closed_trades(save_to_db)` — reconcile closed positions from IB
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — execute trades
- `cancel_order(order_id)` — cancel stale stop/target orders after exit
- `modify_order(order_id, quantity, limit_price, stop_price)` — adjust stops/targets
- `get_strategy_positions(strategy_id, status, limit)` — query strategy-37 positions
- `get_strategy_kpis_report(strategy_id)` — compute and retrieve KPIs
- `get_trading_lessons(limit)` — load prior lessons for application
- `get_scan_runs(limit)` — query scan history
- `get_job_executions(job_id, limit)` — query execution history
- `get_daily_kpis()` — daily performance metrics
- `get_position_price_history(position_id)` — price trajectory for a position
