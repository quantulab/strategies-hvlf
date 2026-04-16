---
noteId: "s21_pairs_divergence"
tags: [strategy, pairs-trading, scanner-divergence, mean-reversion, dollar-neutral]

---

# Strategy 21: Pairs Trading — Scanner Divergence — Operating Instructions

## Schedule
- **Pair screening** (9:30 AM ET): Identify diverged pairs from scanner data
- **Monitoring** (every 10 minutes, 9:40 AM–3:50 PM ET): Monitor positions, check convergence
- **Time stop**: Close pairs not converged after 3 trading days

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Pair universe: `D:\src\ai\mcp\ib\models\pairs_universe.json`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_21_pairs")` to create a new execution record — returns `exec_id`
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
2. **Load strategy file** from `data/strategies/` — verify Strategy 21 parameters
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count pairs tagged with `strategy_id = "pairs_divergence"` — each pair = 2 positions (long + short)
   - Track pair metadata: which symbols form each pair, entry spread, current spread
4. **Check open orders** via `get_open_orders()` — avoid duplicates
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Load pair universe** from `D:\src\ai\mcp\ib\models\pairs_universe.json`:
   - Pre-defined candidate pairs: IONQ/QBTS, NIO/LCID, SOUN/BBAI, PLUG/EOSE
   - Co-appearance history and rank correlation for each pair
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the per-pair stop at 3.5σ divergence.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each active pair (long leg + short leg):
   a. Call `get_quote(symbol=LONG_SYMBOL)` and `get_quote(symbol=SHORT_SYMBOL)`
   b. Compute current spread: `spread = price_long / price_short` (or log ratio)
   c. Compute z-score: `z = (spread - spread_mean_20d) / spread_std_20d`
   d. If `abs(z) >= 3.5` (divergence widened beyond stop):
      - Close BOTH legs simultaneously:
        - Check `get_open_orders()` — skip if exit orders already exist for either leg
        - `place_order(symbol=LONG_SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
        - `place_order(symbol=SHORT_SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
      - Log to `orders` table for both legs with `strategy_id = "pairs_divergence"`
      - Log to `strategy_positions` — close both legs with `exit_reason = "stop_loss_3.5sigma"`
      - Log to `lessons` table with pair details, spread history, P&L
      - Compute KPIs via `compute_and_log_kpis(strategy_id="pairs_divergence")`
3. **Time stop check**: For pairs open > 3 trading days (measured from entry timestamp):
   a. Close both legs with `exit_reason = "time_stop_3days"`
   b. Log to all tables as above
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` to sync IB executions
   b. For every pair leg that closed externally:
      - IMMEDIATELY close the other leg to avoid unhedged exposure
      - Log to `lessons`, `strategy_positions`, and `orders` tables
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 Scanner Co-Appearance Analysis

1. Call `get_scanner_dates()` to verify available dates
2. For each scanner type, call `get_scanner_results(scanner=SCANNER_TYPE, date=TODAY, top_n=50)` to get current state
3. For each candidate pair (IONQ/QBTS, NIO/LCID, SOUN/BBAI, PLUG/EOSE), check:
   a. **Co-appearance history**: Over the last 20 trading days, how many days did both symbols appear on the same scanner? Requires historical scanner data from `\\Station001\DATA\hvlf\rotating\`
   b. **Rank correlation**: Spearman correlation of rank positions when both present on same scanner
   c. **Qualification**: Co-appearance ≥ 15 of 20 days AND rank correlation > 0.7

### 3.2 Current State Assessment

4. For each qualified pair, determine current scanner divergence:
   a. Is Symbol A on a **Gainer scanner** (TopGainers, GainSinceOpen, HighOpenGap)?
   b. Is Symbol B on a **Loser scanner** (TopLosers, LossSinceOpen, LowOpenGap)?
   c. OR vice versa (Symbol B on Gainer, Symbol A on Loser)?
   d. **Divergence trigger**: One on Gainer AND the other on Loser = active divergence signal

### 3.3 Spread Calculation

5. For each diverged pair, call `get_historical_bars(symbol=SYMBOL_A, duration="20 D", bar_size="1 day")` and `get_historical_bars(symbol=SYMBOL_B, duration="20 D", bar_size="1 day")`
6. Compute spread time series: `spread_t = log(price_A_t) - log(price_B_t)` for each day
7. Compute rolling statistics:
   - `spread_mean_20d = mean(spread over 20 days)`
   - `spread_std_20d = std(spread over 20 days)`
   - `z_score = (spread_today - spread_mean_20d) / spread_std_20d`
8. Call `get_quote(symbol=SYMBOL_A)` and `get_quote(symbol=SYMBOL_B)` for current intraday prices
9. Call `calculate_indicators(symbol=SYMBOL_A, indicators=["RSI", "ATR", "BBANDS"], duration="20 D", bar_size="1 day", tail=5)` for each leg
10. Call `calculate_indicators(symbol=SYMBOL_B, indicators=["RSI", "ATR", "BBANDS"], duration="20 D", bar_size="1 day", tail=5)` for each leg

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 Divergence Signal Detection

1. For each qualified pair with an active scanner divergence (one on Gainer, other on Loser):
   a. Check z-score of the spread: **entry requires z > 2.0 or z < -2.0** (divergence > 2σ)
   b. Determine direction:
      - If `z > 2.0`: Stock A is expensive relative to B → **SHORT A (the Gainer), LONG B (the Laggard)**
      - If `z < -2.0`: Stock B is expensive relative to A → **SHORT B (the Gainer), LONG A (the Laggard)**
   c. **The laggard (on Loser scanner) is the LONG leg. The leader (on Gainer scanner) is the SHORT leg.**

### 4.2 Conviction Scoring

2. Compute pair conviction score:
   - `+3`: z-score > 2.5σ (strong divergence)
   - `+2`: z-score 2.0-2.5σ (standard divergence)
   - `+2`: co-appearance ≥ 18 of 20 days (very high correlation)
   - `+1`: co-appearance 15-17 of 20 days (meets minimum)
   - `+1`: rank correlation > 0.8
   - `-2`: either symbol has spread > 3% (illiquid, hard to execute)
   - `-1`: either symbol on multiple Loser scanners (deep distress, may not mean-revert)

3. **Minimum conviction score of 4 required to trade.** Below 4 → reject, log to `scanner_picks`

### 4.3 Veto Rules

4. Reject the pair if:
   - Either symbol has significant news (earnings, FDA, M&A): Call `get_news_headlines(symbol=SYMBOL, provider_codes="DJ-N", start=TODAY, end=TODAY, max_results=5)` — if major event found, skip (fundamental divergence, not mean-reverting)
   - Either symbol price < $2.00
   - Either symbol daily volume < 50,000 shares
5. Log all pair candidates to `scanner_picks` table (both accepted and rejected pairs)

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, call `get_quote(symbol=SYMBOL)` for BOTH legs and verify:

1. **Minimum price:** `last >= $2.00` for both symbols — reject pair if either fails
2. **Minimum volume:** avg daily volume >= 50,000 shares for both — reject pair if either fails
3. **Maximum spread:** `(ask - bid) / last <= 3%` for both — reject pair if either fails
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Dollar-neutral check:** Verify long and short dollar amounts are within 5% of each other
6. **Borrow availability (short leg):** Call `get_contract_details(symbol=SHORT_SYMBOL)` to verify shortable

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **2 active pairs** (= 4 positions) for Strategy 21 at any time
- Position size: **1.5% of account per leg** (3% total per pair, dollar-neutral)
- Calculate shares per leg:
  - `long_shares = floor(account_value * 0.015 / long_price)`
  - `short_shares = floor(account_value * 0.015 / short_price)`
  - Adjust to ensure `long_shares * long_price ≈ short_shares * short_price` (within 5%)
- Check for existing positions via `get_positions()` and `get_open_orders()` before placing

### Order Structure — BOTH LEGS SIMULTANEOUSLY

For the LONG leg (laggard):
1. `place_order(symbol=LAGGARD, action="BUY", quantity=LONG_SHARES, order_type="MKT")`

For the SHORT leg (leader):
2. `place_order(symbol=LEADER, action="SELL", quantity=SHORT_SHARES, order_type="MKT")`

No individual stop-loss orders — pair risk is managed by z-score monitoring in Phase 6.

### Database Logging (for EVERY pair entry):

1. **`scanner_picks` table (2 rows):** One per leg — symbol, scanner (Gainer or Loser), rank, conviction_score, pair_partner, z_score_at_entry, action, rejected=0
2. **`orders` table (2 rows):** One per leg — symbol, scanner, action (BUY or SELL), quantity, order_type, order_id, entry_price, status, pick_id, strategy_id="pairs_divergence"
3. **`strategy_positions` table (2 rows):** One per leg — strategy_id="pairs_divergence", symbol, action, quantity, entry_price, entry_order_id, pair_id (shared identifier linking legs), z_score_at_entry, spread_mean_20d, spread_std_20d, entry_timestamp

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each active pair every 10-minute run:

1. Call `get_quote(symbol=LONG_SYMBOL)` and `get_quote(symbol=SHORT_SYMBOL)` for current prices
2. Compute current spread: `spread = log(long_price) - log(short_price)`
3. Compute current z-score: `z = (spread - spread_mean_20d) / spread_std_20d`
4. Log `price_snapshots` for BOTH legs with bid, ask, last, volume, unrealized P&L, current z-score
5. Update position extremes via `update_position_extremes` for both legs
6. Call `get_position_price_history(position_id=POS_ID)` for both legs to review trajectory

### Exit Conditions (checked every run):

| Condition | z-score | Action |
|-----------|---------|--------|
| **Convergence (take profit)** | `abs(z) < 0.5` | Close both legs — profit target reached |
| **Divergence blowout (stop)** | `abs(z) >= 3.5` | Close both legs — spread widened beyond tolerance |
| **Time stop** | Open > 3 trading days | Close both legs — convergence too slow |
| **Leg imbalance** | One leg closed externally | Close remaining leg immediately |

7. **On convergence exit** (`abs(z) < 0.5`):
   a. `place_order(symbol=LONG_SYMBOL, action="SELL", quantity=LONG_SHARES, order_type="MKT")`
   b. `place_order(symbol=SHORT_SYMBOL, action="BUY", quantity=SHORT_SHARES, order_type="MKT")`
   c. Log both exits with `exit_reason = "convergence_profit"`

8. **On stop exit** (`abs(z) >= 3.5`):
   a. Close both legs as above
   b. Log both exits with `exit_reason = "stop_loss_3.5sigma"`

9. **On time stop** (3 trading days elapsed):
   a. Close both legs as above
   b. Log both exits with `exit_reason = "time_stop_3days"`

10. **Scanner status update**: Check if pair divergence is still reflected in scanners
    - Call `get_scanner_results(scanner="TopGainers", date=TODAY, top_n=30)` and `get_scanner_results(scanner="TopLosers", date=TODAY, top_n=30)`
    - If BOTH symbols have left their respective scanners (divergence no longer scanner-visible), note in monitoring log

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

### On Pair Exit (convergence, stop, time stop, or manual close)

1. Close BOTH positions in `strategy_positions` with exit_price, exit_reason, P&L per leg
2. Compute **pair P&L**: `pair_pnl = long_leg_pnl + short_leg_pnl` (dollar and percentage)
3. Log to `lessons` table with full pair trade details:
   - pair_symbols (e.g., "IONQ/QBTS"), strategy_id="pairs_divergence"
   - long_symbol, long_entry_price, long_exit_price, long_pnl
   - short_symbol, short_entry_price, short_exit_price, short_pnl
   - pair_pnl_total, pair_pnl_pct
   - z_score_at_entry, z_score_at_exit, max_z_score_during_hold
   - hold_duration_minutes, hold_duration_days
   - convergence_speed: time from max divergence to convergence
   - lesson text: did the pair mean-revert as expected? Was scanner divergence a reliable signal?
4. Compute and log KPIs via `compute_and_log_kpis(strategy_id="pairs_divergence")`
5. **Update pair universe quality:**
   - If pair produced a loss: increment loss_count for this pair in `pairs_universe.json`
   - If loss_count > 3 consecutive: demote pair from active universe
   - If pair produced a profit: reset loss_count
6. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: pairs_screened, pairs_diverged, pairs_entered, pairs_converged, pairs_stopped, summary
2. Log `strategy_runs` for strategy_id="pairs_divergence" with this cycle's metrics
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="pairs_divergence")`:
   - Win rate (pair-level, not leg-level)
   - Average pair P&L, max drawdown per pair
   - Average convergence time (minutes/days)
   - Convergence rate: % of pairs that converge within 3-day window
   - Per-pair performance: which pairs (IONQ/QBTS, NIO/LCID, etc.) perform best
   - Z-score entry accuracy: mean z at entry vs optimal entry z
4. Call `complete_job_execution(exec_id, summary)` with full summary

---

## Model Training / Retraining Schedule

### Weekly Pair Universe Update (Sunday)
1. Scan last 20 trading days of scanner data to find co-appearing pairs:
   - For every pair of symbols, count days both appeared on the same scanner
   - Compute Spearman rank correlation when co-appearing
2. **Qualification criteria**: co-appearance ≥ 15 of 20 days AND rank correlation > 0.7
3. Update `D:\src\ai\mcp\ib\models\pairs_universe.json` with:
   - Qualified pairs, co-appearance counts, rank correlations
   - Historical spread mean/std for each pair
   - Performance history (win/loss from `strategy_kpis`)
4. Starting pair universe: IONQ/QBTS, NIO/LCID, SOUN/BBAI, PLUG/EOSE
   - Add new pairs that meet criteria
   - Remove pairs that fail criteria or have 3+ consecutive losses

### Monthly Review
- Review per-pair performance via `get_strategy_kpis_report(strategy_id="pairs_divergence")`
- Analyze convergence patterns: which market conditions favor mean-reversion?
- Adjust z-score thresholds: entry (currently 2σ), exit (0.5σ), stop (3.5σ)
- Review time stop (currently 3 days): extend if convergence is profitable but slow
- Consider adding more pairs from scanner data analysis
- Review whether scanner-based divergence is more predictive than price-only divergence

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every pair candidate (both legs) with z-score and rejection reasons | Phase 4, 5 |
| `orders` | Every order placed (entry and exit for both legs) | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle for each leg with pair_id linking | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each leg each cycle, with z-score | Phase 6 |
| `strategy_runs` | Per-strategy summary with pair convergence stats | Phase 8 |
| `scan_runs` | Scan cycle summary with pair screening results | Phase 8 |
| `lessons` | Exit lessons with pair P&L, convergence analysis, and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate per pair, convergence rate, z-score accuracy | Phase 2, 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_dates()` | 3 | Verify available scanner data dates |
| `get_scanner_results(scanner, date, top_n)` | 3, 4, 6 | Fetch scanner data for co-appearance and divergence detection |
| `get_quote(symbol)` | 2, 3, 5, 6 | Current prices for spread calculation, quality gate, monitoring |
| `get_historical_bars(symbol, duration, bar_size)` | 3 | 20-day price history for spread mean/std calculation |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | 3 | RSI, ATR, BBANDS for each leg |
| `get_news_headlines(symbol, provider_codes, start, end, max_results)` | 4 | Check for fundamental events that break correlation |
| `get_contract_details(symbol)` | 5 | Verify short-leg borrow availability |
| `get_positions()` | 1, 5 | Check current positions and pair count |
| `get_portfolio_pnl()` | 1, 2 | P&L for stop enforcement |
| `get_open_orders()` | 1, 2, 5 | Prevent duplicate orders and accidental shorts |
| `get_closed_trades(save_to_db=True)` | 2 | Reconcile externally closed trades, detect leg imbalance |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | 2, 5, 6 | Execute entries and exits for both legs |
| `cancel_order(order_id)` | 6 | Cancel orders when closing pair |
| `get_position_price_history(position_id)` | 6 | Review leg trajectory and spread evolution |
| `get_strategy_positions(strategy_id="pairs_divergence", status, limit)` | 1, 6 | Query active pairs and their metadata |
| `get_strategy_kpis_report(strategy_id="pairs_divergence")` | 7, 8 | Compute and review pair-level KPIs |
| `get_job_executions(job_id="strategy_21_pairs", limit)` | 0 | Query execution history |
